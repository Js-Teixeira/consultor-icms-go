"""Interface Streamlit da consulta tributária por NCM."""

from html import escape
from urllib.parse import urlparse

import streamlit as st

from src.busca import consultar, texto
from src.carregamento import ErroBase, base_vazia
from src.dados import ErroConfiguracaoDados, ErroFonteDados, criar_repositorio
from src.estilos import CSS_DIROMA
from src.formatacao import (
    EXIBICAO_BENEFICIO,
    EXIBICAO_LEGISLACAO,
    campos_preenchidos,
    formatar_percentual,
    rotulo_enum,
    vigencia_exibicao,
)
from src.modelos import Candidato, ResultadoConsulta
from src.normalizacao import formatar_ncm

st.set_page_config(page_title="Consulta Tributária — Goiás", layout="centered")
st.markdown(CSS_DIROMA, unsafe_allow_html=True)

MENSAGEM_DESCRICAO = (
    "NCM encontrado. Existem tratamentos tributários que dependem da descrição "
    "específica da mercadoria. Informe a descrição do produto para aumentar "
    "a precisão da consulta."
)
ROTULOS_CONFIANCA = {
    "ALTA": "ALTA",
    "MEDIA": "MÉDIA",
    "REVISAO_NECESSARIA": "REVISÃO NECESSÁRIA",
}


def campo(rotulo: str, valor: str) -> None:
    """Mostra um campo preenchido com rótulo legível."""

    st.write(f"**{rotulo}:** {valor}")


def mostrar_vigencia(candidato: Candidato) -> None:
    """Distingue datas cadastradas da ausência de vigência específica."""

    vigencia = vigencia_exibicao(candidato)
    if vigencia == "Vigência específica não cadastrada." or vigencia.startswith(("Início da vigência:", "Fim da vigência:")):
        st.write(vigencia)
    else:
        campo("Vigência", vigencia)


def mostrar_fundamento(candidato: Candidato) -> None:
    """Apresenta apenas os dispositivos legais cadastrados para uma regra."""

    if candidato.problema_fundamento:
        st.warning(candidato.problema_fundamento)
    if not candidato.legislacao:
        return

    campos = dict(campos_preenchidos(candidato, EXIBICAO_LEGISLACAO))
    for rotulo in ("Norma", "Número", "Ano", "Anexo", "Artigo", "Parágrafo", "Inciso", "Alínea", "Item"):
        if rotulo in campos:
            campo(rotulo, campos[rotulo])
    if "Resumo" in campos:
        campo("Resumo", campos["Resumo"])
    if "Trecho da legislação" in campos:
        campo("Trecho da legislação", campos["Trecho da legislação"])
    url = texto(candidato.legislacao.get("url_fonte"))
    if url:
        endereco = urlparse(url)
        if endereco.scheme in {"http", "https"} and endereco.netloc:
            st.link_button("Consultar fonte oficial", url)
        else:
            campo("URL cadastrada", url)


def mostrar_beneficio(candidato: Candidato) -> None:
    """Mostra campos cadastrados do benefício sem concluir sua aplicação legal."""

    campo("ID do benefício", candidato.identificador)
    campo("Aplicabilidade à operação consultada", candidato.aplicabilidade or "REVISAO_NECESSARIA")
    campo("Motivo da aplicabilidade", candidato.motivo_aplicabilidade)
    if candidato.aplicabilidade == "CONDICIONAL":
        st.warning("BENEFÍCIO CONDICIONAL — O NCM/produto corresponde à regra cadastrada, mas é necessário verificar as condições legais abaixo.")
    for rotulo, valor in campos_preenchidos(candidato, EXIBICAO_BENEFICIO):
        campo(rotulo, valor)
    if not candidato.cbenef:
        campo("cBenef", "cBenef não cadastrado na base atual.")
    if not texto(candidato.dados.get("escopo_operacao")):
        campo("Operação prevista", "Não definida na base")
    mostrar_vigencia(candidato)
    mostrar_fundamento(candidato)


def referencia_aliquota(resultado: ResultadoConsulta) -> Candidato | None:
    """Regra confirmada ou possibilidade única usada apenas na explicação."""

    if resultado.regra_priorizada:
        return resultado.regra_priorizada
    if len(resultado.possibilidades_aliquota) == 1:
        return resultado.possibilidades_aliquota[0]
    return None


def mostrar_trilha(resultado: ResultadoConsulta) -> None:
    """Explica a consulta em grupos legíveis, preservando todas as candidatas."""

    todos = resultado.candidatos_aliquota + resultado.candidatos_beneficio
    principal = referencia_aliquota(resultado)
    with st.expander("Como chegamos neste resultado"):
        st.markdown("##### Entrada")
        campo("NCM informado", resultado.ncm_original)
        campo("NCM normalizado", formatar_ncm(resultado.ncm_normalizado))
        campo("Descrição informada", resultado.descricao_original or "Não informada")
        campo("Operação consultada", rotulo_enum("escopo_operacao", resultado.operacao_consultada))

        st.markdown("##### Correspondência")
        campo("Quantidade de regras encontradas", str(len(todos)))
        if principal:
            campo("Regra", principal.tipo_correspondencia)
            especificidade = "8 dígitos (exata)" if principal.tipo_correspondencia == "EXATO" else f"prefixo de {len(principal.chave_ncm)} dígitos"
            campo("Especificidade", especificidade)
        elif resultado.possibilidades_aliquota:
            st.write("Há mais de uma regra de alíquota igualmente específica.")

        st.markdown("##### Descrição")
        if principal:
            descricao_regra = texto(principal.dados.get("descricao_regra"))
            if descricao_regra:
                campo("Descrição da regra", descricao_regra)
            if principal.melhor_palavra_chave:
                campo("Palavra-chave mais compatível", principal.melhor_palavra_chave)
            if principal.score_descricao is not None:
                campo("Score da descrição da regra", str(principal.score_descricao_regra) if principal.score_descricao_regra is not None else "Sem texto cadastrado")
                campo("Score da palavra-chave", str(principal.score_melhor_palavra_chave) if principal.score_melhor_palavra_chave is not None else "Sem palavra-chave cadastrada")
                campo("Score final", str(principal.score_descricao))
            else:
                st.caption("A descrição não foi informada; não houve comparação textual.")
        else:
            st.caption("Consulte as descrições de cada candidata na tabela abaixo.")

        st.markdown("##### Vigência")
        campo("Data utilizada na consulta", resultado.data_referencia.strftime("%d/%m/%Y"))
        campo("Regras descartadas por vigência", str(sum(c.vigencia == "FORA_DA_VIGENCIA" for c in todos)))

        st.markdown("##### Resultado")
        campo("ID da regra", resultado.regra_priorizada.identificador if resultado.regra_priorizada else "Nenhuma regra confirmada")
        beneficios = ", ".join(c.identificador for c in resultado.beneficios_encontrados)
        campo("ID do benefício", beneficios or "Nenhum")
        if resultado.beneficios_possiveis:
            campo("IDs de benefícios pendentes", ", ".join(c.identificador for c in resultado.beneficios_possiveis))
        if principal:
            campo("ID da legislação", texto(principal.dados.get("id_legislacao")) or "Não cadastrado")
        for motivo in resultado.motivos_confianca:
            campo("Motivo da confiança", motivo)

        if todos:
            st.markdown("##### Regras candidatas")
            st.dataframe(
                [{
                    "Categoria": "Alíquota" if c.categoria == "aliquota" else "Benefício",
                    "ID": c.identificador,
                    "Correspondência": c.tipo_correspondencia,
                    "Chave NCM": c.chave_ncm,
                    "Vigência": c.vigencia.replace("_", " ").lower(),
                    "Exige descrição": c.exige_descricao,
                    "Descrição da regra": texto(c.dados.get("descricao_regra")),
                    "Melhor palavra-chave": c.melhor_palavra_chave,
                    "Score final": c.score_descricao,
                    "ID da legislação": texto(c.dados.get("id_legislacao")),
                    "Operação prevista": rotulo_enum("escopo_operacao", c.escopo_operacao) if c.categoria == "beneficio" else "",
                    "Aplicabilidade": c.aplicabilidade or "",
                } for c in todos],
                hide_index=True,
                width="stretch",
            )


def mostrar_resultado(resultado: ResultadoConsulta) -> None:
    """Organiza os dados da consulta em cartões independentes."""

    with st.container(border=True):
        st.markdown("#### Identificação")
        campo("NCM", formatar_ncm(resultado.ncm_normalizado))
        campo("Descrição oficial", resultado.descricao_oficial or "Não cadastrada na base")
        if resultado.descricao_original.strip():
            campo("Produto informado", resultado.descricao_original)

    with st.container(border=True):
        st.markdown("#### Tratamento fiscal cadastrado")
        st.markdown("##### Alíquota interna — Goiás")
        if resultado.regra_priorizada:
            regra = resultado.regra_priorizada
            percentual = formatar_percentual(regra.dados.get("aliquota_icms"))
            st.markdown(f'<div class="diroma-rate">{escape(percentual)}</div>', unsafe_allow_html=True)
            adicional = regra.dados.get("adicional_percentual")
            if texto(adicional):
                campo("Adicional cadastrado", formatar_percentual(adicional))
        elif resultado.possibilidades_aliquota:
            st.info("O enquadramento da alíquota ainda não está confirmado. Confira as possibilidades:")
            for regra in resultado.possibilidades_aliquota:
                campo(f"Regra {regra.identificador or '(sem ID)'}", formatar_percentual(regra.dados.get("aliquota_icms")))
                campo("Correspondência", regra.tipo_correspondencia)
                mostrar_vigencia(regra)
                if regra.exige_descricao == "SIM" and not resultado.descricao_original.strip():
                    st.info(MENSAGEM_DESCRICAO)
                mostrar_fundamento(regra)
        elif resultado.situacao == "SEM_TRATAMENTO_CADASTRADO":
            st.info("Alíquota interna de Goiás ainda não cadastrada para este NCM na base.")
        else:
            st.info("Nenhuma regra de alíquota vigente encontrada para os critérios consultados.")

    with st.container(border=True):
        st.markdown("#### Benefícios encontrados")
        for beneficio in resultado.beneficios_encontrados:
            mostrar_beneficio(beneficio)
        if resultado.beneficios_possiveis:
            if not resultado.descricao_original.strip() and any(
                beneficio.exige_descricao == "SIM" for beneficio in resultado.beneficios_possiveis
            ):
                st.info(MENSAGEM_DESCRICAO)
            else:
                st.info("Há tratamentos tributários possíveis que ainda exigem confirmação do enquadramento da mercadoria.")
        if not resultado.beneficios_encontrados:
            st.info("Nenhum benefício encontrado na base atual para os critérios consultados.")

    with st.container(border=True):
        st.markdown("#### Fundamento Legal")
        if resultado.regra_priorizada:
            mostrar_fundamento(resultado.regra_priorizada)
        else:
            st.info("Sem regra única de alíquota confirmada para vincular a um fundamento legal.")

    with st.container(border=True):
        st.markdown("#### Precisão da correspondência NCM")
        nivel = ROTULOS_CONFIANCA[resultado.nivel_confianca]
        st.markdown(f'<span class="diroma-status">Precisão da correspondência NCM: {escape(nivel)}</span>', unsafe_allow_html=True)
        st.caption("Avalia a correspondência entre NCM, descrição e regra cadastrada. As condições legais de benefícios exigem verificação separada.")
        for motivo in resultado.motivos_confianca:
            campo("Motivo", motivo)

    mostrar_trilha(resultado)


st.title("Consulta Tributária — Goiás")
st.markdown('<div class="diroma-accent"></div>', unsafe_allow_html=True)
st.write("**Consulta de alíquota de ICMS e benefícios fiscais por NCM.**")
st.caption("Informe o NCM e, opcionalmente, a descrição do produto para aumentar a precisão do enquadramento.")

repositorio = None
try:
    repositorio = criar_repositorio(secrets=st.secrets)
    base = repositorio.carregar_base()
except (ErroBase, ErroConfiguracaoDados, ErroFonteDados) as exc:
    base = None
    st.error(str(exc))

if repositorio is not None:
    st.caption(f"Fonte da base: {repositorio.nome_fonte}")

sem_regras = base is not None and base_vazia(base)
if sem_regras:
    st.info("A base tributária ainda não possui regras cadastradas para consulta.")

with st.form("consulta", border=True):
    ncm = st.text_input("NCM *", placeholder="8 dígitos, com ou sem pontos")
    descricao = st.text_input("Descrição do produto (opcional)")
    operacao = st.selectbox("Operação", ("INTERNA", "INTERESTADUAL"),
                            format_func=lambda valor: rotulo_enum("escopo_operacao", valor))
    st.caption("A descrição é opcional, mas pode aumentar a precisão quando o NCM possui mais de um tratamento possível.")
    enviado = st.form_submit_button("CONSULTAR", type="primary", width="stretch")

if enviado and base is not None:
    try:
        resultado = consultar(base, ncm, descricao, operacao=operacao)
    except ValueError as exc:
        st.error(str(exc))
    else:
        if resultado.situacao == "NCM_NAO_ENCONTRADO":
            st.info("NCM não encontrado na tabela oficial cadastrada.")
            mostrar_trilha(resultado)
        elif resultado.situacao == "SEM_TRATAMENTO_CADASTRADO":
            st.info("NCM encontrado na tabela oficial, mas ainda não há tratamento tributário de Goiás cadastrado na base.")
            mostrar_resultado(resultado)
        elif resultado.situacao == "SEM_REGRA_VIGENTE":
            st.info("NCM encontrado, mas nenhuma regra correspondente está vigente na data consultada.")
            mostrar_trilha(resultado)
        else:
            mostrar_resultado(resultado)

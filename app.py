"""Consulta pública de alíquota interna de ICMS em Goiás por NCM."""

from datetime import date

import streamlit as st

from src.busca import PERCENTUAIS_BENEFICIO, consultar, pendencias_validacao, percentual_valido, texto
from src.dados import ErroConfiguracaoDados, ErroFonteDados, criar_repositorio
from src.formatacao import formatar_percentual


st.set_page_config(page_title="Alíquota interna de ICMS — Goiás", layout="centered")
st.title("Alíquota interna de ICMS — Goiás")


def exibir_data(valor):
    """Formata datas do cadastro sem atribuir vigência a campo vazio."""

    if not texto(valor):
        return "Não cadastrada"
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    try:
        return date.fromisoformat(texto(valor)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return "Data inválida no cadastro"


def exibir_regra(regra):
    beneficio = regra.tipo_tratamento == "BENEFICIO"
    rotulo = "Benefício cadastrado" if beneficio else "Regra cadastrada"
    st.subheader(f"{rotulo}: {regra.identificador}")
    if beneficio:
        tipo = texto(regra.dados.get("tipo_beneficio")).upper()
        rotulos = {"REDUCAO_BASE_CALCULO": "Redução de base de cálculo", "ISENCAO": "Isenção",
                   "CREDITO_OUTORGADO": "Crédito outorgado", "DIFERIMENTO": "Diferimento",
                   "OUTRO_BENEFICIO": "Outro benefício fiscal"}
        st.write(f"Tipo de tratamento: {rotulos.get(tipo, tipo or 'Não cadastrado')}")
        st.write(f"Escopo cadastrado da operação: {texto(regra.dados.get('escopo_operacao')) or 'Não definido'}")
    if regra.tipo_correspondencia == "EXATO":
        st.write("Tipo de correspondência: NCM exato")
        st.write(f"Código utilizado: {regra.chave_ncm}")
    else:
        st.write("Tipo de correspondência: prefixo")
        st.write(f"Prefixo utilizado: {regra.chave_ncm}")
    if beneficio:
        campos_preenchidos = [(campo, rotulo) for campo, rotulo in PERCENTUAIS_BENEFICIO
                              if texto(regra.dados.get(campo))]
        if not campos_preenchidos:
            st.write("Percentuais do benefício: não cadastrados.")
        for campo, rotulo in campos_preenchidos:
            if percentual_valido(regra.dados.get(campo)):
                st.write(f"{rotulo}: {formatar_percentual(regra.dados[campo])}")
            else:
                st.write(f"{rotulo}: percentual inválido no cadastro")
    elif percentual_valido(regra.dados.get("aliquota_icms")):
        st.write(f"Percentual informado no cadastro: {formatar_percentual(regra.dados['aliquota_icms'])}")
    else:
        st.write("Percentual inválido ou ausente no cadastro")

    for campo, rotulo in (("descricao_regra", "Descrição do tratamento"),
                          ("condicoes", "Condições de aplicação cadastradas"),
                          ("observacao", "Observações/condições cadastradas"),
                          ("palavras_chave", "Palavras-chave cadastradas")):
        valor = texto(regra.dados.get(campo))
        if valor:
            st.write(f"{rotulo}: {valor}")
    st.write(f"Vigência da regra: {exibir_data(regra.dados.get('vigencia_inicio'))} a "
             f"{exibir_data(regra.dados.get('vigencia_fim'))}")

    fundamento = regra.legislacao
    if fundamento:
        st.write("Fundamento legal cadastrado:")
        for chave, rotulo in (
            ("norma", "Norma"), ("numero", "Número"), ("ano", "Ano"),
            ("anexo", "Anexo"), ("artigo", "Artigo"), ("paragrafo", "Parágrafo"),
            ("inciso", "Inciso"), ("alinea", "Alínea"), ("item", "Item"),
            ("texto_relevante", "Trecho cadastrado"),
        ):
            valor = texto(fundamento.get(chave))
            if valor:
                st.write(f"{rotulo}: {valor}")
        st.write(f"Vigência do fundamento: {exibir_data(fundamento.get('vigencia_inicio'))} a "
                 f"{exibir_data(fundamento.get('vigencia_fim'))}")
        fonte = texto(fundamento.get("url_fonte"))
        if fonte:
            st.write(f"Fonte cadastrada: {fonte}")

    pendencias = pendencias_validacao(regra)
    if pendencias:
        st.write("Situação da validação automática do cadastro: pendente")
        for pendencia in pendencias:
            st.write(f"Pendência: {pendencia}")
    else:
        st.write("Situação da validação automática: Verificações automáticas do cadastro atendidas; "
                 "aplicabilidade à mercadoria não confirmada apenas pelo NCM.")

try:
    base = criar_repositorio(data_source="postgres", secrets=st.secrets).carregar_base()
except ErroConfiguracaoDados:
    base = None
    st.error("Consulta indisponível: conexão PostgreSQL não configurada ou configuração inválida. "
             "Contate o responsável pelo consultor.")
except ErroFonteDados:
    base = None
    st.error("Consulta indisponível: não foi possível acessar a base PostgreSQL. Tente novamente mais tarde.")

with st.form("consulta"):
    ncm = st.text_input("NCM", placeholder="12345678 ou 1234.56.78")
    enviado = st.form_submit_button("Consultar")

if enviado and base is not None:
    try:
        resultado = consultar(base, ncm)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.caption(f"Operação interna em Goiás · Data de referência: {resultado.data_referencia:%d/%m/%Y}")
        if resultado.situacao == "NCM_NAO_ENCONTRADO":
            st.info("NCM não encontrado na tabela cadastrada.")
        elif resultado.situacao in {"SEM_TRATAMENTO_CADASTRADO", "BENEFICIOS_ENCONTRADOS"}:
            if resultado.aliquota_geral_referencia is not None:
                st.subheader("Alíquota geral de referência — Goiás")
                st.write(formatar_percentual(resultado.aliquota_geral_referencia))
                st.warning(
                    "Referência geral não validada para o enquadramento da mercadoria: a ausência de "
                    "regra específica na base não comprova que não exista exceção "
                    "legal aplicável à mercadoria."
                )
                st.write("Fundamento geral: Lei nº 11.651/1991, art. 27, inciso I.")
                st.write(
                    "Fonte: https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm"
                )
            else:
                st.info("Alíquota interna não encontrada na base para este NCM.")
        elif resultado.situacao == "SEM_REGRA_VIGENTE":
            st.info("Nenhuma regra de alíquota cadastrada está vigente na data consultada.")
        else:
            if len(resultado.possibilidades_aliquota) + len(resultado.possibilidades_beneficio) > 1:
                tipos = {regra.tipo_correspondencia for regra in resultado.possibilidades_aliquota}
                if tipos == {"EXATO", "PREFIXO"}:
                    st.warning("Verificação fiscal necessária: há múltiplas regras correspondentes. "
                               "Regras por NCM exato e por prefixo não são necessariamente alternativas "
                               "equivalentes; nenhuma foi escolhida automaticamente.")
                else:
                    st.warning("Verificação fiscal necessária: há múltiplas regras correspondentes; "
                               "nenhuma foi escolhida automaticamente.")
            elif resultado.regra_priorizada is None:
                st.warning("Verificação fiscal necessária")
            for regra in resultado.possibilidades_aliquota:
                exibir_regra(regra)

        if resultado.situacao != "NCM_NAO_ENCONTRADO":
            if resultado.possibilidades_beneficio:
                st.info("Benefícios encontrados no cadastro: a correspondência por NCM não confirma "
                        "aplicabilidade. Condições e enquadramento exigem validação fiscal; "
                        "redução de base, carga efetiva e crédito outorgado não são a alíquota nominal "
                        "do ICMS e não são somados automaticamente.")
                if not resultado.possibilidades_aliquota and len(resultado.possibilidades_beneficio) > 1:
                    st.warning("Há múltiplas alternativas cadastradas; nenhuma foi escolhida automaticamente.")
                for beneficio in resultado.possibilidades_beneficio:
                    exibir_regra(beneficio)
            elif resultado.candidatos_beneficio:
                st.info("Nenhum benefício fiscal cadastrado está vigente e com escopo compatível com "
                        "a operação interna na data consultada.")
            else:
                st.info("Nenhum benefício fiscal cadastrado corresponde a este NCM.")

        if resultado.hipoteses_especiais:
            st.subheader("Possíveis enquadramentos específicos")
            st.info(
                "As hipóteses abaixo dependem das características reais da "
                "mercadoria e não constituem alíquota confirmada apenas pelo NCM."
            )
            for hipotese in resultado.hipoteses_especiais:
                st.write(f"{hipotese.descricao}: {formatar_percentual(hipotese.aliquota)}")
                st.write(f"Fundamento: {hipotese.fundamento}")
                st.write(f"Condição: {hipotese.condicao}")
                st.write("Situação: hipótese condicional não validada; vigência própria pendente de validação fiscal.")
                st.write(f"Fonte: {hipotese.fonte}")

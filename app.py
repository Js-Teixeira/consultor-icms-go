"""Consulta pública de alíquota interna de ICMS em Goiás por NCM."""

from datetime import date

import streamlit as st

from src.busca import PERCENTUAIS_BENEFICIO, consultar, pendencias_validacao, percentual_valido, texto
from src.dados import ErroConfiguracaoDados, ErroFonteDados, criar_repositorio
from src.formatacao import formatar_percentual
from src.opcoes_consulta import opcoes_consulta


st.set_page_config(page_title="Consultor ICMS GO", layout="centered")
st.title("Consultor ICMS GO")
st.caption("Consulte tratamentos de ICMS cadastrados para operações internas em Goiás. O NCM, sozinho, não confirma a aplicação de uma regra.")


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
        st.write("Alíquota nominal informada no cadastro, sem confirmação de enquadramento: "
                 f"{formatar_percentual(regra.dados['aliquota_icms'])}")
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


def selecionar_opcao(chave):
    st.session_state["opcao_selecionada"] = chave


def voltar_para_lista():
    st.session_state["opcao_selecionada"] = None


def exibir_ficha(resultado, opcao):
    st.button("Voltar", on_click=voltar_para_lista)
    codigo = resultado.ncm_normalizado
    st.subheader(f"{codigo[:4]}.{codigo[4:6]}.{codigo[6:]} — {opcao.descricao}")
    st.caption(f"Ficha individual · {opcao.natureza}")
    st.write(f"NCM: {codigo[:4]}.{codigo[4:6]}.{codigo[6:]}")
    st.write(f"Descrição específica do cadastro: {opcao.descricao}")
    icms, adicional, total = st.columns(3)
    with icms:
        st.caption("ICMS interno")
        st.write("Alíquota interna verificada: não disponível; enquadramento fiscal específico pendente.")
    with adicional:
        st.caption("Adicional")
        st.write("Adicional: aplicação não comprovada.")
    with total:
        st.caption("Carga total")
        st.write("Carga total: não calculada; incidência conjunta e base de cálculo não comprovadas.")
    if opcao.regra is not None:
        if pendencias_validacao(opcao.regra):
            st.warning("Verificação fiscal necessária para o tratamento selecionado.")
        exibir_regra(opcao.regra)
        adicional = opcao.regra.dados.get("adicional_percentual")
        if texto(adicional):
            if percentual_valido(adicional):
                st.write(f"Adicional informado no cadastro (pendente): {formatar_percentual(adicional)}")
            else:
                st.write("Adicional informado no cadastro: percentual inválido.")
        st.info("As verificações cadastrais não equivalem a aprovação fiscal da mercadoria. "
                "O adicional e a carga total dependem de fundamento e enquadramento próprios.")
    else:
        st.write("Vigência da classificação: não cadastrada.")
        st.write("Fundamento da classificação: não cadastrado.")
        st.info("Nenhum tratamento de alíquota vigente foi encontrado para esta classificação. "
                "Desdobramentos oficiais da TIPI não estão disponíveis nesta consulta; nenhum Ex foi presumido.")

    if resultado.possibilidades_beneficio:
        st.info("Benefícios com correspondência por NCM; vínculo específico com esta alternativa "
                "não comprovado. Condições e enquadramento exigem validação fiscal. "
                "Redução de base, carga efetiva e crédito outorgado são apresentados separadamente, "
                "sem combinação automática.")
        for beneficio in resultado.possibilidades_beneficio:
            exibir_regra(beneficio)
    elif resultado.candidatos_beneficio:
        st.info("Nenhum benefício fiscal cadastrado está vigente e com escopo compatível com "
                "a operação interna na data consultada.")
    else:
        st.info("Nenhum benefício fiscal cadastrado corresponde a este NCM.")


try:
    base = criar_repositorio(data_source="postgres", secrets=st.secrets).carregar_base()
except ErroConfiguracaoDados:
    base = None
    st.error("Consulta indisponível: conexão PostgreSQL não configurada ou configuração inválida. "
             "Contate o responsável pelo consultor.")
except ErroFonteDados:
    base = None
    st.error("Consulta indisponível: não foi possível acessar a base PostgreSQL. Tente novamente mais tarde.")

resultado_anterior = st.session_state.get("resultado_consulta") if base is not None else None
ficha_aberta = resultado_anterior is not None and any(
    opcao.chave == st.session_state.get("opcao_selecionada")
    for opcao in opcoes_consulta(resultado_anterior)
)
enviado = False
if not ficha_aberta:
    # O Streamlit remove o estado de widgets ocultos; guardar a pesquisa fora
    # do widget permite voltar à lista sem perder a entrada original.
    if "ncm_pesquisado" not in st.session_state:
        st.session_state["ncm_pesquisado"] = st.session_state.get("ultima_pesquisa_ncm", "")
    with st.form("consulta"):
        ncm = st.text_input("NCM", placeholder="12345678 ou 1234.56.78", key="ncm_pesquisado")
        enviado = st.form_submit_button("Consultar")

if enviado and base is not None:
    st.session_state["ultima_pesquisa_ncm"] = ncm
    st.session_state.pop("resultado_consulta", None)
    st.session_state["opcao_selecionada"] = None
    try:
        resultado = consultar(base, ncm)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.session_state["resultado_consulta"] = resultado

resultado = st.session_state.get("resultado_consulta") if base is not None else None
if resultado is not None:
    st.caption(f"Operação interna em Goiás · Data de referência: {resultado.data_referencia:%d/%m/%Y}")
    opcoes = opcoes_consulta(resultado)
    selecionada = next((o for o in opcoes if o.chave == st.session_state.get("opcao_selecionada")), None)
    if resultado.situacao == "NCM_NAO_ENCONTRADO":
        st.info("NCM não encontrado no cadastro. Confira o código informado e tente novamente.")
    elif selecionada is not None:
        exibir_ficha(resultado, selecionada)
    else:
        st.subheader("Resultados da consulta")
        st.info("Selecione uma opção cadastrada para abrir sua ficha. "
                "Tratamentos de ICMS não representam desdobramentos Ex da TIPI.")
        if len(opcoes) > 1:
            st.warning("Verificação fiscal necessária: há múltiplas regras correspondentes; "
                       "nenhuma foi escolhida automaticamente. Regras por NCM exato e por prefixo "
                       "não são necessariamente alternativas equivalentes.")
        codigo = resultado.ncm_normalizado
        formatado = f"{codigo[:4]}.{codigo[4:6]}.{codigo[6:]}"
        quantidade = len(opcoes)
        st.caption(f"{quantidade} {'opção encontrada' if quantidade == 1 else 'opções encontradas'} "
                   f"no cadastro para {formatado}.")
        for opcao in opcoes:
            identificador = f" · {opcao.regra.identificador}" if opcao.regra else ""
            st.button(f"{formatado} — {opcao.descricao}{identificador}", key=f"opcao_{opcao.chave}",
                      on_click=selecionar_opcao, args=(opcao.chave,), use_container_width=True)
            st.caption(opcao.natureza)

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


def selecionar_opcao(chave):
    st.session_state["opcao_selecionada"] = chave


def voltar_para_lista():
    st.session_state["opcao_selecionada"] = None


def exibir_ficha(resultado, opcao):
    st.button("Voltar", on_click=voltar_para_lista)
    codigo = resultado.ncm_normalizado
    st.subheader(f"{codigo[:4]}.{codigo[4:6]}.{codigo[6:]} — {opcao.descricao}")
    st.caption(f"Ficha individual · {opcao.natureza}")
    st.markdown(
        '<style>[data-testid="stMetricValue"] {font-size: 1.5rem; white-space: normal;}'
        '[data-testid="stMetricValue"] p {white-space: normal; overflow-wrap: break-word;}</style>',
        unsafe_allow_html=True,
    )
    beneficios = resultado.possibilidades_beneficio
    regras = ([opcao.regra] if opcao.regra is not None else []) + beneficios
    pendencias = [(regra, pendencias_validacao(regra)) for regra in regras]
    multiplas = len(resultado.possibilidades_aliquota) > 1
    revisao = opcao.regra is None or multiplas or any(itens for _, itens in pendencias)
    referencia = resultado.aliquota_geral_referencia if opcao.regra is None else None

    aliquota, beneficio, situacao = st.columns(3)
    with aliquota, st.container(border=True):
        if opcao.regra is not None:
            valor = opcao.regra.dados.get("aliquota_icms")
            st.metric("Alíquota", formatar_percentual(valor) if percentual_valido(valor) else "Revisar")
            st.caption("Alíquota cadastrada · ICMS nominal")
        elif referencia is not None:
            st.metric("Alíquota", formatar_percentual(referencia))
            st.caption("Referência geral · ICMS interno em Goiás")
        else:
            st.metric("Alíquota", "Em análise")
            st.caption("Sem alíquota específica para esta consulta")
    with beneficio, st.container(border=True):
        quantidade = len(beneficios)
        st.metric("Benefício", f"{quantidade} {'candidato' if quantidade == 1 else 'candidatos'}"
                  if quantidade else "Não identificado")
        st.caption("Aplicação sujeita às condições do cadastro" if quantidade else
                   "Benefício fiscal: nenhum benefício vigente identificado no cadastro")
    with situacao, st.container(border=True):
        st.metric("Situação", "Revisão fiscal" if revisao else "Cadastro localizado")
        st.caption("Confira os alertas fiscais abaixo" if revisao else
                   "Dados cadastrais consistentes; confira o enquadramento")

    st.subheader("Detalhes")
    if opcao.regra is not None:
        exibir_regra(opcao.regra)
        adicional = opcao.regra.dados.get("adicional_percentual")
        if texto(adicional):
            if percentual_valido(adicional):
                st.write(f"Adicional informado no cadastro (pendente): {formatar_percentual(adicional)}")
            else:
                st.write("Adicional informado no cadastro: percentual inválido.")
    else:
        st.write("Classificação localizada no cadastro NCM.")
        st.write("Tratamento específico de alíquota: nenhum encontrado para a data consultada.")
        if referencia is not None:
            st.write(f"Referência geral de ICMS interno em Goiás: {formatar_percentual(referencia)}.")
            st.info("Essa referência não confirma o enquadramento da mercadoria. "
                    "A operação precisa de análise fiscal; a ausência de regra específica no cadastro "
                    "não exclui exceções ou condições previstas na legislação.")

    if beneficios:
        st.subheader("Benefícios fiscais")
        st.info("Benefícios com correspondência por NCM; vínculo específico com esta alternativa "
                "pendente de validação fiscal. Confira as condições de cada candidato. "
                "Redução de base, carga efetiva e crédito outorgado são apresentados separadamente, "
                "sem combinação automática.")
        for beneficio in beneficios:
            exibir_regra(beneficio)

    st.subheader("Alertas fiscais")
    if revisao:
        st.warning("Verificação fiscal necessária: confira as pendências de cadastro e enquadramento.")
    else:
        st.write("Verificações automáticas do cadastro atendidas.")
    if opcao.regra is None:
        st.write("Vigência da classificação: pendente de cadastro.")
        st.write("Fundamento da classificação: pendente de cadastro.")
    for regra, itens in pendencias:
        if itens:
            st.markdown(f"**Pendências — {regra.identificador}**")
            for pendencia in dict.fromkeys(itens):
                st.write(f"- {pendencia}")
    if multiplas:
        st.write("Há múltiplos tratamentos cadastrados. Esta ficha mostra a opção selecionada; "
                 "nenhuma foi escolhida automaticamente.")
    if opcao.regra is not None and texto(opcao.regra.dados.get("adicional_percentual")):
        st.write("Incidência do adicional e cálculo da carga total: validação fiscal pendente. "
                 "O adicional não é somado automaticamente à alíquota.")
    st.info("O NCM sozinho não confirma o enquadramento da mercadoria. "
            "Verifique operação, descrição, fundamento e vigência. "
            "Desdobramentos oficiais exigem fonte própria; nenhum Ex foi presumido.")


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

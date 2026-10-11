"""Consulta pública de alíquota interna de ICMS em Goiás por NCM."""

import streamlit as st

from src.busca import consultar, texto
from src.dados import ErroConfiguracaoDados, ErroFonteDados, criar_repositorio
from src.formatacao import formatar_percentual


st.set_page_config(page_title="Alíquota interna de ICMS — Goiás", layout="centered")
st.title("Alíquota interna de ICMS — Goiás")

try:
    base = criar_repositorio(data_source="postgres", secrets=st.secrets).carregar_base()
except (ErroConfiguracaoDados, ErroFonteDados):
    base = None
    st.error("Consulta indisponível no momento. Tente novamente mais tarde.")

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
        elif resultado.situacao == "SEM_TRATAMENTO_CADASTRADO":
            st.info("Alíquota interna não encontrada na base para este NCM.")
        elif resultado.regra_priorizada is None:
            st.warning("Verificação fiscal necessária")
            st.write("O cadastro não permite determinar com segurança a alíquota interna e seu fundamento para a data consultada.")
        else:
            regra = resultado.regra_priorizada
            st.subheader("Alíquota interna cadastrada — Goiás")
            st.write(formatar_percentual(regra.dados["aliquota_icms"]))
            st.subheader("Fundamento legal cadastrado")
            fundamento = regra.legislacao
            for chave, rotulo in (
                ("norma", "Norma"), ("numero", "Número"), ("ano", "Ano"),
                ("anexo", "Anexo"), ("artigo", "Artigo"), ("paragrafo", "Parágrafo"),
                ("inciso", "Inciso"), ("alinea", "Alínea"), ("item", "Item"),
                ("texto_relevante", "Trecho cadastrado"),
            ):
                valor = texto(fundamento.get(chave))
                if valor:
                    st.write(f"{rotulo}: {valor}")
            st.write(f"Fonte cadastrada: {texto(fundamento['url_fonte'])}")

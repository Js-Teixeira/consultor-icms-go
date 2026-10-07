"""Painel administrativo separado da consulta fiscal."""

import os

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository
from src.estilos import CSS_DIROMA
from updater.persistencia import RepositorioMonitoramento
from updater.repositorio_extracao import RepositorioExtracao
from updater.repositorio_consolidacao import RepositorioConsolidacao

st.set_page_config(page_title="Monitoramento legislativo — Goiás", layout="centered")
st.markdown(CSS_DIROMA, unsafe_allow_html=True)
st.title("Monitoramento legislativo — Goiás")

habilitado = os.getenv("ADMIN_TOOLS", "").strip().lower() == "true"
if not habilitado:
    st.info("Ferramentas administrativas desativadas. Configure ADMIN_TOOLS=true para desenvolvimento.")
    st.stop()

try:
    repositorio_dados = criar_repositorio(data_source="postgres", secrets=st.secrets)
    assert isinstance(repositorio_dados, PostgresRepository)
    painel = RepositorioMonitoramento(repositorio_dados.engine).painel()
    pendentes = RepositorioExtracao(repositorio_dados.engine).pendentes()
    consolidadas = RepositorioConsolidacao(repositorio_dados.engine).painel()
except (ErroConfiguracaoDados, SQLAlchemyError, OSError):
    st.error("Não foi possível acessar a base de monitoramento PostgreSQL.")
    st.stop()

ultima = painel["ultima_verificacao"]
st.write(f"**Última verificação legislativa:** {ultima.strftime('%d/%m/%Y %H:%M') if ultima else 'Nenhuma'}")
st.metric("Atos monitorados", painel["atos_monitorados"])
st.metric("Novos atos pendentes", painel["novos_pendentes"])
st.metric("Erros de coleta", painel["erros_coleta"])
st.subheader("Regras extraídas pendentes")
if pendentes:
    st.dataframe([{
        "Ato": f"{r['tipo_ato']} {r['numero']}/{r['ano']}",
        "Tipo": r["tipo_regra"],
        "NCM": r["ncm_chave"],
        "Descrição": r["descricao_legal"],
        "Alíquota": r["aliquota_icms"],
        "Redução BC": r["percentual_reducao_bc"],
        "Carga efetiva": r["carga_efetiva"],
        "Crédito outorgado": r["credito_outorgado_percentual"],
        "Dispositivo": ", ".join(f"{nome} {r[nome]}" for nome in ("anexo", "artigo", "inciso") if r[nome]),
        "Confiança": r["confianca"],
        "Status": r["status_revisao"],
    } for r in pendentes], hide_index=True, width="stretch")
else:
    st.info("Nenhuma regra extraída pendente de revisão.")

st.subheader("Regras consolidadas")
if consolidadas:
    st.dataframe([{
        "Status": r["status_regra"],
        "Validação": r["status_validacao"],
        "NCM": r["ncm_chave"],
        "Tipo": r["tipo_regra"],
        "Benefício": r["tipo_beneficio"],
        "Alíquota": r["aliquota_icms"],
        "Redução BC": r["percentual_reducao_bc"],
        "Carga efetiva": r["carga_efetiva"],
        "Crédito outorgado": r["credito_outorgado_percentual"],
        "Dispositivo": ", ".join(f"{nome} {r[nome]}" for nome in (
            "anexo", "artigo", "paragrafo", "inciso", "alinea", "item") if r[nome]),
        "Ato atual": f"{r['tipo_ato']} {r['numero']}/{r['ano']}",
        "Regra anterior": r["regra_anterior_id"],
        "Confiança": r["confianca"],
        "Alertas": r["alertas"],
    } for r in consolidadas], hide_index=True, width="stretch")
else:
    st.info("Nenhuma regra consolidada cadastrada.")

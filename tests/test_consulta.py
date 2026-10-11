"""Dados sintéticos compartilhados e validações básicas da consulta."""

import pandas as pd
import pytest

from src.carregamento import ErroBase, carregar_base
from src.normalizacao import normalizar_ncm


def beneficio(id_beneficio="B1", chave="12345678", tipo="EXATO", **campos):
    return {
        "id_beneficio": id_beneficio, "chave_ncm": chave,
        "tipo_correspondencia": tipo, "descricao_regra": "Produto sintético",
        "palavras_chave": "produto", "tipo_beneficio": "TIPO_SINTETICO",
        "carga_efetiva": "CARGA_SINTETICA", "id_legislacao": "L1",
        "vigencia_inicio": None, "vigencia_fim": None, "ativo": "SIM", **campos,
    }


def test_ncm_com_pontos_e_zero_inicial():
    assert normalizar_ncm("0123.45.67") == "01234567"


def test_planilha_indisponivel(tmp_path):
    with pytest.raises(ErroBase, match="Planilha indisponível"):
        carregar_base(tmp_path / "inexistente.xlsx")


def test_colunas_obrigatorias_ausentes(tmp_path):
    caminho = tmp_path / "incompleta.xlsx"
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for aba, tabela in {
            "NCM": pd.DataFrame(columns=["ncm", "descricao_oficial", "ativo"]),
            "Aliquotas": pd.DataFrame(columns=["id_regra"]),
            "Beneficios": pd.DataFrame(columns=["id_beneficio"]),
            "Legislacao": pd.DataFrame(columns=["id_legislacao"]),
        }.items():
            tabela.to_excel(writer, sheet_name=aba, index=False)
    with pytest.raises(ErroBase, match="Colunas obrigatórias ausentes em Aliquotas"):
        carregar_base(caminho)

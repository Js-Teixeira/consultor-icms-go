"""Validação estrutural da planilha e formatação da alíquota."""

import pandas as pd
import pytest

from src.carregamento import COLUNAS_OBRIGATORIAS, ErroBase, carregar_base
from src.formatacao import formatar_percentual
from tests.test_consulta import beneficio


def _planilha_teste(caminho, *, ncm_ativo=True, aliquotas=None, beneficios=None):
    tabelas = {nome: pd.DataFrame(columns=sorted(colunas)) for nome, colunas in COLUNAS_OBRIGATORIAS.items()}
    tabelas["NCM"] = pd.DataFrame([{"ncm": "12345678", "descricao_oficial": "Produto sintético", "ativo": "SIM"}])
    if not ncm_ativo:
        tabelas["NCM"] = tabelas["NCM"].drop(columns="ativo")
    if aliquotas is not None:
        tabelas["Aliquotas"] = pd.DataFrame(aliquotas)
    if beneficios is not None:
        tabelas["Beneficios"] = pd.DataFrame(beneficios)
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for nome, tabela in tabelas.items():
            tabela.to_excel(writer, sheet_name=nome, index=False)


def test_ativo_obrigatorio_na_aba_ncm(tmp_path):
    caminho = tmp_path / "sem_ativo.xlsx"
    _planilha_teste(caminho, ncm_ativo=False)
    with pytest.raises(ErroBase, match="NCM: ativo"):
        carregar_base(caminho)


@pytest.mark.parametrize(("valor", "esperado"), [
    (19, "19,00%"), (7, "7,00%"), (9.8, "9,80%"),
    (0.1, "0,10%"), ("9,8", "9,80%"),
])
def test_percentual_em_pontos_percentuais(valor, esperado):
    assert formatar_percentual(valor) == esperado


@pytest.mark.parametrize(("campo", "valor"), [
    ("exige_descricao", "TALVEZ"), ("aplicacao", "SOMAR"),
    ("escopo_operacao", "EXTERNA"),
])
def test_loader_rejeita_opcoes_invalidas(tmp_path, campo, valor):
    caminho = tmp_path / "opcao_invalida.xlsx"
    linha = beneficio(exige_descricao="SIM", aplicacao="UNICO", grupo_beneficio="")
    linha[campo] = valor
    _planilha_teste(caminho, beneficios=[linha])
    with pytest.raises(ErroBase, match=campo):
        carregar_base(caminho)

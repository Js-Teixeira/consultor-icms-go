"""Formatação e validações SQL, sem dependência de planilhas."""

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from scripts.validacao_carga_sql import ErroImportacao, _normalizar_linha
from scripts.verificar_prontidao_producao import verificar_schema
from src.dados.schema import TABELAS
from src.formatacao import formatar_percentual
from tests.test_consulta import beneficio


def test_schema_sql_aponta_coluna_ativo_ausente():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conexao:
        conexao.execute(text("CREATE TABLE ncm (ncm TEXT PRIMARY KEY, descricao_oficial TEXT)"))
    resultado = verificar_schema(engine)
    assert not resultado["schema"]
    assert "ativo" in resultado["colunas_faltantes"]["ncm"]


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
def test_carga_sql_rejeita_opcoes_invalidas(campo, valor):
    linha = beneficio(exige_descricao="SIM", aplicacao="UNICO", grupo_beneficio="", carga_efetiva=None)
    linha[campo] = valor
    with pytest.raises(ErroImportacao, match=campo):
        _normalizar_linha("Beneficios", TABELAS["Beneficios"], pd.Series(linha), 2)

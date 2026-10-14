"""Regressões da referência modal e de hipóteses específicas condicionais.

Todos os registros de entrada são sintéticos; nenhuma conexão real é usada.
"""

from datetime import date
from decimal import Decimal

import pandas as pd

from src.busca import consultar
from tests.test_consulta_simples import base_sintetica


def test_sem_regra_apresenta_19_apenas_como_referencia():
    resultado = consultar(base_sintetica(regras=[]), "12345678", date(2026, 10, 14))
    assert resultado.situacao == "SEM_TRATAMENTO_CADASTRADO"
    assert resultado.aliquota_geral_referencia == Decimal("19")
    assert resultado.regra_priorizada is None


def test_regra_especifica_preservada_sem_19_como_referencia():
    resultado = consultar(base_sintetica(), "12345678", date(2026, 9, 30))
    assert resultado.situacao == "ENCONTRADO"
    assert resultado.aliquota_geral_referencia is None


def test_regra_insegura_nao_recebe_fallback_19():
    base = base_sintetica()
    base.aliquotas.loc[0, "id_legislacao"] = "SEM_FUNDAMENTO"
    resultado = consultar(base, "12345678", date(2026, 9, 30))
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.aliquota_geral_referencia is None


def test_nao_atribui_19_antes_da_vigencia_modal():
    resultado = consultar(base_sintetica(regras=[]), "12345678", date(2024, 3, 31))
    assert resultado.aliquota_geral_referencia is None


def test_04029900_possui_hipotese_condicionada_sem_confirmar_12():
    base = base_sintetica(regras=[])
    base.ncm = pd.DataFrame([
        {"ncm": "04029900", "descricao_oficial": "Produto sintético", "ativo": "SIM"}
    ])
    resultado = consultar(base, "04029900", date(2026, 10, 14))
    assert resultado.situacao == "SEM_TRATAMENTO_CADASTRADO"
    assert resultado.aliquota_geral_referencia == Decimal("19")
    assert resultado.regra_priorizada is None
    assert len(resultado.hipoteses_especiais) == 1
    hipotese = resultado.hipoteses_especiais[0]
    assert hipotese.aliquota == Decimal("12")
    assert "art. 27" in hipotese.fundamento
    assert "condensado" in hipotese.condicao


def test_ncm_sem_hipotese_nao_recebe_regra_especial_inventada():
    resultado = consultar(base_sintetica(regras=[]), "12345678", date(2026, 10, 14))
    assert resultado.hipoteses_especiais == []

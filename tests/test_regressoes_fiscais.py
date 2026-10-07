"""Contratos estáticos dos casos já revisados em base/validacao_ncm.csv."""

import copy
import json
from decimal import Decimal

import pytest
import pandas as pd

from scripts.importar_validacao_ncm import CAMINHO_VALIDACAO, ler_validacao
from src.modelos import BaseTributaria
from src.regressoes_fiscais import SNAPSHOT, conferir_casos as _conferir_casos, conferir_snapshot_base


def test_casos_reais_validados_nao_mudaram_silenciosamente():
    casos = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["casos"]
    assert len(casos) == 14
    assert sum(bool(caso["beneficios"]) for caso in casos) == 4
    preparados, rascunhos = ler_validacao(CAMINHO_VALIDACAO)
    assert rascunhos == 0
    _conferir_casos(preparados, casos)


@pytest.mark.parametrize("mudanca", ["aliquota", "fundamento", "beneficio"])
def test_snapshot_reprova_mudanca_fiscal_silenciosa(mudanca):
    casos = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["casos"]
    preparados, _ = ler_validacao(CAMINHO_VALIDACAO)
    alterados = copy.deepcopy(preparados)
    if mudanca == "aliquota":
        alterados["Aliquotas"][0]["aliquota_icms"] = Decimal("19")
    elif mudanca == "fundamento":
        alterados["Aliquotas"][0]["id_legislacao"] = "OUTRO_FUNDAMENTO"
    else:
        alterados["Beneficios"].pop(0)
    with pytest.raises(AssertionError):
        _conferir_casos(alterados, casos)


def _base_congelada():
    preparados, _ = ler_validacao(CAMINHO_VALIDACAO)
    return BaseTributaria(
        ncm=pd.DataFrame(preparados["NCM"]), aliquotas=pd.DataFrame(preparados["Aliquotas"]),
        beneficios=pd.DataFrame(preparados["Beneficios"]), legislacao=pd.DataFrame(preparados["Legislacao"]),
    )


def test_regressao_banco_usa_campos_fiscais_sem_exigir_descricao_local():
    base = _base_congelada()
    base.ncm.loc[0, "descricao_oficial"] = "Descrição oficial sincronizada"
    assert conferir_snapshot_base(base) == (14, 4)


@pytest.mark.parametrize("mudanca", ["aliquota", "regra_removida", "beneficio_removido",
                                    "fundamento", "carga", "ncm_inativo"])
def test_regressao_banco_reprova_divergencia_fiscal(mudanca):
    base = _base_congelada()
    if mudanca == "aliquota":
        base.aliquotas.loc[0, "aliquota_icms"] = Decimal("19")
    elif mudanca == "regra_removida":
        base.aliquotas = base.aliquotas.iloc[1:]
    elif mudanca == "beneficio_removido":
        base.beneficios = base.beneficios.iloc[1:]
    elif mudanca == "fundamento":
        base.aliquotas.loc[0, "id_legislacao"] = "OUTRO_FUNDAMENTO"
    elif mudanca == "carga":
        base.beneficios.loc[0, "carga_efetiva"] = Decimal("8")
    else:
        base.ncm.loc[0, "ativo"] = "NAO"
    with pytest.raises(AssertionError, match="NCM"):
        conferir_snapshot_base(base)

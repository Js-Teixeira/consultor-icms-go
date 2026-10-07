"""Compara casos fiscais revisados com o snapshot fixo."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .modelos import BaseTributaria

SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "regressoes_fiscais_go.json"


def _valor(valor: Any) -> Any:
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor.normalize())
    return valor


def _campos(registro: dict, esperado: dict) -> dict:
    return {campo: _valor(registro.get(campo)) for campo in esperado}


def conferir_casos(preparados: dict, casos: list[dict], *, comparar_descricao: bool = True) -> None:
    ncms = {r["ncm"]: r for r in preparados["NCM"]}
    aliquotas = preparados["Aliquotas"]
    beneficios = preparados["Beneficios"]
    for caso in casos:
        codigo = caso["ncm"]
        cadastrado = ncms.get(codigo)
        if cadastrado is None or cadastrado.get("ativo") != "SIM":
            raise AssertionError(f"NCM {codigo}: ausente ou inativo")
        if comparar_descricao and cadastrado["descricao_oficial"] != caso["descricao_oficial"]:
            raise AssertionError(f"NCM {codigo}: descrição divergente")
        regras = [r for r in aliquotas if r["chave_ncm"] == codigo and r["tipo_correspondencia"] == "EXATO"
                  and r.get("ativo") == "SIM"]
        if len(regras) != 1 or _campos(regras[0], caso["aliquota"]) != caso["aliquota"]:
            raise AssertionError(f"NCM {codigo}: alíquota ou fundamento divergente")
        encontrados = {r["id_beneficio"]: r for r in beneficios
                       if r["chave_ncm"] == codigo and r["tipo_correspondencia"] == "EXATO"
                       and r.get("ativo") == "SIM"}
        if set(encontrados) != {r["id_beneficio"] for r in caso["beneficios"]}:
            raise AssertionError(f"NCM {codigo}: benefícios divergentes")
        for esperado in caso["beneficios"]:
            if _campos(encontrados[esperado["id_beneficio"]], esperado) != esperado:
                raise AssertionError(f"NCM {codigo}: benefício ou fundamento divergente")


def conferir_snapshot(preparados: dict, caminho: Path = SNAPSHOT) -> tuple[int, int]:
    casos = json.loads(caminho.read_text(encoding="utf-8"))["casos"]
    conferir_casos(preparados, casos)
    return len(casos), sum(bool(caso["beneficios"]) for caso in casos)


def conferir_snapshot_base(base: BaseTributaria, caminho: Path = SNAPSHOT) -> tuple[int, int]:
    """Confere casos congelados nos dados fiscais carregados."""

    preparados = {
        "NCM": base.ncm.to_dict("records"),
        "Aliquotas": base.aliquotas.to_dict("records"),
        "Beneficios": base.beneficios.to_dict("records"),
    }
    casos = json.loads(caminho.read_text(encoding="utf-8"))["casos"]
    conferir_casos(preparados, casos, comparar_descricao=False)
    return len(casos), sum(bool(caso["beneficios"]) for caso in casos)

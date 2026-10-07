"""Validação explícita dos vínculos fiscais curados; sem inferência por NCM."""

from __future__ import annotations

import json
from typing import Any

from .busca import texto


def ids_informados(registro: dict[str, Any]) -> bool:
    return bool(texto(registro.get("regra_consolidada_id")) or texto(registro.get("evidencia_ncm_id")))


def origens_consolidacao(consolidada: dict[str, Any]) -> set[str]:
    """IDs de origens declarados pelo consolidador, sem buscar por conteúdo fiscal."""

    principal = texto(consolidada.get("regra_origem_id"))
    origens = {principal} if principal else set()
    equivalentes = consolidada.get("origens_equivalentes")
    if equivalentes:
        try:
            valores = json.loads(equivalentes) if isinstance(equivalentes, str) else equivalentes
            if not isinstance(valores, list) or any(not isinstance(valor, int) or valor <= 0 for valor in valores):
                raise ValueError("Lista de origens equivalentes inválida.")
        except (TypeError, ValueError) as exc:
            raise ValueError("Lista de origens equivalentes inválida.") from exc
        origens.update(str(valor) for valor in valores)
    return origens


def problemas_vinculo(
    registro: dict[str, Any],
    consolidadas: dict[str, dict[str, Any]],
    extraidas: dict[str, dict[str, Any]],
    evidencias: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    """Devolve falhas comprovadas por IDs explícitos, sem procurar associação provável."""

    problemas: list[tuple[str, str]] = []
    consolidada_id = texto(registro.get("regra_consolidada_id"))
    evidencia_id = texto(registro.get("evidencia_ncm_id"))
    consolidada = consolidadas.get(consolidada_id) if consolidada_id else None
    evidencia = evidencias.get(evidencia_id) if evidencia_id else None
    if consolidada_id and consolidada is None:
        problemas.append(("RASTREABILIDADE_CONSOLIDACAO_INEXISTENTE", "Regra consolidada indicada não existe."))
    if evidencia_id and evidencia is None:
        problemas.append(("RASTREABILIDADE_EVIDENCIA_INEXISTENTE", "Evidência NCM indicada não existe."))
    if evidencia is not None:
        ncm_evidencia = texto(evidencia.get("valor_extraido")).replace(".", "")
        ncm_regra = texto(registro.get("chave_ncm")).replace(".", "")
        if texto(evidencia.get("tipo_evidencia")).upper() != "NCM" or ncm_evidencia != ncm_regra:
            problemas.append(("NCM_EVIDENCIA_INCOMPATIVEL", "Evidência indicada não comprova a chave NCM da regra."))
    if consolidada is not None:
        origem = texto(consolidada.get("regra_origem_id"))
        if not origem or origem not in extraidas:
            problemas.append(("RASTREABILIDADE_INCONSISTENTE", "Origem da consolidação não existe na extração."))
        try:
            origens = origens_consolidacao(consolidada)
        except ValueError:
            origens = {origem}
            problemas.append(("RASTREABILIDADE_INCONSISTENTE", "Origens equivalentes da consolidação inválidas."))
        if evidencia is not None and texto(evidencia.get("regra_extraida_id")) not in origens:
            problemas.append(("RASTREABILIDADE_INCONSISTENTE", "Consolidação e evidência não pertencem à mesma extração."))
        origem_registro = extraidas.get(origem)
        if (origem_registro is not None and texto(consolidada.get("ato_origem_id"))
                and texto(origem_registro.get("ato_id"))
                and texto(consolidada.get("ato_origem_id")) != texto(origem_registro.get("ato_id"))):
            problemas.append(("RASTREABILIDADE_INCONSISTENTE", "Ato da consolidação difere do ato da extração."))
    elif evidencia is not None and texto(evidencia.get("regra_extraida_id")) not in extraidas:
        problemas.append(("RASTREABILIDADE_INCONSISTENTE", "Extração da evidência não existe."))
    return problemas

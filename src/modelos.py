"""Estruturas da base fiscal e da consulta pública de alíquota."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

ESCOPOS_OPERACAO = frozenset({"INTERNA", "INTERESTADUAL", "AMBAS", "NAO_DEFINIDA"})
PREFIXOS_NCM_VALIDOS = frozenset({2, 4, 6})


@dataclass
class BaseTributaria:
    """Quatro tabelas fiscais preservadas para consulta, auditoria e manutenção."""

    ncm: pd.DataFrame
    aliquotas: pd.DataFrame
    beneficios: pd.DataFrame
    legislacao: pd.DataFrame


@dataclass
class Candidato:
    """Regra de alíquota correspondente, mesmo que dependa de verificação."""

    identificador: str
    chave_ncm: str
    tipo_correspondencia: str
    dados: dict[str, Any]
    vigencia: str
    exige_descricao: str = "NAO"
    legislacao: dict[str, Any] | None = None
    problema_fundamento: str | None = None

    @property
    def prioridade(self) -> tuple[int, int]:
        return (2, 8) if self.tipo_correspondencia == "EXATO" else (1, len(self.chave_ncm))


@dataclass
class ResultadoConsulta:
    """Decisão sobre a alíquota interna e candidatos mantidos para auditoria."""

    ncm_original: str
    ncm_normalizado: str
    data_referencia: date
    descricao_oficial: str = ""
    candidatos_aliquota: list[Candidato] = field(default_factory=list)
    regra_priorizada: Candidato | None = None
    possibilidades_aliquota: list[Candidato] = field(default_factory=list)
    situacao: str = "ENCONTRADO"

"""Estruturas compartilhadas pelo carregamento, busca e apresentação."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

NivelConfianca = Literal["ALTA", "MEDIA", "REVISAO_NECESSARIA"]
Operacao = Literal["INTERNA", "INTERESTADUAL"]
Aplicabilidade = Literal["APLICAVEL", "NAO_APLICAVEL", "CONDICIONAL", "REVISAO_NECESSARIA"]
ESCOPOS_OPERACAO = frozenset({"INTERNA", "INTERESTADUAL", "AMBAS", "NAO_DEFINIDA"})
PREFIXOS_NCM_VALIDOS = frozenset({2, 4, 6})


@dataclass
class BaseTributaria:
    """Tabelas consumidas pelo motor de consulta por NCM."""

    ncm: pd.DataFrame
    aliquotas: pd.DataFrame
    beneficios: pd.DataFrame
    legislacao: pd.DataFrame


@dataclass
class Candidato:
    """Regra que corresponde ao NCM, inclusive se for descartada pela vigência."""

    categoria: str
    identificador: str
    chave_ncm: str
    tipo_correspondencia: str
    dados: dict[str, Any]
    vigencia: str
    exige_descricao: str = "NAO"
    grupo_beneficio: str = ""
    aplicacao: str = ""
    palavras_chave_utilizadas: list[str] = field(default_factory=list)
    score_descricao_regra: float | None = None
    melhor_palavra_chave: str = ""
    score_melhor_palavra_chave: float | None = None
    score_descricao: float | None = None
    legislacao: dict[str, Any] | None = None
    problema_fundamento: str | None = None
    escopo_operacao: str = "NAO_DEFINIDA"
    cbenef: str = ""
    aplicabilidade: Aplicabilidade | None = None
    motivo_aplicabilidade: str = ""

    @property
    def prioridade(self) -> tuple[int, int]:
        return (2, 8) if self.tipo_correspondencia == "EXATO" else (1, len(self.chave_ncm))


@dataclass
class ResultadoConsulta:
    """Resultado e trilha de decisão para a interface e os casos de teste."""

    ncm_original: str
    ncm_normalizado: str
    data_referencia: date
    descricao_original: str = ""
    operacao_consultada: Operacao = "INTERNA"
    descricao_oficial: str = ""
    candidatos_aliquota: list[Candidato] = field(default_factory=list)
    candidatos_beneficio: list[Candidato] = field(default_factory=list)
    regra_priorizada: Candidato | None = None
    possibilidades_aliquota: list[Candidato] = field(default_factory=list)
    beneficios_priorizados: list[Candidato] = field(default_factory=list)
    beneficios_possiveis: list[Candidato] = field(default_factory=list)
    beneficios_encontrados: list[Candidato] = field(default_factory=list)
    beneficios_pendentes: bool = False
    nivel_confianca: NivelConfianca = "REVISAO_NECESSARIA"
    motivos_confianca: list[str] = field(default_factory=list)
    situacao: str = "ENCONTRADO"
    ambiguidades: list[str] = field(default_factory=list)

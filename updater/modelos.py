"""Valores transportados entre descoberta, leitura e persistência."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .foco_ncm import PrioridadeNcm

AVISO_DIVERGENCIA = "Divergência de datas encontrada entre a página de descoberta e o texto oficial."


@dataclass(frozen=True)
class AtoDescoberto:
    tipo_ato: str
    numero: str
    ano: int
    data_descoberta: date | None
    titulo: str
    ementa: str
    url_descoberta: str
    url_arquivo_economia: str | None
    data_publicacao: date | None = None
    fonte: str = "Secretaria da Economia de Goiás"


@dataclass(frozen=True)
class ConteudoOficial:
    url: str
    texto_original: str
    texto_limpo: str
    data_publicacao: date | None = None
    data_ato: date | None = None
    texto_consolidado: str = "NAO"


@dataclass(frozen=True)
class Classificacao:
    relevancia: str
    motivos: tuple[str, ...]


@dataclass(frozen=True)
class AtoColetado:
    descoberto: AtoDescoberto
    conteudo: ConteudoOficial | None
    classificacao: Classificacao
    erro: str | None = None
    divergencia_data: str = "NAO"
    advertencias: tuple[str, ...] = ()
    prioridade_ncm: PrioridadeNcm | None = None

    @property
    def status(self) -> str:
        if self.erro:
            return "ERRO"
        return "IGNORADO" if self.classificacao.relevancia == "BAIXA" else "NOVO"

"""Identificação de atos e limpeza de texto sem inferir conteúdo legal."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from bs4 import BeautifulSoup

from .modelos import AtoDescoberto

MESES = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4,
    "MAIO": 5, "JUNHO": 6, "JULHO": 7, "AGOSTO": 8,
    "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12,
}
PADRAO_ATO = re.compile(
    r"^(?P<tipo>DECRETO|LEI(?:\s+COMPLEMENTAR)?|INSTRUÇÃO\s+NORMATIVA(?:\s+ECONOMIA)?)"
    r"\s+N[º°o.]?\s*(?P<numero>\d[\d.]*(?:/\d{2,4})?(?:(?:\s*[-/]\s*|\s+)SIF)?)"
    r"\s*,?\s*DE\s+(?P<dia>\d{1,2})\s+DE\s+"
    r"(?P<mes>[A-ZÇÃÉÍÔ]+)\s+DE\s+(?P<ano>\d{4})",
    re.IGNORECASE,
)


def sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_numero_ato(numero: str, ano: int | None = None) -> str:
    """Remove pontuação de milhar e ano redundante, preservando sufixo do órgão."""

    valor = re.sub(r"\s+", "", numero.strip().upper())
    match = re.fullmatch(r"(\d[\d.]*)(?:/(\d{2,4}))?(?:[-/]?SIF)?", valor)
    if not match:
        return valor
    base = str(int(match.group(1).replace(".", "")))
    ano_numero = match.group(2)
    sufixo_ano = "" if not ano_numero or ano_numero == str(ano) else f"/{ano_numero}"
    return base + sufixo_ano + ("-SIF" if valor.endswith("SIF") else "")


def identificar_ato(titulo: str, ementa: str, url_descoberta: str, url_arquivo: str | None) -> AtoDescoberto | None:
    """Extrai somente identidade e data explicitamente presentes no título oficial."""

    titulo = " ".join(titulo.split())
    match = PADRAO_ATO.match(titulo)
    if not match:
        return None
    mes = MESES.get(sem_acentos(match.group("mes")).upper())
    if mes is None:
        return None
    ano = int(match.group("ano"))
    try:
        publicacao = date(ano, mes, int(match.group("dia")))
    except ValueError:
        return None
    return AtoDescoberto(
        tipo_ato=" ".join(match.group("tipo").upper().split()),
        numero=normalizar_numero_ato(match.group("numero"), ano),
        ano=ano,
        data_descoberta=publicacao,
        titulo=titulo,
        ementa=" ".join(ementa.split()),
        url_descoberta=url_descoberta,
        url_arquivo_economia=url_arquivo,
    )


def limpar_html(html: str) -> str:
    """Remove elementos de interface, preservando o texto e números do ato."""

    soup = BeautifulSoup(html, "html.parser")
    for elemento in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        elemento.decompose()
    linhas = [" ".join(linha.split()) for linha in soup.get_text("\n").splitlines()]
    return "\n".join(linha for linha in linhas if linha)


def limpar_texto(texto: str) -> str:
    """Normaliza espaços de texto convertido sem apagar dispositivos ou NCMs."""

    linhas = [" ".join(linha.split()) for linha in texto.replace("\ufeff", "").splitlines()]
    return "\n".join(linha for linha in linhas if linha)

"""Normalização de entradas sem alterar os textos originais exibidos."""

import re
import unicodedata


def normalizar_ncm(valor: object) -> str:
    """Remove caracteres não numéricos e exige exatamente oito dígitos."""

    digitos = re.sub(r"[^0-9]", "", str(valor or ""))
    if len(digitos) != 8:
        raise ValueError("NCM inválido: informe exatamente 8 dígitos.")
    return digitos


def formatar_ncm(ncm: str) -> str:
    """Formata um NCM previamente validado para exibição."""

    return f"{ncm[:4]}.{ncm[4:6]}.{ncm[6:]}"


def normalizar_texto(valor: object) -> str:
    """Retorna texto minúsculo, sem acentos e com espaços uniformes."""

    texto = unicodedata.normalize("NFKD", str(valor or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split())

"""Normalização de entradas sem alterar os textos originais exibidos."""

import re


def normalizar_ncm(valor: object) -> str:
    """Aceita oito dígitos, com ou sem a pontuação convencional."""

    informado = str(valor or "").strip()
    if not re.fullmatch(r"(?:[0-9]{8}|[0-9]{4}\.[0-9]{2}\.[0-9]{2})", informado):
        raise ValueError("NCM inválido: informe exatamente 8 dígitos.")
    return informado.replace(".", "")

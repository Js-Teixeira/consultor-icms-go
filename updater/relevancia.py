"""Triagem por termos, sem decisão jurídica automática."""

import re

from .modelos import Classificacao
from .normalizacao import sem_acentos

SINAIS = {
    "NCM": r"\bncm(?:/sh)?\b",
    "posição fiscal": r"\bposicao\s+\d{4}\b",
    "subposição fiscal": r"\bsubposicao\s+\d{4}(?:\.?\d{2})?\b",
    "classificação fiscal": r"\bclassificacao\s+fiscal\b",
    "mercadoria": r"\bmercadorias?\b",
    "produto": r"\bprodutos?\b",
    "Anexo IX": r"\banexo\s+ix\b",
    "Decreto nº 4.852": r"\bdecreto\s*(?:n[ºo.]\s*)?4\.?852\b",
    "benefício fiscal": r"\bbenefici[oa]\s+fiscal\b",
    "isenção": r"\bisencao\b",
    "redução de base": r"\breducao\s+(?:da?\s+)?base\b",
    "crédito outorgado": r"\bcredito\s+outorgado\b",
    "diferimento": r"\bdiferimento\b",
    "alíquota": r"\baliquota\b",
    "RCTE": r"\brcte\b",
    "ICMS": r"\bicms\b",
}
SINAIS_ESPECIFICOS = set(SINAIS) - {"ICMS", "RCTE"}
def classificar_relevancia(texto: str) -> Classificacao:
    """Exige combinação de sinais para ALTA e registra os termos encontrados."""

    normalizado = sem_acentos(texto).lower()
    encontrados = [nome for nome, padrao in SINAIS.items() if re.search(padrao, normalizado)]
    if len(encontrados) >= 2 and SINAIS_ESPECIFICOS.intersection(encontrados):
        nivel = "ALTA"
    elif encontrados:
        nivel = "MEDIA"
    else:
        nivel = "BAIXA"
    motivos = tuple(f'Contém "{termo}".' for termo in encontrados)
    return Classificacao(nivel, motivos or ("Nenhum termo tributário monitorado encontrado.",))

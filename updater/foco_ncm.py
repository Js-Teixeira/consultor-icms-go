"""Prioridade de descoberta por NCM, independente da elegibilidade fiscal."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extracao_fiscal import detectar_ncms
from .normalizacao import sem_acentos

NIVEIS = {"MUITO_ALTA": 4, "ALTA": 3, "MEDIA": 2, "BAIXA": 1, "SEM_INDICIO": 0}
TERMOS_NCM = re.compile(r"\b(?:ncm(?:\s*[/\-]\s*sh)?|nomenclatura comum do mercosul)\b")
TERMOS_CLASSIFICACAO = re.compile(r"\b(?:classificacao fiscal|posicao|subposicao)\b")
TERMOS_MERCADORIA = re.compile(r"\b(?:mercadorias?|produtos?)\b")
TERMOS_MATERIAIS = re.compile(
    r"\b(?:aliquota|isencao|isento|isenta|reducao(?:\s+(?:da|de))?\s+base|"
    r"carga tributaria|diferimento|substituicao tributaria|beneficio fiscal|"
    r"credito outorgado|nao incidencia|suspensao)\b"
)
TERMOS_PROCEDIMENTAIS = re.compile(
    r"\b(?:manifestacao do fisco|documentacao fiscal|documento fiscal|"
    r"obrigacao acessoria|procedimento|requerimento|cadastro)\b"
)


@dataclass(frozen=True)
class PrioridadeNcm:
    relevancia: str
    motivos: tuple[str, ...]
    ncms: tuple[str, ...]
    quantidade_ncms_texto: int
    possui_ncm_explicito: str
    possui_prefixo_ncm: str
    possui_termo_material_icms: str
    apenas_procedimental: bool


def classificar_foco_ncm(texto_oficial: str, texto_descoberta: str = "",
                        html_original: str | None = None) -> PrioridadeNcm:
    """Classifica indícios do texto oficial; ementa só auxilia a triagem textual."""

    deteccoes = detectar_ncms(texto_oficial, html_original) if texto_oficial else []
    texto = sem_acentos(" ".join((texto_descoberta, texto_oficial))).lower()
    tem_icms = bool(re.search(r"\bicms(?:-st)?\b", texto))
    contextos_ncm = [sem_acentos(texto_oficial[max(d.inicio_contexto, d.inicio - 300):
                                               min(d.fim_contexto, d.fim + 300)]).lower()
                    for d in deteccoes]
    contexto_material_ncm = any(
        re.search(r"\bicms(?:-st)?\b", contexto) and TERMOS_MATERIAIS.search(contexto)
        for contexto in contextos_ncm
    )
    exatos = any(d.tipo_correspondencia == "EXATO" for d in deteccoes)
    prefixos = any(d.tipo_correspondencia == "PREFIXO" for d in deteccoes)
    mencao_ncm = bool(TERMOS_NCM.search(texto))
    classificacao = bool(TERMOS_CLASSIFICACAO.search(texto))
    mercadoria = bool(TERMOS_MERCADORIA.search(texto))
    if exatos and contexto_material_ncm:
        nivel = "MUITO_ALTA"
    elif exatos and tem_icms:
        nivel = "ALTA"
    elif (prefixos or classificacao or mencao_ncm) and tem_icms:
        nivel = "MEDIA"
    elif deteccoes or mencao_ncm or classificacao or mercadoria:
        nivel = "BAIXA"
    else:
        nivel = "SEM_INDICIO"
    motivos: list[str] = []
    if exatos:
        motivos.append("Código NCM explícito no texto oficial.")
    if prefixos:
        motivos.append("Posição ou subposição NCM explícita no texto oficial.")
    if not deteccoes and (mencao_ncm or classificacao):
        motivos.append("Termo de classificação fiscal sem código confirmado no texto oficial.")
    if contexto_material_ncm:
        motivos.append("ICMS e termo material próximos ao NCM; efeito jurídico não avaliado.")
    elif tem_icms:
        motivos.append("Menção a ICMS encontrada.")
    if mercadoria and not deteccoes:
        motivos.append("Mercadoria ou produto citado sem código NCM confirmado.")
    if not motivos:
        motivos.append("Sem indício NCM no conteúdo coletado.")
    return PrioridadeNcm(
        nivel, tuple(motivos), tuple(dict.fromkeys(d.normalizado for d in deteccoes)),
        len(deteccoes), "SIM" if exatos else "NAO", "SIM" if prefixos else "NAO",
        "SIM" if contexto_material_ncm else "NAO",
        bool(deteccoes and not contexto_material_ncm and all(
            TERMOS_PROCEDIMENTAIS.search(contexto) for contexto in contextos_ncm)),
    )

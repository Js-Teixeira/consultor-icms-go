"""Cobertura lógica do cadastro fiscal por NCM, sem criar linhas por prefixo."""

from __future__ import annotations

from .busca import texto
from .modelos import BaseTributaria, PREFIXOS_NCM_VALIDOS


def resumir_cobertura(base: BaseTributaria) -> dict[str, int]:
    ncms = {texto(r.get("ncm")) for r in base.ncm.to_dict("records")
            if texto(r.get("ativo")).upper() == "SIM"}
    grupos = {}
    exatas = prefixos = 0
    for nome in ("aliquotas", "beneficios"):
        df = getattr(base, nome)
        regras = [r for r in df.to_dict("records") if texto(r.get("ativo")).upper() == "SIM"]
        grupos[nome] = regras
        exatas += sum(texto(r.get("tipo_correspondencia")).upper() == "EXATO"
                      and len(texto(r.get("chave_ncm"))) == 8 for r in regras)
        prefixos += sum(texto(r.get("tipo_correspondencia")).upper() == "PREFIXO"
                        and len(texto(r.get("chave_ncm"))) in PREFIXOS_NCM_VALIDOS for r in regras)

    def cobertos(regras: list[dict]) -> set[str]:
        diretos = {texto(r.get("chave_ncm")) for r in regras
                   if texto(r.get("tipo_correspondencia")).upper() == "EXATO"
                   and len(texto(r.get("chave_ncm"))) == 8}
        chaves_prefixo = {texto(r.get("chave_ncm")) for r in regras
                         if texto(r.get("tipo_correspondencia")).upper() == "PREFIXO"
                         and len(texto(r.get("chave_ncm"))) in PREFIXOS_NCM_VALIDOS}
        return {n for n in ncms if n in diretos or any(n.startswith(p) for p in chaves_prefixo if p)}

    com_aliquota = cobertos(grupos["aliquotas"])
    com_beneficio = cobertos(grupos["beneficios"])
    return {
        "ncms_cadastrados": len(ncms),
        "ncms_com_aliquota": len(com_aliquota),
        "ncms_com_beneficio": len(com_beneficio),
        "ncms_sem_tratamento_cadastrado": len(ncms - com_aliquota - com_beneficio),
        "regras_exato": exatas,
        "regras_prefixo": prefixos,
    }

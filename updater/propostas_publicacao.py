"""Projeções de cadastro para revisão; sem conexão, autorização ou gravação."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.modelos import PREFIXOS_NCM_VALIDOS

from .consolidacao import CONSOLIDATOR_VERSION
from .fontes import ErroColeta, validar_url_oficial

DISPOSITIVOS = ("anexo", "artigo", "paragrafo", "inciso", "alinea", "item")
COLUNAS_LEGISLACAO = ("norma", "numero", "ano", *DISPOSITIVOS, "vigencia_inicio",
                     "vigencia_fim", "url_fonte", "texto_relevante", "ativo")
COLUNAS_ALIQUOTA = ("chave_ncm", "tipo_correspondencia", "descricao_regra", "aliquota_icms",
                   "id_legislacao", "vigencia_inicio", "vigencia_fim", "observacao", "exige_descricao",
                   "ativo")


@dataclass(frozen=True)
class RegistroPrevisto:
    proposta_id: int
    legislacao: dict[str, Any]
    aliquota: dict[str, Any]
    origem_sintetica: bool = False


@dataclass
class PlanoPublicacao:
    para_revisao: list[RegistroPrevisto] = field(default_factory=list)
    inalteradas: list[int] = field(default_factory=list)
    duplicadas_no_lote: list[int] = field(default_factory=list)
    bloqueadas: list[dict[str, Any]] = field(default_factory=list)


def planejar_revisao(proposta: Mapping[str, Any], acao: str, *, responsavel: str,
                    justificativa: str, data: date) -> dict[str, Any]:
    """Prepara uma decisão fiscal sem persistir ou modificar a proposta original."""

    if proposta.get("status_validacao") != "PENDENTE":
        raise ValueError("Só propostas pendentes podem ser revisadas.")
    if acao not in {"APROVAR", "REJEITAR"}:
        raise ValueError("Decisão fiscal inválida.")
    if not responsavel.strip() or not justificativa.strip() or not isinstance(data, date):
        raise ValueError("Responsável, justificativa e data são obrigatórios.")
    if acao == "APROVAR":
        candidata = dict(proposta, status_validacao="PENDENTE")
        motivos, _ = _verificar(candidata)
        if motivos:
            raise ValueError("Proposta não apta à aprovação: " + "; ".join(motivos))
    return {"proposta_id": proposta["id"],
            "status_anterior": "PENDENTE",
            "situacao_simulada": "APROVACAO_SIMULADA" if acao == "APROVAR" else "REJEICAO_SIMULADA",
            "responsavel": responsavel.strip(), "justificativa": justificativa.strip(),
            "data_decisao": data}


def _chave(prefixo: str, *partes: object) -> str:
    material = "\x1f".join(str(parte or "").strip().casefold() for parte in partes)
    return prefixo + sha256(material.encode("utf-8")).hexdigest()[:24]


def _evidencia_confere(evidencia: Mapping[str, Any], valor: str) -> bool:
    extraido = str(evidencia.get("valor_extraido") or "").strip()
    trecho = str(evidencia.get("texto_origem") or "").strip()
    return bool(valor and extraido and trecho and valor == extraido
                and _trecho_contem_valor(trecho, extraido))


def _trecho_contem_valor(trecho: str, valor: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(valor) + r"(?!\w)", trecho))


def _verificar(proposta: Mapping[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
    motivos: list[str] = []
    if proposta.get("status_validacao") == "DESCARTADA":
        motivos.append("Proposta rejeitada no cadastro; histórico preservado.")
    elif proposta.get("status_validacao") not in {"PENDENTE", "VALIDADA"}:
        motivos.append("Situação de revisão fiscal inválida.")
    if proposta.get("superada") is True or proposta.get("consolidador_versao") != CONSOLIDATOR_VERSION:
        motivos.append("Proposta substituída ou de versão antiga da consolidação.")
    if proposta.get("cadeia_origem_valida") is not True:
        motivos.append("Cadeia entre proposta, extração, versão e ato não comprovada.")
    if not isinstance(proposta.get("id"), int) or proposta["id"] <= 0:
        motivos.append("Identificador persistido da proposta ausente.")
    if proposta.get("status_regra") not in {"VIGENTE", "FUTURA"}:
        motivos.append("Situação da regra incompatível com cadastro ativo.")
    if proposta.get("tipo_regra") != "ALIQUOTA":
        motivos.append("Este plano só cobre a tabela Aliquotas; outro tratamento requer projeção própria.")
    if proposta.get("alertas"):
        motivos.append("Alertas da consolidação exigem revisão.")
    if proposta.get("fonte_atual") is not True:
        motivos.append("Proposta vinculada a versão superada ou com erro de coleta.")
    if proposta.get("fonte_verificada") is not True:
        motivos.append("Fonte oficial sem confirmação explícita de verificação.")

    ncm = proposta.get("ncm_chave") or ""
    tipo = proposta.get("tipo_correspondencia")
    tamanho = 8 if tipo == "EXATO" else PREFIXOS_NCM_VALIDOS if tipo == "PREFIXO" else ()
    if not (isinstance(ncm, str) and ncm.isascii() and ncm.isdigit()
            and len(ncm) in ({tamanho} if isinstance(tamanho, int) else tamanho)):
        motivos.append("NCM exato ou prefixo inválido.")
    evidencias_origem = [e for e in proposta.get("evidencias", ()) if
                        e.get("regra_extraida_id") == proposta.get("regra_origem_id")
                        and e.get("id") is not None and e.get("texto_origem")]
    evidencias = [e for e in evidencias_origem if
                  e.get("tipo_evidencia") == "NCM"
                  and isinstance(e.get("valor_extraido"), str)
                  and e["valor_extraido"].replace(".", "") == ncm
                  and _trecho_contem_valor(str(e.get("texto_origem") or ""), e["valor_extraido"])]
    if len(evidencias) != 1:
        motivos.append("Evidência NCM única e vinculada à extração é obrigatória.")

    try:
        percentual = Decimal(str(proposta.get("aliquota_icms")))
        if not percentual.is_finite() or not 0 <= percentual <= 100:
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        percentual = None
        motivos.append("Percentual ausente ou inválido.")
    if percentual is not None:
        valores_aliquota = []
        for evidencia in evidencias_origem:
            if evidencia.get("tipo_evidencia") != "ALIQUOTA":
                continue
            try:
                valor = str(evidencia.get("valor_extraido") or "")
                if not _trecho_contem_valor(str(evidencia.get("texto_origem") or ""), valor):
                    continue
                valores_aliquota.append(Decimal(valor.replace(",", ".")))
            except InvalidOperation:
                continue
        if percentual not in valores_aliquota:
            motivos.append("Evidência do percentual correspondente ausente.")
    if not str(proposta.get("descricao_legal") or "").strip():
        motivos.append("Descrição legal do tratamento ausente.")

    inicio, fim = proposta.get("vigencia_inicio"), proposta.get("vigencia_fim")
    if (not isinstance(inicio, date) or
            fim is not None and (not isinstance(fim, date) or fim < inicio)):
        motivos.append("Vigência ausente ou inconsistente.")
    else:
        referencia = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        if ((proposta.get("status_regra") == "VIGENTE" and
             (inicio > referencia or fim is not None and fim < referencia))
                or (proposta.get("status_regra") == "FUTURA" and inicio <= referencia)):
            motivos.append("Situação da regra não corresponde à vigência na data de referência.")
    for nome, valor in (("início", inicio), ("fim", fim)):
        if not isinstance(valor, date) or not any(
                e.get("tipo_evidencia") == "VIGENCIA" and _evidencia_confere(e, valor.isoformat())
                for e in evidencias_origem):
            motivos.append(f"Vigência de {nome} pendente de validação pela evidência.")
    condicoes = str(proposta.get("condicoes_texto") or "").strip()
    if condicoes and not any(e.get("tipo_evidencia") in {"CONDICAO", "EXCECAO"}
                             and _evidencia_confere(e, condicoes) for e in evidencias_origem):
        motivos.append("Condições pendentes de validação pela evidência da mesma extração.")

    tipo_ato = str(proposta.get("tipo_ato") or "").strip()
    numero = str(proposta.get("numero") or "").strip()
    ano = proposta.get("ano")
    identificacao = f"{tipo_ato} {numero}/{ano}".casefold()
    norma_base = " ".join(str(proposta.get("norma_base") or "").split()).casefold()
    if (not tipo_ato or not numero or not isinstance(ano, int) or ano < 1800
            or norma_base != identificacao):
        motivos.append("Fundamento não identifica sem ambiguidade o ato oficial da proposta.")
    dispositivos = [campo for campo in DISPOSITIVOS if proposta.get(campo)]
    if not dispositivos or any(not any(e.get("tipo_evidencia") == campo.upper()
                               and _evidencia_confere(e, str(proposta[campo]).strip())
                               for e in evidencias_origem) for campo in dispositivos):
        motivos.append("Dispositivo legal incompleto ou sem evidência correspondente.")
    fonte = proposta.get("url_texto_oficial") or ""
    try:
        validar_url_oficial(fonte)
    except (ErroColeta, ValueError):
        motivos.append("Fonte oficial verificável ausente.")
    if not proposta.get("regra_origem_id") or not proposta.get("ato_origem_id"):
        motivos.append("Vínculo com extração e ato oficial ausente.")
    return motivos, evidencias[0] if len(evidencias) == 1 else None


def _mesmo_cadastro(novo: Mapping[str, Any], anterior: Mapping[str, Any],
                    campos: Sequence[str]) -> bool:
    return all(novo.get(campo) == anterior.get(campo) for campo in campos)


def _periodos_sobrepostos(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    inicio_a, inicio_b = a.get("vigencia_inicio"), b.get("vigencia_inicio")
    fim_a, fim_b = a.get("vigencia_fim"), b.get("vigencia_fim")
    if (not isinstance(inicio_a, date) or not isinstance(inicio_b, date)
            or fim_a is not None and not isinstance(fim_a, date)
            or fim_b is not None and not isinstance(fim_b, date)):
        return True  # período desconhecido exige revisão
    return (fim_a is None or inicio_b <= fim_a) and (fim_b is None or inicio_a <= fim_b)


def _mesmo_fundamento(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return _mesmo_cadastro(a, b, ("norma", "numero", "ano", *DISPOSITIVOS))


def simular_publicacao(propostas: Sequence[Mapping[str, Any]], *,
                      legislacoes_existentes: Sequence[Mapping[str, Any]] = (),
                      aliquotas_existentes: Sequence[Mapping[str, Any]] = ()) -> PlanoPublicacao:
    """Projeta candidatos para revisão humana; não autoriza nem grava dados."""

    plano = PlanoPublicacao()
    leis = {r["id_legislacao"]: r for r in legislacoes_existentes}
    aliquotas = {r["id_regra"]: r for r in aliquotas_existentes}
    leis_planejadas: set[str] = set()
    regras_planejadas: set[str] = set()
    sucessores = {p.get(campo) for p in propostas for campo in
                  ("regra_anterior_id", "regra_substituida_id") if p.get(campo) is not None}
    ultimas = {}
    for proposta in propostas:
        chave = (proposta.get("ato_origem_id"), proposta.get("chave_consolidacao"))
        if chave[1] and isinstance(proposta.get("id"), int):
            ultimas[chave] = max(ultimas.get(chave, 0), proposta["id"])
    for proposta in propostas:
        chave = (proposta.get("ato_origem_id"), proposta.get("chave_consolidacao"))
        superada = (proposta.get("superada") is True or proposta.get("id") in sucessores
                    or chave in ultimas and proposta.get("id") != ultimas[chave])
        motivos, evidencia = _verificar(dict(proposta, superada=superada))
        identificador = proposta.get("id")
        if motivos:
            plano.bloqueadas.append({"proposta_id": identificador, "motivos": motivos})
            continue

        assert evidencia is not None
        chave_lei = _chave("AUTOLEG_", proposta["tipo_ato"], proposta["numero"],
                          proposta["ano"], *(proposta.get(c) for c in DISPOSITIVOS))
        chave_regra = _chave("AUTOALQ_", chave_lei, proposta["ncm_chave"],
                            proposta["tipo_correspondencia"], proposta["vigencia_inicio"])
        legislacao = {
            "id_legislacao": chave_lei, "norma": proposta["tipo_ato"],
            "numero": str(proposta["numero"]), "ano": str(proposta["ano"]),
            **{campo: proposta.get(campo) for campo in DISPOSITIVOS},
            "resumo": None, "texto_relevante": proposta["descricao_legal"],
            "url_fonte": proposta["url_texto_oficial"],
            "vigencia_inicio": proposta["vigencia_inicio"],
            "vigencia_fim": proposta.get("vigencia_fim"),
            "data_verificacao": None, "ativo": "NAO",
        }
        condicoes = str(proposta.get("condicoes_texto") or "").strip()
        aliquota = {
            "id_regra": chave_regra, "chave_ncm": proposta["ncm_chave"],
            "tipo_correspondencia": proposta["tipo_correspondencia"],
            "descricao_regra": proposta["descricao_legal"], "palavras_chave": None,
            "aliquota_icms": Decimal(str(proposta["aliquota_icms"])),
            "adicional_percentual": None, "id_legislacao": chave_lei,
            "regra_consolidada_id": identificador, "evidencia_ncm_id": evidencia["id"],
            "vigencia_inicio": proposta["vigencia_inicio"],
            "vigencia_fim": proposta.get("vigencia_fim"),
            "observacao": condicoes or None, "ativo": "NAO",
            "exige_descricao": "SIM" if condicoes or proposta["tipo_correspondencia"] == "PREFIXO" else "NAO",
        }
        fundamentos = [lei for lei in leis.values() if _mesmo_fundamento(legislacao, lei)]
        if any(not _mesmo_cadastro(legislacao, lei,
                                  tuple(c for c in COLUNAS_LEGISLACAO if c != "ativo"))
               for lei in fundamentos):
            plano.bloqueadas.append({"proposta_id": identificador,
                                    "motivos": ["Fundamento existente com conteúdo ou vigência divergente."]})
            continue
        if any(lei.get("ativo") != "SIM" and lei["id_legislacao"] not in leis_planejadas
               for lei in fundamentos):
            plano.bloqueadas.append({"proposta_id": identificador,
                                    "motivos": ["Fundamento anterior inativo exige análise histórica."]})
            continue
        equivalentes = [regra for regra in aliquotas.values()
                        if regra.get("chave_ncm") == aliquota["chave_ncm"]
                        and regra.get("tipo_correspondencia") == aliquota["tipo_correspondencia"]
                        and regra.get("id_legislacao") in {lei["id_legislacao"] for lei in fundamentos}
                        and _mesmo_cadastro(aliquota, regra, tuple(
                            c for c in COLUNAS_ALIQUOTA if c not in {"id_legislacao", "ativo"}))]
        if any(regra["id_regra"] in regras_planejadas for regra in equivalentes):
            plano.duplicadas_no_lote.append(identificador)
            continue
        if equivalentes and any(regra.get("ativo") != "SIM" for regra in equivalentes):
            plano.bloqueadas.append({"proposta_id": identificador,
                                    "motivos": ["Regra equivalente inativa exige análise histórica."]})
            continue
        if equivalentes:
            plano.inalteradas.append(identificador)
            continue
        if any(regra.get("chave_ncm") == aliquota["chave_ncm"]
               and regra.get("tipo_correspondencia") == aliquota["tipo_correspondencia"]
               and _periodos_sobrepostos(aliquota, regra) for regra in aliquotas.values()):
            plano.bloqueadas.append({"proposta_id": identificador,
                                    "motivos": ["Possível sobreposição com cadastro fiscal anterior."]})
            continue
        plano.para_revisao.append(RegistroPrevisto(identificador, legislacao, aliquota,
                                                  proposta.get("origem_sintetica") is True))
        leis[chave_lei] = legislacao
        aliquotas[chave_regra] = aliquota
        leis_planejadas.add(chave_lei)
        regras_planejadas.add(chave_regra)
    return plano

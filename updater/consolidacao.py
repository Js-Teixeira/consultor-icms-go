"""Planejamento determinístico e conservador de relações entre regras extraídas."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping

from .normalizacao import sem_acentos

CONSOLIDATOR_VERSION = "3.3.0"
DISPOSITIVOS = ("anexo", "artigo", "paragrafo", "inciso", "alinea", "item")
PERCENTUAIS = ("aliquota_icms", "percentual_reducao_bc", "carga_efetiva", "credito_outorgado_percentual")
CAMPOS_COPIADOS = (
    "tipo_regra", "ncm_chave", "tipo_correspondencia", "descricao_legal", *PERCENTUAIS,
    "tipo_beneficio", "anexo", "artigo", "paragrafo", "inciso", "alinea", "item",
    "condicoes_texto", "vigencia_inicio", "vigencia_fim",
    "grupo_regra_id", "complementos_json",
)


def _normalizar(valor: object) -> str:
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return str(valor.normalize())
    return " ".join(sem_acentos(str(valor)).lower().split())


def chave_consolidacao(regra: Mapping[str, Any]) -> str:
    """Identifica assunto por norma, dispositivo e NCM; artigo diferente não colide."""

    dispositivos = [_normalizar(regra.get(campo)) for campo in DISPOSITIVOS]
    chave = [
        _normalizar(regra.get("norma_base") or regra.get("norma_alterada")),
        *dispositivos,
        _normalizar(regra.get("ncm_chave")),
        _normalizar(regra.get("tipo_correspondencia")),
    ]
    if not any(dispositivos):
        # Sem dispositivo não é seguro associar atos distintos pelo NCM sozinho.
        chave.extend((_normalizar(regra.get("ato_origem_id") or regra.get("ato_id")),
                      _normalizar(regra.get("descricao_legal"))))
    return hashlib.sha256(json.dumps(chave, ensure_ascii=False).encode("utf-8")).hexdigest()


def _assunto_completo(regra: Mapping[str, Any]) -> bool:
    return bool(regra.get("norma_base") or regra.get("norma_alterada")) and any(regra.get(c) for c in DISPOSITIVOS)


def _conteudo_fiscal_explicito(regra: Mapping[str, Any]) -> bool:
    tipo = regra.get("tipo_regra")
    if tipo in {"ALTERACAO_LEGISLATIVA", "REVOGACAO", None}:
        return False
    exigido = {
        "ALIQUOTA": "aliquota_icms",
        "REDUCAO_BASE_CALCULO": "percentual_reducao_bc",
        "CREDITO_OUTORGADO": "credito_outorgado_percentual",
    }.get(tipo)
    return exigido is None or regra.get(exigido) is not None


def _equivalente(nova: Mapping[str, Any], anterior: Mapping[str, Any]) -> bool:
    if (nova.get("ato_origem_id") or nova.get("ato_id")) != anterior.get("ato_origem_id"):
        return False
    campos = ("tipo_regra", "ncm_chave", "tipo_correspondencia", "descricao_legal",
              "tipo_beneficio", *PERCENTUAIS, "vigencia_inicio", "vigencia_fim", "condicoes_texto")
    return all(_normalizar(nova.get(campo)) == _normalizar(anterior.get(campo)) for campo in campos)


def _diverge_conteudo(nova: Mapping[str, Any], anterior: Mapping[str, Any]) -> bool:
    campos = ("tipo_regra", "tipo_beneficio", *PERCENTUAIS, "descricao_legal", "condicoes_texto")
    return any(_normalizar(nova.get(campo)) != _normalizar(anterior.get(campo)) for campo in campos)


def _somente_vigencia_mudou(nova: Mapping[str, Any], anterior: Mapping[str, Any]) -> bool:
    """Não herda conteúdo anterior se o ato de extensão trouxer valor incompatível."""

    campos = ("tipo_beneficio", "descricao_legal", *PERCENTUAIS)
    return all(nova.get(campo) is None or
               _normalizar(nova.get(campo)) == _normalizar(anterior.get(campo))
               for campo in campos)


def _sobreposicao(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool | None:
    inicio_a, inicio_b = a.get("vigencia_inicio"), b.get("vigencia_inicio")
    if not isinstance(inicio_a, date) or not isinstance(inicio_b, date):
        return None
    fim_a, fim_b = a.get("vigencia_fim"), b.get("vigencia_fim")
    return (fim_a is None or inicio_b <= fim_a) and (fim_b is None or inicio_a <= fim_b)


def _status_temporal(regra: Mapping[str, Any], referencia: date) -> str:
    inicio, fim = regra.get("vigencia_inicio"), regra.get("vigencia_fim")
    if not isinstance(inicio, date) or fim is not None and (not isinstance(fim, date) or fim < inicio):
        return "INDETERMINADA"
    if inicio > referencia:
        return "FUTURA"
    return "VIGENTE" if fim is None or fim >= referencia else "INDETERMINADA"


@dataclass
class Consolidada:
    dados: dict[str, Any]
    id: int | None = None

    def valor(self, campo: str) -> Any:
        return self.dados.get(campo)


@dataclass(frozen=True)
class RelacaoPlanejada:
    origem_id: int | None  # None aponta para a nova regra da decisão.
    destino_id: int
    tipo: str
    motivo: str
    confianca: str


@dataclass
class Decisao:
    origem_id: int
    ato_id: int
    identificacao: str
    tipo_regra: str
    acao: str
    ncm: str | None
    nova: Consolidada | None
    motivo: str
    alteracoes: dict[int, dict[str, Any]] = field(default_factory=dict)
    relacoes: list[RelacaoPlanejada] = field(default_factory=list)
    duplicada_de: int | None = None
    anterior_id: int | None = None

    @property
    def status_previsto(self) -> str:
        return "DUPLICADA" if self.nova is None else self.nova.valor("status_regra")


def _nova_regra(fonte: Mapping[str, Any], versao: str) -> Consolidada:
    dados = {campo: fonte.get(campo) for campo in CAMPOS_COPIADOS}
    dados.update(
        chave_consolidacao=chave_consolidacao(fonte),
        norma_base=fonte.get("norma_alterada"),
        status_regra="INDETERMINADA", status_validacao="PENDENTE",
        confianca=fonte.get("confianca") or "BAIXA",
        regra_origem_id=fonte["id"], ato_origem_id=fonte["ato_id"],
        regra_substituida_id=None, regra_anterior_id=None,
        relacao_regra="INDETERMINADA", motivo_consolidacao="",
        alertas=fonte.get("alertas"), origens_equivalentes="[]",
        consolidador_versao=versao,
    )
    return Consolidada(dados)


def _relacao_ncm(nova: Consolidada, existentes: list[Consolidada], decisao: Decisao) -> None:
    ncm = nova.valor("ncm_chave")
    if not ncm or not nova.valor("norma_base"):
        return
    for anterior in existentes:
        outro = anterior.valor("ncm_chave")
        if not outro or outro == ncm or anterior.id is None:
            continue
        if not all(_normalizar(nova.valor(c)) == _normalizar(anterior.valor(c)) for c in ("norma_base", *DISPOSITIVOS)):
            continue
        if ncm.startswith(outro) and len(ncm) > len(outro):
            condicao = _normalizar(nova.valor("condicoes_texto"))
            excecao = re.search(r"\b(?:exceto|salvo|nao se aplica|vedad[oa]|excluem-se|nao alcanca)\b", condicao)
            tipo = "EXCECAO_DE" if excecao else "ESPECIFICA_DE"
            nova.dados["relacao_regra"] = "EXCECAO" if tipo == "EXCECAO_DE" else "ESPECIFICA"
            decisao.relacoes.append(RelacaoPlanejada(None, anterior.id, tipo,
                "NCM mais específico no mesmo dispositivo; não implica revogação.", "MEDIA"))
            if (anterior.valor("relacao_regra") == "INDETERMINADA"
                    and anterior.valor("status_validacao") == "PENDENTE"):
                decisao.alteracoes.setdefault(anterior.id, {})["relacao_regra"] = "GERAL"
        elif outro.startswith(ncm) and len(outro) > len(ncm):
            nova.dados["relacao_regra"] = "GERAL"
            decisao.relacoes.append(RelacaoPlanejada(anterior.id, 0, "ESPECIFICA_DE",
                "NCM mais específico no mesmo dispositivo; não implica revogação.", "MEDIA"))


def planejar_regra(fonte: Mapping[str, Any], existentes: list[Consolidada],
                   referencia: date, versao: str = CONSOLIDATOR_VERSION) -> Decisao:
    """Projeta uma regra e relações, sem alterar banco ou inferir vigência."""

    ato = f"{fonte['tipo_ato']} {fonte['numero']}/{fonte['ano']}"
    nova = _nova_regra(fonte, versao)
    decisao = Decisao(fonte["id"], fonte["ato_id"], ato, fonte["tipo_regra"],
                      fonte["acao_legislativa"], fonte.get("ncm_chave"), nova, "")
    for anterior in existentes:
        origens = json.loads(anterior.valor("origens_equivalentes") or "[]")
        if fonte["id"] == anterior.valor("regra_origem_id") or fonte["id"] in origens:
            decisao.nova = None
            decisao.duplicada_de = anterior.id
            decisao.motivo = "Regra extraída já consolidada nesta versão do consolidador."
            return decisao

    mesma_chave = [r for r in existentes if r.valor("chave_consolidacao") == nova.valor("chave_consolidacao")]
    for anterior in mesma_chave:
        if _equivalente(nova.dados, anterior.dados):
            decisao.nova = None
            decisao.duplicada_de = anterior.id
            decisao.motivo = "Extração equivalente do mesmo ato e dispositivo; origem adicional vinculada."
            return decisao

    acao = fonte["acao_legislativa"]
    apta = (fonte.get("confianca") == "ALTA" and not fonte.get("alertas")
            and (acao in {"PRORROGA", "RENOVA"} or _conteudo_fiscal_explicito(nova.dados))
            and bool(nova.valor("ncm_chave")) and _assunto_completo(nova.dados))
    base_status = _status_temporal(nova.dados, referencia)
    ativas = [r for r in mesma_chave if r.valor("status_regra") not in {"SUBSTITUIDA", "REVOGADA"}]
    candidatas = [r for r in ativas if r.valor("status_validacao") == "PENDENTE"]

    if acao == "REVOGA":
        # Revogação sem NCM só alcança automaticamente dispositivo único e exato.
        alvos = [r for r in existentes if r.valor("norma_base") == nova.valor("norma_base")
                 and all(r.valor(c) == nova.valor(c) for c in DISPOSITIVOS)
                 and (not nova.valor("ncm_chave") or r.valor("ncm_chave") == nova.valor("ncm_chave"))
                 and r.valor("tipo_regra") != "REVOGACAO"
                 and r.valor("status_regra") not in {"REVOGADA", "SUBSTITUIDA"}]
        if (fonte.get("tipo_regra") == "REVOGACAO"
                and fonte.get("confianca") in {"ALTA", "MEDIA"}
                and _assunto_completo(nova.dados) and len(alvos) == 1
                and alvos[0].valor("status_validacao") == "PENDENTE"
                and base_status == "VIGENTE" and not fonte.get("alertas")):
            alvo = alvos[0]
            decisao.anterior_id = alvo.id
            decisao.alteracoes[alvo.id] = {"status_regra": "REVOGADA"}
            decisao.relacoes.append(RelacaoPlanejada(None, alvo.id, "REVOGA",
                "Revogação explícita do dispositivo único com início de vigência identificado.", "ALTA"))
            decisao.motivo = "Revogação vinculada; registro anterior preservado."
        else:
            decisao.motivo = "Revogação sem alvo único ou início de vigência seguro; revisão necessária."
        nova.dados["status_regra"] = "INDETERMINADA"
    elif acao in {"ALTERA", "SUBSTITUI"}:
        if (apta and base_status in {"VIGENTE", "FUTURA"} and len(candidatas) == 1
                and len(ativas) == 1 and candidatas[0].valor("status_regra") in {"VIGENTE", "FUTURA"}
                and (not candidatas[0].valor("vigencia_inicio")
                     or nova.valor("vigencia_inicio") > candidatas[0].valor("vigencia_inicio"))):
            anterior = candidatas[0]
            decisao.anterior_id = anterior.id
            decisao.alteracoes[anterior.id] = {"status_regra": "SUBSTITUIDA"}
            decisao.relacoes.append(RelacaoPlanejada(None, anterior.id, acao,
                "Ação explícita, mesmo dispositivo e NCM, alvo único e início posterior.", "ALTA"))
            nova.dados["regra_anterior_id"] = anterior.id
            nova.dados["regra_substituida_id"] = anterior.id
            nova.dados["status_regra"] = base_status
            if anterior.valor("vigencia_fim") is None or anterior.valor("vigencia_fim") >= nova.valor("vigencia_inicio"):
                nova.dados["alertas"] = "Vigências podem se sobrepor; fim anterior preservado."
            decisao.motivo = "Nova versão consolidada; anterior marcada SUBSTITUIDA sem alterar suas datas."
        else:
            decisao.motivo = "Alteração ou substituição sem alvo único, sequência temporal ou evidência suficiente."
    elif acao in {"PRORROGA", "RENOVA"}:
        if (apta and len(candidatas) == 1 and len(ativas) == 1
                and _somente_vigencia_mudou(nova.dados, candidatas[0].dados)
                and isinstance(fonte.get("vigencia_fim"), date)
                and isinstance(candidatas[0].valor("vigencia_fim"), date)
                and fonte["vigencia_fim"] > candidatas[0].valor("vigencia_fim")
                and (acao == "PRORROGA" or isinstance(fonte.get("vigencia_inicio"), date))):
            anterior = candidatas[0]
            continuidade = (acao == "PRORROGA" or
                            fonte["vigencia_inicio"] == anterior.valor("vigencia_fim") + timedelta(days=1))
            if continuidade:
                for campo in CAMPOS_COPIADOS:
                    if campo not in {"vigencia_inicio", "vigencia_fim"}:
                        nova.dados[campo] = anterior.valor(campo)
                nova.dados["vigencia_inicio"] = (fonte.get("vigencia_inicio") if acao == "RENOVA"
                                                  else anterior.valor("vigencia_inicio"))
                nova.dados["vigencia_fim"] = fonte["vigencia_fim"]
                nova.dados["regra_anterior_id"] = anterior.id
                nova.dados["regra_substituida_id"] = anterior.id
                nova.dados["status_regra"] = _status_temporal(nova.dados, referencia)
                decisao.anterior_id = anterior.id
                decisao.alteracoes[anterior.id] = {"status_regra": "SUBSTITUIDA"}
                decisao.relacoes.append(RelacaoPlanejada(None, anterior.id, acao,
                    "Novo limite de vigência explícito; conteúdo fiscal preservado da versão anterior.", "ALTA"))
                decisao.motivo = "Continuidade de vigência explícita; criada versão sem apagar histórico."
            else:
                decisao.motivo = "Renovação com lacuna de vigência; continuidade não presumida."
        else:
            decisao.motivo = "Prorrogação ou renovação sem alvo único e novo limite explícito."
    elif acao == "INCLUI":
        if apta and base_status in {"VIGENTE", "FUTURA"} and not ativas:
            nova.dados["status_regra"] = base_status
            decisao.motivo = "Inclusão explícita com dispositivo, NCM e vigência identificados."
        else:
            decisao.motivo = "Inclusão potencial sem identidade, vigência ou unicidade suficientes."
    else:
        decisao.motivo = "Ação legislativa sem identificação suficiente para definir situação da regra."

    if acao not in {"ALTERA", "SUBSTITUI", "REVOGA", "PRORROGA", "RENOVA"}:
        conflitos = [r for r in ativas if _assunto_completo(nova.dados)
                     and _diverge_conteudo(nova.dados, r.dados)
                     and _sobreposicao(nova.dados, r.dados) is True]
        if conflitos:
            nova.dados["status_regra"] = "CONFLITO"
            nova.dados["confianca"] = "BAIXA"
            decisao.motivo = "Mesmo dispositivo e NCM com conteúdo fiscal divergente em vigências sobrepostas."
            for anterior in conflitos:
                if anterior.valor("status_validacao") == "PENDENTE":
                    decisao.alteracoes[anterior.id] = {"status_regra": "CONFLITO", "confianca": "BAIXA"}
                decisao.relacoes.append(RelacaoPlanejada(None, anterior.id, "CONFLITA_COM",
                    decisao.motivo, "ALTA"))

    _relacao_ncm(nova, existentes, decisao)
    if nova.valor("status_regra") == "INDETERMINADA":
        nova.dados["confianca"] = "BAIXA"
    nova.dados["motivo_consolidacao"] = decisao.motivo
    return decisao


def aplicar_em_memoria(decisao: Decisao, existentes: list[Consolidada], novo_id: int | None = None) -> None:
    """Atualiza cenário do dry-run ou sincroniza IDs após persistência."""

    for anterior in existentes:
        if anterior.id in decisao.alteracoes:
            anterior.dados.update(decisao.alteracoes[anterior.id])
        if anterior.id == decisao.duplicada_de and decisao.origem_id != anterior.valor("regra_origem_id"):
            origens = json.loads(anterior.valor("origens_equivalentes") or "[]")
            if decisao.origem_id not in origens:
                anterior.dados["origens_equivalentes"] = json.dumps(origens + [decisao.origem_id])
    if decisao.nova is not None:
        decisao.nova.id = novo_id if novo_id is not None else -(len(existentes) + 1)
        existentes.append(decisao.nova)

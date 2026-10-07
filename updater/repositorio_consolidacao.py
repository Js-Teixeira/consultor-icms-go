"""Persistência e leitura da Fase 3, restritas às tabelas intermediárias."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, func, insert, select, update

from .consolidacao import CONSOLIDATOR_VERSION, Consolidada, Decisao
from .fontes import ErroColeta, validar_url_oficial
from .schema import (
    atos_legislativos, evidencias_extracao, regras_consolidadas, regras_extraidas,
    relacoes_regras, versoes_ato,
)


class RepositorioConsolidacao:
    """Consulta fontes atuais e grava somente consolidações e relações."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def listar_extraidas(self, *, ato_id: int | None = None, ano: int | None = None,
                         limite: int = 10) -> list[dict[str, Any]]:
        versoes_anteriores = versoes_ato.alias("versoes_anteriores")
        ultima = select(func.max(versoes_anteriores.c.id)).where(
            versoes_anteriores.c.ato_id == atos_legislativos.c.id,
        ).correlate(atos_legislativos).scalar_subquery()
        consulta = select(
            regras_extraidas, atos_legislativos.c.tipo_ato, atos_legislativos.c.numero,
            atos_legislativos.c.ano, atos_legislativos.c.data_ato,
            atos_legislativos.c.url_texto_oficial,
        ).select_from(regras_extraidas).join(
            atos_legislativos, regras_extraidas.c.ato_id == atos_legislativos.c.id,
        ).join(versoes_ato, regras_extraidas.c.versao_ato_id == versoes_ato.c.id).where(
            regras_extraidas.c.versao_ato_id == ultima,
            regras_extraidas.c.status_revisao != "DESCARTADO",
            regras_extraidas.c.elegivel_consolidacao == "SIM",
            regras_extraidas.c.elegivel_consulta_ncm == "SIM",
            regras_extraidas.c.papel_dispositivo == "REGRA_MATERIAL",
            atos_legislativos.c.status != "ERRO",
            atos_legislativos.c.hash_conteudo == versoes_ato.c.hash_conteudo,
        ).order_by(atos_legislativos.c.data_ato, atos_legislativos.c.id,
                   regras_extraidas.c.id)
        if ato_id is not None:
            consulta = consulta.where(atos_legislativos.c.id == ato_id)
        if ano is not None:
            consulta = consulta.where(atos_legislativos.c.ano == ano)
        with self.engine.connect() as conexao:
            linhas = [dict(linha) for linha in conexao.execute(consulta).mappings()]
        selecionadas: list[dict[str, Any]] = []
        atos: set[int] = set()
        for linha in linhas:
            try:
                validar_url_oficial(linha["url_texto_oficial"] or "")
            except ErroColeta:
                continue
            if linha["ato_id"] not in atos and len(atos) >= limite:
                break
            atos.add(linha["ato_id"])
            selecionadas.append(linha)
        self._anexar_complementos(selecionadas)
        return selecionadas

    def _anexar_complementos(self, principais: list[dict[str, Any]]) -> None:
        """Acopla trechos e evidências do mesmo grupo sem criar outra consolidação."""

        grupos = {r["grupo_regra_id"] for r in principais if r["grupo_regra_id"]}
        if not grupos:
            return
        with self.engine.connect() as conexao:
            complementos = [dict(r) for r in conexao.execute(select(regras_extraidas).where(
                regras_extraidas.c.grupo_regra_id.in_(grupos),
                regras_extraidas.c.elegivel_consolidacao == "NAO",
                regras_extraidas.c.status_revisao != "DESCARTADO",
            ).order_by(regras_extraidas.c.inicio_trecho, regras_extraidas.c.id)).mappings()]
            ids = [r["id"] for r in complementos]
            evidencias = [dict(e) for e in conexao.execute(select(evidencias_extracao).where(
                evidencias_extracao.c.regra_extraida_id.in_(ids),
            ).order_by(evidencias_extracao.c.id)).mappings()] if ids else []
        por_regra: dict[int, list[dict[str, Any]]] = {}
        for evidencia in evidencias:
            por_regra.setdefault(evidencia["regra_extraida_id"], []).append({
                "id": evidencia["id"], "tipo": evidencia["tipo_evidencia"],
                "inicio": evidencia["posicao_inicio"], "fim": evidencia["posicao_fim"],
                "texto": evidencia["texto_origem"],
            })
        for principal in principais:
            ligados = [r for r in complementos if
                       r["ato_id"] == principal["ato_id"]
                       and r["versao_ato_id"] == principal["versao_ato_id"]
                       and r["extrator_versao"] == principal["extrator_versao"]
                       and r["grupo_regra_id"] == principal["grupo_regra_id"]]
            principal["complementos_json"] = json.dumps([{
                "regra_extraida_id": r["id"], "papel": r["papel_dispositivo"],
                "artigo": r["artigo"], "paragrafo": r["paragrafo"], "inciso": r["inciso"],
                "trecho": r["trecho_origem"], "inicio": r["inicio_trecho"],
                "fim": r["fim_trecho"], "evidencias": por_regra.get(r["id"], []),
            } for r in ligados], ensure_ascii=False) if ligados else None
            condicionantes = [r["trecho_origem"] for r in ligados if r["papel_dispositivo"] in {
                "CONDICAO", "BENEFICIARIO", "VEDACAO", "EXCECAO",
            }]
            if condicionantes:
                principal["condicoes_texto"] = "\n".join(filter(None, [
                    principal["condicoes_texto"], *condicionantes,
                ]))

    def listar_consolidadas(self, versao: str = CONSOLIDATOR_VERSION) -> list[Consolidada]:
        with self.engine.connect() as conexao:
            linhas = conexao.execute(select(regras_consolidadas).where(
                regras_consolidadas.c.consolidador_versao == versao,
            ).order_by(regras_consolidadas.c.id)).mappings().all()
        return [Consolidada(dict(linha), linha["id"]) for linha in linhas]

    def salvar(self, decisao: Decisao) -> int | None:
        """Aplica uma decisão indivisível; qualquer falha preserva o estado anterior."""

        with self.engine.begin() as conexao:
            if decisao.duplicada_de is not None:
                anterior = conexao.execute(select(regras_consolidadas).where(
                    regras_consolidadas.c.id == decisao.duplicada_de,
                ).with_for_update()).mappings().one()
                origens = json.loads(anterior["origens_equivalentes"] or "[]")
                if (decisao.origem_id != anterior["regra_origem_id"]
                        and decisao.origem_id not in origens):
                    conexao.execute(update(regras_consolidadas).where(
                        regras_consolidadas.c.id == decisao.duplicada_de,
                    ).values(origens_equivalentes=json.dumps(origens + [decisao.origem_id])))
                return None
            assert decisao.nova is not None
            nova_id = conexao.execute(insert(regras_consolidadas).values(
                **decisao.nova.dados,
            ).returning(regras_consolidadas.c.id)).scalar_one()
            for anterior_id, campos in decisao.alteracoes.items():
                resultado = conexao.execute(update(regras_consolidadas).where(
                    regras_consolidadas.c.id == anterior_id,
                    regras_consolidadas.c.status_validacao == "PENDENTE",
                ).values(**campos))
                if resultado.rowcount != 1:
                    raise RuntimeError("Regra anterior alterada por outra revisão; consolidação revertida.")
            for relacao in decisao.relacoes:
                origem = nova_id if relacao.origem_id is None else relacao.origem_id
                destino = nova_id if relacao.destino_id == 0 else relacao.destino_id
                conexao.execute(insert(relacoes_regras).values(
                    regra_origem_id=origem, regra_destino_id=destino,
                    tipo_relacao=relacao.tipo, motivo=relacao.motivo,
                    confianca=relacao.confianca,
                    consolidador_versao=decisao.nova.valor("consolidador_versao"),
                ))
        return nova_id

    def painel(self, limite: int = 100) -> list[dict[str, Any]]:
        """Lista somente leitura de consolidações da versão atual."""

        consulta = select(
            regras_consolidadas.c.id, regras_consolidadas.c.status_regra,
            regras_consolidadas.c.status_validacao, regras_consolidadas.c.ncm_chave,
            regras_consolidadas.c.tipo_regra, regras_consolidadas.c.tipo_beneficio,
            regras_consolidadas.c.aliquota_icms, regras_consolidadas.c.percentual_reducao_bc,
            regras_consolidadas.c.carga_efetiva, regras_consolidadas.c.credito_outorgado_percentual,
            regras_consolidadas.c.anexo, regras_consolidadas.c.artigo,
            regras_consolidadas.c.paragrafo, regras_consolidadas.c.inciso,
            regras_consolidadas.c.alinea, regras_consolidadas.c.item,
            regras_consolidadas.c.regra_anterior_id, regras_consolidadas.c.confianca,
            regras_consolidadas.c.alertas, regras_consolidadas.c.motivo_consolidacao,
            regras_consolidadas.c.regra_origem_id, atos_legislativos.c.tipo_ato,
            atos_legislativos.c.numero, atos_legislativos.c.ano,
        ).select_from(regras_consolidadas).join(
            atos_legislativos, regras_consolidadas.c.ato_origem_id == atos_legislativos.c.id,
        ).where(regras_consolidadas.c.consolidador_versao == CONSOLIDATOR_VERSION).order_by(
            regras_consolidadas.c.id.desc()).limit(limite)
        with self.engine.connect() as conexao:
            return [dict(linha) for linha in conexao.execute(consulta).mappings()]

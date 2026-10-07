"""Persistência auditável do monitoramento, sem escrever nas tabelas fiscais."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, func, insert, select, update

from .foco_ncm import classificar_foco_ncm
from .modelos import AVISO_DIVERGENCIA, AtoColetado
from .schema import atos_legislativos, monitoramento_legislativo, versoes_ato


def hash_conteudo(texto_limpo: str) -> str:
    """Identifica o conteúdo integral normalizado por SHA-256."""

    return hashlib.sha256(texto_limpo.encode("utf-8")).hexdigest()


def _dados_ncm(coleta: AtoColetado) -> dict[str, object]:
    prioridade = coleta.prioridade_ncm or classificar_foco_ncm(
        coleta.conteudo.texto_limpo if coleta.conteudo else "",
        " ".join((coleta.descoberto.titulo, coleta.descoberto.ementa)),
        coleta.conteudo.texto_original if coleta.conteudo else None,
    )
    return {
        "relevancia_ncm": prioridade.relevancia,
        "motivos_relevancia_ncm": "\n".join(prioridade.motivos),
        "quantidade_ncms_texto": prioridade.quantidade_ncms_texto,
        "possui_ncm_explicito": prioridade.possui_ncm_explicito,
        "possui_prefixo_ncm": prioridade.possui_prefixo_ncm,
        "possui_termo_material_icms": prioridade.possui_termo_material_icms,
        "texto_consolidado": coleta.conteudo.texto_consolidado if coleta.conteudo else "NAO",
    }


@dataclass
class ResumoExecucao:
    encontrada: int = 0
    descobertos_fonte: int = 0
    nova: int = 0
    atualizada: int = 0
    ignorados: int = 0
    erros: int = 0
    sem_comparacao: int = 0
    mensagem: str = ""

    def contar(self, operacao: str) -> None:
        if operacao == "novo":
            self.nova += 1
        elif operacao == "atualizado":
            self.atualizada += 1
        elif operacao == "ignorado":
            self.ignorados += 1
        elif operacao == "erro":
            self.erros += 1
        elif operacao == "candidato":
            self.sem_comparacao += 1


class RepositorioMonitoramento:
    """Acesso isolado às tabelas de atos, versões e execuções."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def prever_operacao(self, coleta: AtoColetado) -> str:
        """Compara identidade e hash em somente leitura para o dry-run."""

        if coleta.erro:
            return "erro"
        ato = coleta.descoberto
        novo_hash = hash_conteudo(coleta.conteudo.texto_limpo) if coleta.conteudo else None
        with self.engine.connect() as conexao:
            existente = conexao.execute(select(atos_legislativos.c.id, atos_legislativos.c.hash_conteudo).where(
                atos_legislativos.c.tipo_ato == ato.tipo_ato,
                atos_legislativos.c.numero == ato.numero,
                atos_legislativos.c.ano == ato.ano,
            )).mappings().first()
        if existente is None:
            return "novo"
        return "ignorado" if existente["hash_conteudo"] == novo_hash else "atualizado"

    def salvar_ato(self, coleta: AtoColetado) -> str:
        """Insere, verifica ou versiona um ato em transação indivisível."""

        ato = coleta.descoberto
        agora = datetime.now(timezone.utc)
        novo_hash = hash_conteudo(coleta.conteudo.texto_limpo) if coleta.conteudo else None
        with self.engine.begin() as conexao:
            existente = conexao.execute(
                select(atos_legislativos).where(
                    atos_legislativos.c.tipo_ato == ato.tipo_ato,
                    atos_legislativos.c.numero == ato.numero,
                    atos_legislativos.c.ano == ato.ano,
                ).with_for_update()
            ).mappings().first()
            if existente is None:
                dados = {
                    "tipo_ato": ato.tipo_ato, "numero": ato.numero, "ano": ato.ano,
                    "data_ato": coleta.conteudo.data_ato if coleta.conteudo else None,
                    "data_descoberta": ato.data_descoberta,
                    "data_ato_documento": coleta.conteudo.data_ato if coleta.conteudo else None,
                    "data_publicacao": coleta.conteudo.data_publicacao if coleta.conteudo else ato.data_publicacao,
                    "divergencia_data": coleta.divergencia_data,
                    "advertencia_data": "\n".join(coleta.advertencias) or None,
                    "titulo": ato.titulo,
                    "ementa": ato.ementa, "url_descoberta": ato.url_descoberta,
                    "url_texto_oficial": coleta.conteudo.url if coleta.conteudo else ato.url_arquivo_economia,
                    "texto_original": coleta.conteudo.texto_original if coleta.conteudo else None,
                    "texto_limpo": coleta.conteudo.texto_limpo if coleta.conteudo else None,
                    "hash_conteudo": novo_hash, "fonte": ato.fonte,
                    "data_coleta": agora, "data_ultima_verificacao": agora,
                    "status": coleta.status, "relevancia": coleta.classificacao.relevancia,
                    "motivos_relevancia": "\n".join(coleta.classificacao.motivos),
                    "erro_coleta": coleta.erro,
                }
                dados.update(_dados_ncm(coleta))
                ato_id = conexao.execute(insert(atos_legislativos).values(**dados).returning(atos_legislativos.c.id)).scalar_one()
                if coleta.conteudo:
                    self._salvar_versao(conexao, ato_id, novo_hash, coleta, agora)
                return "erro" if coleta.erro else "novo"

            if coleta.erro and coleta.conteudo is None:
                conexao.execute(update(atos_legislativos).where(atos_legislativos.c.id == existente["id"]).values(
                    data_ultima_verificacao=agora, erro_coleta=coleta.erro, status="ERRO",
                ))
                return "erro"

            if existente["hash_conteudo"] == novo_hash:
                data_ato = coleta.conteudo.data_ato or existente["data_ato"]
                data_descoberta = ato.data_descoberta or existente["data_descoberta"]
                if data_ato is not None and data_descoberta is not None:
                    divergencia = "SIM" if data_ato != data_descoberta else "NAO"
                    advertencia = AVISO_DIVERGENCIA if divergencia == "SIM" else None
                else:
                    divergencia = existente["divergencia_data"]
                    advertencia = existente["advertencia_data"]
                conexao.execute(update(atos_legislativos).where(atos_legislativos.c.id == existente["id"]).values(
                    data_ultima_verificacao=agora, erro_coleta=coleta.erro,
                    data_ato=data_ato,
                    data_descoberta=data_descoberta,
                    data_publicacao=coleta.conteudo.data_publicacao or existente["data_publicacao"],
                    data_ato_documento=coleta.conteudo.data_ato or existente["data_ato_documento"],
                    divergencia_data=divergencia,
                    advertencia_data=advertencia,
                    status="PROCESSADO" if not coleta.erro and existente["status"] == "PROCESSADO" else coleta.status,
                    url_texto_oficial=coleta.conteudo.url,
                    **_dados_ncm(coleta),
                ))
                return "erro" if coleta.erro else "ignorado"

            conexao.execute(update(atos_legislativos).where(atos_legislativos.c.id == existente["id"]).values(
                data_ato=coleta.conteudo.data_ato,
                data_descoberta=ato.data_descoberta,
                data_ato_documento=coleta.conteudo.data_ato,
                data_publicacao=coleta.conteudo.data_publicacao or ato.data_publicacao,
                divergencia_data=coleta.divergencia_data,
                advertencia_data="\n".join(coleta.advertencias) or None,
                titulo=ato.titulo, ementa=ato.ementa,
                url_descoberta=ato.url_descoberta, url_texto_oficial=coleta.conteudo.url,
                texto_original=coleta.conteudo.texto_original,
                texto_limpo=coleta.conteudo.texto_limpo, hash_conteudo=novo_hash,
                data_coleta=agora, data_ultima_verificacao=agora,
                status=coleta.status, relevancia=coleta.classificacao.relevancia,
                motivos_relevancia="\n".join(coleta.classificacao.motivos), erro_coleta=coleta.erro,
                **_dados_ncm(coleta),
            ))
            self._salvar_versao(conexao, existente["id"], novo_hash, coleta, agora)
            return "erro" if coleta.erro else "atualizado"

    @staticmethod
    def _salvar_versao(conexao, ato_id: int, conteudo_hash: str, coleta: AtoColetado, data: datetime) -> None:
        assert coleta.conteudo is not None
        conexao.execute(insert(versoes_ato).values(
            ato_id=ato_id, hash_conteudo=conteudo_hash,
            texto_original=coleta.conteudo.texto_original,
            texto_limpo=coleta.conteudo.texto_limpo, data_coleta=data,
            url_origem=coleta.conteudo.url,
            texto_consolidado=coleta.conteudo.texto_consolidado,
        ))

    def registrar_execucao(self, resumo: ResumoExecucao, fonte: str) -> None:
        """Grava contagens e eventual erro da execução para auditoria."""

        with self.engine.begin() as conexao:
            conexao.execute(insert(monitoramento_legislativo).values(
                fonte=fonte, quantidade_encontrada=resumo.encontrada,
                quantidade_nova=resumo.nova, quantidade_atualizada=resumo.atualizada,
                quantidade_ignorados=resumo.ignorados, quantidade_erros=resumo.erros,
                mensagem=resumo.mensagem or None,
            ))

    def painel(self) -> dict[str, object]:
        """Retorna apenas métricas para a página administrativa."""

        with self.engine.connect() as conexao:
            ultima = conexao.execute(select(monitoramento_legislativo.c.data_execucao).order_by(
                monitoramento_legislativo.c.data_execucao.desc()).limit(1)
            ).scalar_one_or_none()
            total = conexao.execute(select(func.count()).select_from(atos_legislativos)).scalar_one()
            pendentes = conexao.execute(select(func.count()).select_from(atos_legislativos).where(
                atos_legislativos.c.status == "NOVO"
            )).scalar_one()
            erros = conexao.execute(select(func.count()).select_from(atos_legislativos).where(
                atos_legislativos.c.status == "ERRO"
            )).scalar_one()
        return {"ultima_verificacao": ultima, "atos_monitorados": total,
                "novos_pendentes": pendentes, "erros_coleta": erros}

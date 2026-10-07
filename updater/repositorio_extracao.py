"""Leitura e escrita isoladas da Fase 2, sem acesso às tabelas fiscais."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from .extracao_fiscal import EXTRACTOR_VERSION, RegraExtraida
from .fontes import ErroColeta, validar_url_oficial
from .foco_ncm import NIVEIS, classificar_foco_ncm
from .schema import (
    atos_legislativos, evidencias_extracao, processamentos_extracao,
    regras_extraidas, versoes_ato,
)


@dataclass(frozen=True)
class AtoParaExtrair:
    id: int
    versao_id: int
    tipo_ato: str
    numero: str
    ano: int
    texto_limpo: str
    texto_original: str
    url_oficial: str

    @property
    def identificacao(self) -> str:
        return f"{self.tipo_ato} {self.numero}/{self.ano}"


class RepositorioExtracao:
    """Seleciona a versão atual e persiste apenas candidatos auditáveis."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def listar_atos(self, *, ano: int | None = None, ato_id: int | None = None,
                    limite: int = 10, relevancia: str = "ALTA") -> list[AtoParaExtrair]:
        versoes_anteriores = versoes_ato.alias("versoes_anteriores")
        ultima = select(func.max(versoes_anteriores.c.id)).where(
            versoes_anteriores.c.ato_id == atos_legislativos.c.id,
        ).correlate(atos_legislativos).scalar_subquery()
        consulta = select(
            atos_legislativos.c.id, versoes_ato.c.id.label("versao_id"),
            atos_legislativos.c.tipo_ato, atos_legislativos.c.numero,
            atos_legislativos.c.ano, versoes_ato.c.texto_limpo,
            versoes_ato.c.texto_original, atos_legislativos.c.url_texto_oficial,
            atos_legislativos.c.relevancia_ncm,
        ).select_from(atos_legislativos).join(versoes_ato, versoes_ato.c.id == ultima).where(
            atos_legislativos.c.relevancia == relevancia,
            atos_legislativos.c.status != "ERRO",
            atos_legislativos.c.hash_conteudo == versoes_ato.c.hash_conteudo,
            func.length(func.trim(versoes_ato.c.texto_limpo)) > 0,
        ).order_by(atos_legislativos.c.id.desc())
        if ano is not None:
            consulta = consulta.where(atos_legislativos.c.ano == ano)
        if ato_id is not None:
            consulta = consulta.where(atos_legislativos.c.id == ato_id)
        # Rejeições por fonte não oficial não consomem a cota solicitada.
        with self.engine.connect() as conexao:
            linhas = list(conexao.execute(consulta).mappings())
        atos: list[AtoParaExtrair] = []
        def prioridade(linha):
            nivel = linha.get("relevancia_ncm") or "SEM_INDICIO"
            if nivel == "SEM_INDICIO":
                # Compatibilidade com atos coletados antes da migração/priorização NCM.
                nivel = classificar_foco_ncm(
                    linha["texto_limpo"], html_original=linha["texto_original"]
                ).relevancia
            return NIVEIS.get(nivel, 0), linha["id"]

        linhas.sort(key=prioridade, reverse=True)
        for linha in linhas:
            url = linha["url_texto_oficial"] or ""
            try:
                validar_url_oficial(url)
            except ErroColeta:
                continue
            atos.append(AtoParaExtrair(
                linha["id"], linha["versao_id"], linha["tipo_ato"], linha["numero"],
                linha["ano"], linha["texto_limpo"], linha["texto_original"], url,
            ))
            if len(atos) >= limite:
                break
        return atos

    def processado(self, versao_id: int, extrator_versao: str = EXTRACTOR_VERSION) -> bool:
        """Inclui atos sem regras, cuja extração também deve ser idempotente."""

        with self.engine.connect() as conexao:
            status = conexao.execute(select(processamentos_extracao.c.status).where(
                processamentos_extracao.c.versao_ato_id == versao_id,
                processamentos_extracao.c.extrator_versao == extrator_versao,
            )).scalar_one_or_none()
        return status == "COMPLETO"

    def salvar(self, ato: AtoParaExtrair, regras: list[RegraExtraida],
               extrator_versao: str = EXTRACTOR_VERSION) -> tuple[int, list[str]]:
        """Usa savepoint por regra; falhas ficam reprocessáveis sem duplicar as demais."""

        erros: list[str] = []
        gravadas = 0
        with self.engine.begin() as conexao:
            existente = conexao.execute(select(processamentos_extracao.c.id, processamentos_extracao.c.status).where(
                processamentos_extracao.c.versao_ato_id == ato.versao_id,
                processamentos_extracao.c.extrator_versao == extrator_versao,
            ).with_for_update()).mappings().first()
            if existente and existente["status"] == "COMPLETO":
                return 0, []
            if existente:
                processamento_id = existente["id"]
            else:
                processamento_id = conexao.execute(insert(processamentos_extracao).values(
                    ato_id=ato.id, versao_ato_id=ato.versao_id,
                    extrator_versao=extrator_versao, status="PENDENTE",
                ).returning(processamentos_extracao.c.id)).scalar_one()
            for regra in regras:
                try:
                    with conexao.begin_nested():
                        ja_existe = conexao.execute(select(regras_extraidas.c.id).where(
                            regras_extraidas.c.versao_ato_id == ato.versao_id,
                            regras_extraidas.c.extrator_versao == extrator_versao,
                            regras_extraidas.c.chave_extracao == regra.chave_extracao,
                        )).scalar_one_or_none()
                        if ja_existe is not None:
                            continue
                        dados = {
                            campo: getattr(regra, campo) for campo in (
                                "tipo_regra", "acao_legislativa", "ncm_chave", "ncm_original",
                                "descricao_proxima_ncm",
                                "tipo_correspondencia", "descricao_legal", "descricao_resumida",
                                "aliquota_icms", "percentual_reducao_bc", "carga_efetiva",
                                "credito_outorgado_percentual", "tipo_beneficio", "anexo", "artigo",
                                "paragrafo", "inciso", "alinea", "item", "vigencia_inicio",
                                "vigencia_fim", "condicoes_texto", "norma_alterada", "trecho_origem",
                                "inicio_trecho", "fim_trecho", "confianca", "status_revisao",
                                "escopo_fiscal", "elegivel_consolidacao", "motivo_elegibilidade",
                                "papel_dispositivo", "grupo_regra_id",
                                "elegivel_consulta_ncm", "status_vinculo_ncm", "motivo_consulta_ncm",
                            )
                        }
                        dados.update(
                            ato_id=ato.id, versao_ato_id=ato.versao_id,
                            processamento_id=processamento_id, chave_extracao=regra.chave_extracao,
                            motivos_confianca="\n".join(regra.motivos_confianca),
                            alertas="\n".join(regra.alertas) or None,
                            extrator_versao=extrator_versao,
                        )
                        regra_id = conexao.execute(insert(regras_extraidas).values(**dados).returning(
                            regras_extraidas.c.id)).scalar_one()
                        for evidencia in regra.evidencias:
                            conexao.execute(insert(evidencias_extracao).values(
                                regra_extraida_id=regra_id,
                                tipo_evidencia=evidencia.tipo_evidencia,
                                valor_extraido=evidencia.valor_extraido,
                                texto_origem=evidencia.texto_origem,
                                posicao_inicio=evidencia.posicao_inicio,
                                posicao_fim=evidencia.posicao_fim,
                                confianca=evidencia.confianca,
                                metodo=evidencia.metodo,
                            ))
                        gravadas += 1
                except SQLAlchemyError as exc:
                    erros.append(f"Regra no trecho {regra.inicio_trecho}-{regra.fim_trecho}: {type(exc).__name__}")
            conexao.execute(update(processamentos_extracao).where(
                processamentos_extracao.c.id == processamento_id,
            ).values(status="FALHOU" if erros else "COMPLETO"))
        return gravadas, erros

    def pendentes(self, limite: int = 100) -> list[dict[str, object]]:
        """Consulta somente leitura para a área administrativa."""

        consulta = select(
            regras_extraidas.c.id, regras_extraidas.c.tipo_regra, regras_extraidas.c.ncm_chave,
            regras_extraidas.c.descricao_legal, regras_extraidas.c.aliquota_icms,
            regras_extraidas.c.percentual_reducao_bc, regras_extraidas.c.carga_efetiva,
            regras_extraidas.c.credito_outorgado_percentual, regras_extraidas.c.anexo,
            regras_extraidas.c.artigo, regras_extraidas.c.inciso, regras_extraidas.c.confianca,
            regras_extraidas.c.status_revisao, atos_legislativos.c.tipo_ato,
            regras_extraidas.c.escopo_fiscal, regras_extraidas.c.elegivel_consolidacao,
            regras_extraidas.c.motivo_elegibilidade,
            regras_extraidas.c.papel_dispositivo, regras_extraidas.c.grupo_regra_id,
            regras_extraidas.c.elegivel_consulta_ncm, regras_extraidas.c.status_vinculo_ncm,
            regras_extraidas.c.motivo_consulta_ncm,
            regras_extraidas.c.ncm_original, regras_extraidas.c.descricao_proxima_ncm,
            atos_legislativos.c.numero, atos_legislativos.c.ano,
        ).join(atos_legislativos, regras_extraidas.c.ato_id == atos_legislativos.c.id).where(
            regras_extraidas.c.status_revisao == "PENDENTE",
            regras_extraidas.c.status_vinculo_ncm.in_(("NCM_EXPLICITO", "PENDENTE_VINCULO_NCM")),
        ).order_by(regras_extraidas.c.id.desc()).limit(limite)
        with self.engine.connect() as conexao:
            return [dict(linha) for linha in conexao.execute(consulta).mappings()]

"""Execução manual da descoberta e auditoria legislativa."""

from __future__ import annotations

import argparse
import os

from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository

from .casacivil_go import buscar_texto_oficial, ler_arquivo_economia
from .economia_go import URL_CATEGORIA, descobrir_atos
from .foco_ncm import NIVEIS, classificar_foco_ncm
from .fontes import ClienteOficial, ErroColeta
from .modelos import AVISO_DIVERGENCIA, AtoColetado, AtoDescoberto
from .persistencia import RepositorioMonitoramento, ResumoExecucao
from .relevancia import classificar_relevancia


def coletar_ato(ato: AtoDescoberto, cliente: ClienteOficial) -> AtoColetado:
    """Obtém texto oficial quando disponível e registra falhas sem inferir teor."""

    conteudo = None
    erro = None
    advertencias: tuple[str, ...] = ()
    divergencia_data = "NAO"
    try:
        conteudo = buscar_texto_oficial(ato, cliente)
        if conteudo is None:
            conteudo = ler_arquivo_economia(ato, cliente)
            if ato.url_arquivo_economia and ato.url_arquivo_economia.lower().split("?", 1)[0].endswith(".doc"):
                if conteudo.data_ato is None:
                    erro = "Não foi possível conferir a data e a identidade no arquivo .doc."
        if (conteudo is not None and conteudo.data_ato is not None
                and ato.data_descoberta is not None and conteudo.data_ato != ato.data_descoberta):
            divergencia_data = "SIM"
            advertencias = (AVISO_DIVERGENCIA,)
    except ErroColeta as exc:
        erro = str(exc)
    texto_triagem = " ".join((ato.titulo, ato.ementa, conteudo.texto_limpo if conteudo else ""))
    prioridade_ncm = classificar_foco_ncm(
        conteudo.texto_limpo if conteudo else "", " ".join((ato.titulo, ato.ementa)),
        conteudo.texto_original if conteudo else None,
    )
    return AtoColetado(ato, conteudo, classificar_relevancia(texto_triagem),
                      erro, divergencia_data, advertencias, prioridade_ncm)


def executar(
    cliente: ClienteOficial, *, repositorio: RepositorioMonitoramento | None = None,
    dry_run: bool = False, ano: int | None = None, limite: int = 20,
    foco_ncm: bool = False, max_paginas: int = 10,
) -> tuple[ResumoExecucao, list[AtoColetado], list[str]]:
    """Executa a triagem; dry-run nunca grava e só consulta o banco se houver repositório."""

    if not dry_run and repositorio is None:
        raise ValueError("Repositório PostgreSQL necessário para execução normal.")
    resumo = ResumoExecucao()
    coletas: list[AtoColetado] = []
    operacoes: list[str] = []
    try:
        limite_descoberta = min(limite * 5, 500) if foco_ncm else limite
        atos = descobrir_atos(cliente, ano=ano, limite=limite_descoberta,
                             max_paginas=max_paginas)
        resumo.descobertos_fonte = len(atos)
        candidatos = [coletar_ato(ato, cliente) for ato in atos] if foco_ncm else None
        if candidatos is not None:
            candidatos.sort(key=lambda coleta: (
                not bool(coleta.conteudo),
                -NIVEIS[coleta.prioridade_ncm.relevancia] if coleta.prioridade_ncm else 0,
            ))
            selecionados = candidatos[:limite]
        else:
            selecionados = [coletar_ato(ato, cliente) for ato in atos]
        resumo.encontrada = len(selecionados)
        for coleta in selecionados:
            coletas.append(coleta)
            if dry_run:
                operacao = ("erro" if coleta.erro else
                            repositorio.prever_operacao(coleta) if repositorio is not None else "candidato")
            else:
                assert repositorio is not None
                operacao = repositorio.salvar_ato(coleta)
            operacoes.append(operacao)
            resumo.contar(operacao)
    except ErroColeta as exc:
        resumo.erros += 1
        resumo.mensagem = str(exc)
    finally:
        if not dry_run and repositorio is not None:
            repositorio.registrar_execucao(resumo, URL_CATEGORIA)
    return resumo, coletas, operacoes


def _mostrar_resumo(resumo: ResumoExecucao, coletas: list[AtoColetado], operacoes: list[str],
                   dry_run: bool, foco_ncm: bool = False) -> None:
    if dry_run:
        print("DRY-RUN: nenhuma escrita no banco.")
        for coleta, operacao in zip(coletas, operacoes):
            ato = coleta.descoberto
            origem = coleta.conteudo.url if coleta.conteudo else ato.url_arquivo_economia or ato.url_descoberta
            print(f"{ato.tipo_ato} {ato.numero}/{ato.ano} | {coleta.classificacao.relevancia} | {operacao.upper()}")
            print(f"  Fonte: {origem}")
            print(f"  Motivos: {'; '.join(coleta.classificacao.motivos)}")
            if foco_ncm and coleta.prioridade_ncm:
                prioridade = coleta.prioridade_ncm
                print(f"  Prioridade NCM: {prioridade.relevancia}")
                print(f"  NCMs encontrados: {', '.join(prioridade.ncms) or 'nenhum'}")
                print(f"  Motivo da prioridade: {'; '.join(prioridade.motivos)}")
                if coleta.conteudo:
                    print(f"  Texto consolidado indicado: {coleta.conteudo.texto_consolidado}")
            for advertencia in coleta.advertencias:
                print(f"  Aviso: {advertencia}")
            if coleta.divergencia_data == "SIM":
                if coleta.conteudo and coleta.conteudo.data_ato:
                    print(f"  Data do ato: {coleta.conteudo.data_ato.strftime('%d/%m/%Y')}")
                if ato.data_descoberta:
                    print(f"  Data da descoberta: {ato.data_descoberta.strftime('%d/%m/%Y')}")
                if coleta.conteudo and coleta.conteudo.data_publicacao:
                    print(f"  Data de publicação: {coleta.conteudo.data_publicacao.strftime('%d/%m/%Y')}")
            if coleta.erro:
                print(f"  Erro: {coleta.erro}")
    print(f"Atos encontrados: {resumo.encontrada}")
    print(f"Novos: {resumo.nova}")
    print(f"Atualizados: {resumo.atualizada}")
    print(f"Ignorados: {resumo.ignorados}")
    print(f"Erros: {resumo.erros}")
    if dry_run and resumo.sem_comparacao:
        print(f"Candidatos sem comparação com o banco: {resumo.sem_comparacao}")
    if foco_ncm:
        prioridades = [coleta.prioridade_ncm for coleta in coletas if coleta.prioridade_ncm]
        print(f"Atos encontrados na fonte: {resumo.descobertos_fonte}")
        print(f"Atos analisados após priorização: {resumo.encontrada}")
        print(f"Atos já existentes: {resumo.ignorados + resumo.atualizada}" if not resumo.sem_comparacao
              else "Atos já existentes: não verificado sem comparação com o banco")
        print(f"Atos novos: {resumo.nova}" if not resumo.sem_comparacao
              else "Atos novos: não verificado sem comparação com o banco")
        print(f"Atos com NCM explícito: {sum(p.possui_ncm_explicito == 'SIM' for p in prioridades)}")
        print(f"Atos com prefixo NCM: {sum(p.possui_prefixo_ncm == 'SIM' for p in prioridades)}")
        print(f"Atos com NCM + termo material de ICMS: {sum(p.quantidade_ncms_texto > 0 and p.possui_termo_material_icms == 'SIM' for p in prioridades)}")
        print(f"Atos apenas procedimentais: {sum(p.apenas_procedimental for p in prioridades)}")
        print(f"Atos sem indício NCM: {sum(p.relevancia == 'SEM_INDICIO' for p in prioridades)}")
    if resumo.mensagem:
        print(f"Mensagem: {resumo.mensagem}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitora atos oficiais do Estado de Goiás.")
    parser.add_argument("--dry-run", action="store_true", help="Consulta fontes sem gravar no banco")
    parser.add_argument("--ano", type=int, help="Filtra atos pelo ano identificado no título")
    parser.add_argument("--limite", type=int, default=20, help="Máximo de atos por execução (padrão: 20)")
    parser.add_argument("--foco-ncm", action="store_true", help="Ordena atos pelo potencial de consulta por NCM")
    parser.add_argument("--max-paginas", type=int, default=10,
                        help="Máximo de páginas oficiais a percorrer, de 1 a 100 (padrão: 10)")
    args = parser.parse_args()
    if args.ano is not None and not 1800 <= args.ano <= 9999:
        parser.error("--ano deve conter quatro dígitos válidos.")
    if args.limite < 1:
        parser.error("--limite deve ser maior que zero.")
    if not 1 <= args.max_paginas <= 100:
        parser.error("--max-paginas deve estar entre 1 e 100.")
    try:
        repositorio = None
        if not args.dry_run or os.getenv("DATABASE_URL"):
            repo_dados = criar_repositorio(data_source="postgres")
            assert isinstance(repo_dados, PostgresRepository)
            repositorio = RepositorioMonitoramento(repo_dados.engine)
        with ClienteOficial() as cliente:
            resumo, coletas, operacoes = executar(cliente, repositorio=repositorio,
                                                 dry_run=args.dry_run, ano=args.ano, limite=args.limite,
                                                 foco_ncm=args.foco_ncm, max_paginas=args.max_paginas)
    except ErroConfiguracaoDados as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError):
        print("Não foi possível acessar a base de monitoramento PostgreSQL.")
        return 1
    _mostrar_resumo(resumo, coletas, operacoes, args.dry_run, args.foco_ncm)
    return 1 if resumo.mensagem else 0


if __name__ == "__main__":
    raise SystemExit(main())

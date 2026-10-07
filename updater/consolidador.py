"""Comando da Fase 3: projeta e persiste consolidações sem publicar regras fiscais."""

from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository

from .consolidacao import (
    CONSOLIDATOR_VERSION, Consolidada, aplicar_em_memoria, planejar_regra,
)
from .repositorio_consolidacao import RepositorioConsolidacao


def executar(repo: RepositorioConsolidacao, *, ato_id: int | None = None,
             ano: int | None = None, limite: int = 10, dry_run: bool = False,
             versao: str = CONSOLIDATOR_VERSION) -> dict[str, int]:
    """Executa a mesma projeção em ambos os modos; dry-run só usa leituras."""

    entradas = repo.listar_extraidas(ato_id=ato_id, ano=ano, limite=limite)
    existentes: list[Consolidada] = repo.listar_consolidadas(versao)
    referencia = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    totais = {"atos": len({r["ato_id"] for r in entradas}), "extraidas": len(entradas),
              "novas": 0, "duplicadas": 0, "conflitos": 0, "revogacoes": 0, "erros": 0}
    for fonte in entradas:
        decisao = planejar_regra(fonte, existentes, referencia, versao)
        print(f"ATO: {decisao.identificacao} | regra extraída ID {decisao.origem_id}")
        print(f"  Regra extraída: {decisao.tipo_regra} | NCM: {decisao.ncm or 'não identificado'}")
        print(f"  Ação: {decisao.acao}")
        print(f"  Regra anterior encontrada: {decisao.anterior_id or 'nenhuma confirmada'}")
        print(f"  Resultado previsto: {decisao.status_previsto}")
        for anterior_id, campos in decisao.alteracoes.items():
            print(f"  Regra {anterior_id} → {campos.get('status_regra', 'relação atualizada')}")
        if decisao.nova:
            print(f"  Nova regra → {decisao.nova.valor('status_regra')}")
            print(f"  Confiança: {decisao.nova.valor('confianca')}")
            if decisao.nova.valor("alertas"):
                print(f"  Alertas: {decisao.nova.valor('alertas')}")
        if decisao.duplicada_de:
            print(f"  Duplicada de: regra consolidada {decisao.duplicada_de}")
        for relacao in decisao.relacoes:
            print(f"  Relação: {relacao.tipo} → regra {relacao.destino_id or 'nova'}")
        print(f"  Motivo: {decisao.motivo}")
        if dry_run:
            aplicar_em_memoria(decisao, existentes)
        else:
            try:
                novo_id = repo.salvar(decisao)
            except (SQLAlchemyError, ValueError, RuntimeError) as exc:
                totais["erros"] += 1
                print(f"  Erro ao consolidar: {type(exc).__name__}; transação revertida.")
                continue
            aplicar_em_memoria(decisao, existentes, novo_id)
        if decisao.nova:
            totais["novas"] += 1
            if decisao.nova.valor("status_regra") == "CONFLITO":
                totais["conflitos"] += 1
            if any(campos.get("status_regra") == "REVOGADA" for campos in decisao.alteracoes.values()):
                totais["revogacoes"] += 1
        else:
            totais["duplicadas"] += 1
    print("DRY-RUN: nenhuma escrita no PostgreSQL." if dry_run else "Consolidação concluída em tabelas intermediárias.")
    print(" | ".join(f"{nome}: {quantidade}" for nome, quantidade in totais.items()))
    return totais


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolida regras extraídas para revisão, sem publicação fiscal.")
    parser.add_argument("--ato-id", type=int, help="ID do ato armazenado")
    parser.add_argument("--ano", type=int, help="Ano dos atos")
    parser.add_argument("--limite", type=int, default=10, help="Máximo de atos")
    parser.add_argument("--dry-run", action="store_true", help="Projeta relações sem gravar")
    args = parser.parse_args()
    if args.limite < 1 or args.ato_id is not None and args.ato_id < 1:
        parser.error("--limite e --ato-id devem ser maiores que zero.")
    if args.ano is not None and not 1800 <= args.ano <= 9999:
        parser.error("--ano deve conter quatro dígitos válidos.")
    try:
        dados = criar_repositorio(data_source="postgres")
        assert isinstance(dados, PostgresRepository)
        totais = executar(RepositorioConsolidacao(dados.engine), ato_id=args.ato_id,
                         ano=args.ano, limite=args.limite, dry_run=args.dry_run)
    except ErroConfiguracaoDados as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError):
        print("Não foi possível ler o PostgreSQL de monitoramento. Verifique conexão e schema.")
        return 1
    return 1 if totais["erros"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

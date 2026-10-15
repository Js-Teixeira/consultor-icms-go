"""Simulação somente leitura de cadastros de alíquota e legislação."""

from __future__ import annotations

import argparse
import json

from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository
from updater.propostas_publicacao import simular_publicacao
from updater.repositorio_consolidacao import RepositorioConsolidacao


def main() -> int:
    parser = argparse.ArgumentParser(description="Projeta cadastros fiscais sem gravar no PostgreSQL.")
    parser.parse_args()
    try:
        dados = criar_repositorio(data_source="postgres")
        assert isinstance(dados, PostgresRepository)
        propostas, leis, aliquotas = RepositorioConsolidacao(dados.engine).dados_para_simulacao()
    except (ErroConfiguracaoDados, SQLAlchemyError, OSError):
        print("Não foi possível ler as propostas e o cadastro PostgreSQL.")
        return 2

    plano = simular_publicacao(propostas, legislacoes_existentes=leis,
                              aliquotas_existentes=aliquotas)
    print("DRY-RUN: nenhuma escrita no PostgreSQL; nenhuma proposta autorizada para publicação.")
    for registro in plano.para_revisao:
        origem = " | DADOS SINTÉTICOS" if registro.origem_sintetica else ""
        print(f"Proposta {registro.proposta_id} | PARA REVISÃO, SEM AUTORIZAÇÃO{origem}:")
        print("Legislacao: " + json.dumps(registro.legislacao, ensure_ascii=False, default=str))
        print("Aliquotas: " + json.dumps(registro.aliquota, ensure_ascii=False, default=str))
    for identificador in plano.inalteradas:
        print(f"Proposta {identificador} | já cadastrada sem mudança.")
    for identificador in plano.duplicadas_no_lote:
        print(f"Proposta {identificador} | duplicada nesta simulação.")
    for bloqueio in plano.bloqueadas:
        print(f"Proposta {bloqueio['proposta_id']} | BLOQUEADA: " + "; ".join(bloqueio["motivos"]))
    print(f"Para revisão: {len(plano.para_revisao)} | Inalteradas: {len(plano.inalteradas)} | "
          f"Duplicadas no lote: {len(plano.duplicadas_no_lote)} | "
          f"Bloqueadas: {len(plano.bloqueadas)}")
    return 0 if not plano.bloqueadas else 1


if __name__ == "__main__":
    raise SystemExit(main())

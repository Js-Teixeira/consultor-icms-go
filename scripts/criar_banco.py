"""Cria somente as tabelas no banco PostgreSQL já configurado."""

from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import metadata
from updater.schema import metadata as metadata_monitoramento
from updater.migracao import migrar_datas_monitoramento, migrar_escopo_extracao, migrar_prioridade_ncm


def criar_tabelas(repositorio: PostgresRepository) -> None:
    """Inicializa o schema sem criar o banco de dados nem inserir registros."""

    metadata.create_all(repositorio.engine)
    metadata_monitoramento.create_all(repositorio.engine)
    migrar_datas_monitoramento(repositorio.engine)
    migrar_prioridade_ncm(repositorio.engine)
    migrar_escopo_extracao(repositorio.engine)


def main() -> int:
    try:
        repositorio = criar_repositorio(data_source="postgres")
        assert isinstance(repositorio, PostgresRepository)
        criar_tabelas(repositorio)
    except ErroConfiguracaoDados as exc:
        print(exc)
        return 1
    except (SQLAlchemyError, OSError):
        print("Não foi possível acessar a base tributária online.")
        return 1
    print("Tabelas PostgreSQL verificadas/criadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

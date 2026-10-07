"""Migração explícita e aditiva dos vínculos fiscais curados."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio


CAMPOS = ("regra_consolidada_id", "evidencia_ncm_id")


def migrar(engine: Engine) -> list[str]:
    """Adiciona colunas INTEGER anuláveis, preservando todas as linhas existentes."""

    adicionadas: list[str] = []
    with engine.begin() as conexao:
        inspetor = inspect(conexao)
        for tabela in ("aliquotas", "beneficios"):
            existentes = {coluna["name"] for coluna in inspetor.get_columns(tabela)}
            for campo in CAMPOS:
                if campo not in existentes:
                    conexao.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {campo} INTEGER"))
                    adicionadas.append(f"{tabela}.{campo}")
    return adicionadas


def main() -> int:
    try:
        repositorio = criar_repositorio(data_source="postgres")
        adicionadas = migrar(repositorio.engine)
    except (ErroConfiguracaoDados, SQLAlchemyError, OSError):
        print("Migração não executada: verifique conexão e tabelas fiscais no PostgreSQL.")
        return 1
    print("Migração concluída. Colunas adicionadas: " + (", ".join(adicionadas) or "nenhuma"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

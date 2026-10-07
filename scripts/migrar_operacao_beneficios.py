"""Migração explícita e aditiva dos campos de operação do benefício."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from src.dados import ErroConfiguracaoDados, criar_repositorio


def migrar(engine: Engine) -> list[str]:
    """Adiciona apenas colunas ausentes, sem alterar linhas existentes."""

    adicionadas: list[str] = []
    with engine.begin() as conexao:
        existentes = {coluna["name"] for coluna in inspect(conexao).get_columns("beneficios")}
        for nome, tipo in (("escopo_operacao", "VARCHAR(14)"), ("cbenef", "TEXT")):
            if nome not in existentes:
                conexao.execute(text(f"ALTER TABLE beneficios ADD COLUMN {nome} {tipo}"))
                adicionadas.append(nome)
    return adicionadas


def main() -> int:
    try:
        repositorio = criar_repositorio(data_source="postgres")
        adicionadas = migrar(repositorio.engine)
    except (ErroConfiguracaoDados, SQLAlchemyError, OSError):
        print("Migração não executada: verifique a conexão e a tabela beneficios no PostgreSQL.")
        return 1
    print("Migração concluída. Colunas adicionadas: " + (", ".join(adicionadas) or "nenhuma"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

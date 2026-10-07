"""Leitura PostgreSQL no mesmo formato DataFrame da planilha."""

from __future__ import annotations

from hashlib import sha256
from threading import Lock

import pandas as pd
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from src.modelos import BaseTributaria

from .interface import ErroConfiguracaoDados, ErroFonteDados
from .schema import TABELAS

_engine_compartilhado: Engine | None = None
_fingerprint_url: str | None = None
_trava_engine = Lock()


def validar_database_url(database_url: str) -> None:
    """Exige o dialeto PostgreSQL com driver psycopg, sem ecoar a URL."""

    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError) as exc:
        raise ErroConfiguracaoDados("DATABASE_URL inválida; use postgresql+psycopg://...") from exc
    if url.drivername != "postgresql+psycopg" or not url.database:
        raise ErroConfiguracaoDados("DATABASE_URL inválida; use postgresql+psycopg://...")


def obter_engine(database_url: str) -> Engine:
    """Reutiliza o pool e o renova quando a URL configurada mudar."""

    global _engine_compartilhado, _fingerprint_url
    fingerprint = sha256(database_url.encode("utf-8")).hexdigest()
    with _trava_engine:
        if _engine_compartilhado is not None and _fingerprint_url == fingerprint:
            return _engine_compartilhado
        try:
            novo = create_engine(
                database_url,
                pool_pre_ping=True,
                pool_recycle=1800,
                connect_args={"connect_timeout": 5},
            )
        except Exception as exc:
            raise ErroConfiguracaoDados("Não foi possível configurar a conexão PostgreSQL.") from exc
        antigo = _engine_compartilhado
        _engine_compartilhado = novo
        _fingerprint_url = fingerprint
        if antigo is not None:
            antigo.dispose()
        return novo


class PostgresRepository:
    nome_fonte = "PostgreSQL"

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        validar_database_url(database_url)
        self.engine = engine if engine is not None else obter_engine(database_url)

    def carregar_base(self) -> BaseTributaria:
        """Lê as quatro tabelas ativas em uma conexão e preserva tipos fiscais."""

        dados: dict[str, pd.DataFrame] = {}
        try:
            with self.engine.connect() as conexao:
                for nome, tabela in TABELAS.items():
                    consulta = select(tabela).where(func.upper(func.trim(tabela.c.ativo)) == "SIM")
                    registros = [dict(linha) for linha in conexao.execute(consulta).mappings()]
                    dados[nome] = pd.DataFrame.from_records(
                        registros, columns=[coluna.name for coluna in tabela.columns]
                    )
        except (SQLAlchemyError, OSError) as exc:
            raise ErroFonteDados("Não foi possível acessar a base tributária online.") from exc

        return BaseTributaria(
            ncm=dados["NCM"],
            aliquotas=dados["Aliquotas"],
            beneficios=dados["Beneficios"],
            legislacao=dados["Legislacao"],
        )

    def testar_conexao(self) -> bool:
        """Executa somente SELECT 1 e não expõe detalhes da conexão."""

        try:
            with self.engine.connect() as conexao:
                return conexao.execute(text("SELECT 1")).scalar_one() == 1
        except (SQLAlchemyError, OSError):
            return False

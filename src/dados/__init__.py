"""PostgreSQL como única fonte operacional de dados tributários."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import Engine

try:  # A camada de dados também é usada por CLIs e testes sem Streamlit carregado.
    from streamlit.errors import StreamlitSecretNotFoundError
except ModuleNotFoundError:  # pragma: no cover - só ocorre fora da interface Streamlit
    class StreamlitSecretNotFoundError(Exception):
        pass

from .interface import ErroConfiguracaoDados, ErroFonteDados, RepositorioTributario
from .postgres_repository import PostgresRepository


def _segredo(secrets: Mapping[str, Any] | None, chave: str) -> str | None:
    if secrets is None:
        return None
    try:
        valor = secrets.get(chave)
    except (FileNotFoundError, KeyError, StreamlitSecretNotFoundError):
        return None
    return str(valor).strip() if valor else None


def criar_repositorio(
    *,
    data_source: str | None = None,
    database_url: str | None = None,
    secrets: Mapping[str, Any] | None = None,
    engine: Engine | None = None,
) -> RepositorioTributario:
    """Exige PostgreSQL; leitores históricos de arquivos são usados diretamente."""

    fonte_configurada = data_source if data_source is not None else os.getenv("DATA_SOURCE") or _segredo(secrets, "DATA_SOURCE")
    url = database_url if database_url is not None else os.getenv("DATABASE_URL") or _segredo(secrets, "DATABASE_URL")
    fonte = (fonte_configurada or "postgres").strip().lower()
    if fonte != "postgres":
        raise ErroConfiguracaoDados("PostgreSQL é a única fonte operacional; DATA_SOURCE deve ser 'postgres'.")
    if not url:
        raise ErroConfiguracaoDados("PostgreSQL selecionado, mas DATABASE_URL não foi configurada.")
    return PostgresRepository(url, engine=engine)


__all__ = ["criar_repositorio", "ErroConfiguracaoDados", "ErroFonteDados", "RepositorioTributario"]

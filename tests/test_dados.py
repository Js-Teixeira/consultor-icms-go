"""Contrato da camada de dados e da migração, sem servidor PostgreSQL."""

from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from src.dados import ErroConfiguracaoDados, ErroFonteDados, criar_repositorio
from src.dados.postgres_repository import PostgresRepository

URL_TESTE = "postgresql+psycopg://teste:teste@localhost/banco_teste"


class ResultadoFalso:
    def __init__(self, registros):
        self.registros = registros

    def mappings(self):
        return self.registros

    def scalar_one(self):
        return 1


class ConexaoLeituraFalsa:
    def __init__(self, dados):
        self.dados = dados
        self.comandos = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, comando):
        self.comandos.append(str(comando.compile(dialect=postgresql.dialect())))
        nome = comando.get_final_froms()[0] if hasattr(comando, "get_final_froms") else None
        return ResultadoFalso(self.dados.get(nome.name, []) if nome is not None else [])


class EngineLeituraFalso:
    def __init__(self, dados=None, *, falhar=False):
        self.conexao = ConexaoLeituraFalsa(dados or {})
        self.falhar = falhar

    def connect(self):
        if self.falhar:
            raise OperationalError("SELECT 1", {}, Exception("offline"))
        return self.conexao


def test_fonte_operacional_rejeita_excel_mesmo_com_url(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "excel")
    monkeypatch.setenv("DATABASE_URL", URL_TESTE)
    with pytest.raises(ErroConfiguracaoDados, match="única fonte operacional"):
        criar_repositorio()


def test_selecao_postgres_pela_url_e_por_data_source(monkeypatch):
    engine = EngineLeituraFalso()
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.setenv("DATABASE_URL", URL_TESTE)
    assert isinstance(criar_repositorio(engine=engine), PostgresRepository)
    monkeypatch.setenv("DATA_SOURCE", "postgres")
    assert isinstance(criar_repositorio(engine=engine), PostgresRepository)


def test_ausencia_url_postgres_falha_sem_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ErroConfiguracaoDados, match="DATABASE_URL não foi configurada"):
        criar_repositorio(data_source="postgres", secrets={})


@pytest.mark.parametrize("url", ["invalida", "sqlite:///x.db", "postgresql://localhost/x"])
def test_url_postgres_invalida(url):
    with pytest.raises(ErroConfiguracaoDados, match="DATABASE_URL inválida"):
        criar_repositorio(data_source="postgres", database_url=url)


def test_secrets_vazio_exige_postgres_sem_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    with pytest.raises(ErroConfiguracaoDados, match="DATABASE_URL não foi configurada"):
        criar_repositorio(secrets={})


def test_secrets_postgres_funcionam_sem_variaveis(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    repo = criar_repositorio(secrets={"DATABASE_URL": URL_TESTE}, engine=EngineLeituraFalso())
    assert isinstance(repo, PostgresRepository)


@pytest.mark.parametrize("fonte", ["excel", "csv", "desconhecida"])
def test_fonte_operacional_explicita_nao_postgres_e_rejeitada(fonte):
    with pytest.raises(ErroConfiguracaoDados, match="única fonte operacional"):
        criar_repositorio(data_source=fonte, database_url=URL_TESTE)


def test_postgres_retorna_dataframes_filtrados_e_tipos_preservados():
    engine = EngineLeituraFalso({
        "ncm": [{"ncm": "01234567", "descricao_oficial": "Sintético", "ativo": "SIM"}],
        "aliquotas": [{"id_regra": "R1", "chave_ncm": "01234567", "aliquota_icms": Decimal("0.10"), "ativo": "SIM"}],
    })
    repo = PostgresRepository(URL_TESTE, engine=engine)
    base = repo.carregar_base()
    assert base.ncm.iloc[0]["ncm"] == "01234567"
    assert isinstance(base.ncm.iloc[0]["ncm"], str)
    assert base.aliquotas.iloc[0]["aliquota_icms"] == Decimal("0.10")
    assert base.beneficios.empty and base.legislacao.empty
    assert len(engine.conexao.comandos) == 4
    assert all("upper(trim(" in sql.lower() and "ativo" in sql for sql in engine.conexao.comandos)


def test_falha_postgres_nao_cai_no_excel():
    repo = PostgresRepository(URL_TESTE, engine=EngineLeituraFalso(falhar=True))
    assert repo.testar_conexao() is False
    with pytest.raises(ErroFonteDados, match="Não foi possível acessar a base tributária online"):
        repo.carregar_base()


def test_saude_postgres_consulta_apenas_select_1():
    engine = EngineLeituraFalso()
    assert PostgresRepository(URL_TESTE, engine=engine).testar_conexao() is True
    assert engine.conexao.comandos == ["SELECT 1"]

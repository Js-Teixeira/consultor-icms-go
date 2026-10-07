"""Contrato da camada de dados e da migração, sem servidor PostgreSQL."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from scripts.importar_excel_postgres import ErroImportacao, importar_base, preparar_registros
from src.dados import ErroConfiguracaoDados, ErroFonteDados, criar_repositorio
from src.dados.excel_repository import ExcelRepository
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import TABELAS
from src.modelos import BaseTributaria

URL_TESTE = "postgresql+psycopg://teste:teste@localhost/banco_teste"


def _base_importacao(*, percentual="0.1") -> BaseTributaria:
    return BaseTributaria(
        ncm=pd.DataFrame([{"ncm": "01234567", "descricao_oficial": "Produto sintético", "ativo": "SIM"}]),
        legislacao=pd.DataFrame([{"id_legislacao": "L1", "norma": "Norma sintética", "ativo": "SIM"}]),
        aliquotas=pd.DataFrame([{
            "id_regra": "R1", "chave_ncm": "01234567", "tipo_correspondencia": "EXATO",
            "aliquota_icms": percentual, "id_legislacao": "L1", "ativo": "SIM",
            "exige_descricao": "NAO", "vigencia_inicio": date(2020, 1, 1),
        }]),
        beneficios=pd.DataFrame(columns=[col.name for col in TABELAS["Beneficios"].columns]),
    )


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


class EngineImportacaoFalso:
    """Emula a fronteira transacional e chaves únicas para verificar o fluxo."""

    def __init__(self, *, falhar_em=None):
        self.dados = {tabela.name: {} for tabela in TABELAS.values()}
        self.falhar_em = falhar_em
        self.comandos = []

    @contextmanager
    def begin(self):
        pendentes = deepcopy(self.dados)
        engine = self

        class Conexao:
            def execute(self, comando, registros):
                nome = comando.table.name
                if nome == engine.falhar_em:
                    raise OperationalError("INSERT", {}, Exception("falha simulada"))
                sql = str(comando.compile(dialect=postgresql.dialect()))
                engine.comandos.append(sql)
                chave = next(iter(comando.table.primary_key.columns)).name
                for registro in registros:
                    identificador = registro[chave]
                    if identificador not in pendentes[nome] or "DO UPDATE" in sql:
                        pendentes[nome][identificador] = deepcopy(registro)

        yield Conexao()
        self.dados = pendentes


def test_selecao_excel_explicita_ignora_url_indisponivel(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "excel")
    monkeypatch.setenv("DATABASE_URL", URL_TESTE)
    assert isinstance(criar_repositorio(), ExcelRepository)


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


def test_secrets_vazio_usa_excel(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    assert isinstance(criar_repositorio(secrets={}), ExcelRepository)


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


def test_preparacao_preserva_ncm_percentual_e_data():
    registros = preparar_registros(_base_importacao())
    assert registros["NCM"][0]["ncm"] == "01234567"
    assert registros["Aliquotas"][0]["aliquota_icms"] == Decimal("0.1")
    assert registros["Aliquotas"][0]["vigencia_inicio"] == date(2020, 1, 1)


@pytest.mark.parametrize("valor", [45000, "01/02/2026"])
def test_importacao_rejeita_data_ambigua(valor):
    base = _base_importacao()
    base.aliquotas["vigencia_inicio"] = pd.Series([valor], dtype=object)
    with pytest.raises(ErroImportacao, match="Data inválida"):
        preparar_registros(base)


def test_importacao_idempotente_e_atualizacao_explicita():
    engine = EngineImportacaoFalso()
    repo = PostgresRepository(URL_TESTE, engine=engine)
    importar_base(_base_importacao(), repo)
    importar_base(_base_importacao(percentual="0.2"), repo)
    assert engine.dados["aliquotas"]["R1"]["aliquota_icms"] == Decimal("0.1")
    assert len(engine.dados["aliquotas"]) == 1
    assert all("DO NOTHING" in sql for sql in engine.comandos)
    importar_base(_base_importacao(percentual="0.2"), repo, confirmar_atualizacao=True)
    assert engine.dados["aliquotas"]["R1"]["aliquota_icms"] == Decimal("0.2")
    assert any("DO UPDATE" in sql for sql in engine.comandos)


def test_rollback_se_importacao_falhar():
    engine = EngineImportacaoFalso(falhar_em="aliquotas")
    repo = PostgresRepository(URL_TESTE, engine=engine)
    with pytest.raises(OperationalError):
        importar_base(_base_importacao(), repo)
    assert all(not dados for dados in engine.dados.values())


def test_chave_duplicada_aba_toda_antes_de_escrever():
    base = _base_importacao()
    base.aliquotas = pd.concat([base.aliquotas, base.aliquotas], ignore_index=True)
    engine = EngineImportacaoFalso()
    with pytest.raises(ErroImportacao, match="duplicada"):
        importar_base(base, PostgresRepository(URL_TESTE, engine=engine))
    assert not engine.comandos


def test_ncm_numerico_recusado_para_evitar_perda_de_zero_inicial():
    base = _base_importacao()
    base.ncm["ncm"] = pd.Series([1234567], dtype=object)
    with pytest.raises(ErroImportacao, match="NCM deve ser texto"):
        preparar_registros(base)

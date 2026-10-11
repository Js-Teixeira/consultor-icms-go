"""Carga controlada do CSV e consultas com regras sintéticas."""

import csv
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from scripts.importar_excel_postgres import ErroImportacao
from scripts.importar_validacao_ncm import CAMINHO_VALIDACAO, COLUNAS, importar_validacao, ler_validacao
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import TABELAS, metadata


def _csv(caminho, linhas):
    campos = sorted(COLUNAS)
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)


def _linhas():
    return [
        {"tipo_registro": "NCM", "ncm": "12345678", "descricao_oficial": "Mercadoria sintética", "ativo": "SIM"},
        {"tipo_registro": "LEGISLACAO", "id_legislacao": "L1", "norma": "Norma sintética",
         "texto_relevante": "Trecho fictício de teste.", "url_fonte": "https://exemplo.gov.br/norma-ficticia", "ativo": "SIM"},
        {"tipo_registro": "ALIQUOTA", "id_regra": "R1", "chave_ncm": "12345678", "tipo_correspondencia": "EXATO",
         "aliquota_icms": "12", "id_legislacao": "L1", "exige_descricao": "NAO", "ativo": "SIM"},
    ]


def _repo():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return PostgresRepository("postgresql+psycopg://teste:teste@localhost/teste", engine=engine)


def test_arquivo_validacao_preserva_seis_ncms_originais():
    preparados, rascunhos = ler_validacao(CAMINHO_VALIDACAO)
    with CAMINHO_VALIDACAO.open(encoding="utf-8-sig", newline="") as arquivo:
        rascunhos_ncm = {
            linha["ncm"] for linha in csv.DictReader(arquivo)
            if linha["tipo_registro"].strip().upper() == "RASCUNHO"
        }
    esperados = {"02013000", "02023000", "10063011", "10063021", "19021100", "19021900"}
    assert esperados <= rascunhos_ncm | {registro["ncm"] for registro in preparados["NCM"]}
    assert rascunhos == len(rascunhos_ncm)


def test_carga_dry_run_idempotente_e_atualizacao_controlada(tmp_path):
    caminho = tmp_path / "carga.csv"
    linhas = _linhas()
    _csv(caminho, linhas)
    preparados, _ = ler_validacao(caminho)
    repo = _repo()
    plano = importar_validacao(preparados, repo, dry_run=True, confirmar_atualizacao=False)
    assert plano["Aliquotas"]["inserir"] == 1
    with repo.engine.connect() as conn:
        assert conn.execute(select(TABELAS["Aliquotas"])).first() is None
    importar_validacao(preparados, repo, dry_run=False, confirmar_atualizacao=False)
    with repo.engine.begin() as conn:
        conn.execute(TABELAS["NCM"].update().where(TABELAS["NCM"].c.ncm == "12345678").values(observacao="Metadado existente"))
    plano = importar_validacao(preparados, repo, dry_run=True, confirmar_atualizacao=False)
    assert plano["Aliquotas"]["iguais"] == 1
    assert plano["NCM"]["iguais"] == 1
    linhas[2]["aliquota_icms"] = "7"
    _csv(caminho, linhas)
    atualizados, _ = ler_validacao(caminho)
    with pytest.raises(ErroImportacao, match="confirmar-atualizacao"):
        importar_validacao(atualizados, repo, dry_run=False, confirmar_atualizacao=False)
    with repo.engine.connect() as conn:
        assert conn.execute(select(TABELAS["Aliquotas"].c.aliquota_icms)).scalar_one() == Decimal("12")
    plano = importar_validacao(atualizados, repo, dry_run=True, confirmar_atualizacao=True)
    assert plano["Aliquotas"]["atualizar"] == 1
    importar_validacao(atualizados, repo, dry_run=False, confirmar_atualizacao=True)
    with repo.engine.connect() as conn:
        assert conn.execute(select(TABELAS["Aliquotas"].c.aliquota_icms)).scalar_one() == Decimal("7")
        assert conn.execute(select(TABELAS["NCM"].c.observacao)).scalar_one() == "Metadado existente"


@pytest.mark.parametrize("mudanca", [
    {"aliquota_icms": "1200"}, {"vigencia_inicio": "2027-01-01", "vigencia_fim": "2026-01-01"},
    {"id_legislacao": ""}, {"chave_ncm": "99999999"},
])
def test_carga_inconsistente_aborta_sem_gravar(tmp_path, mudanca):
    linhas = _linhas()
    linhas[2].update(mudanca)
    caminho = tmp_path / "carga.csv"
    _csv(caminho, linhas)
    repo = _repo()
    with pytest.raises(ErroImportacao):
        preparados, _ = ler_validacao(caminho)
        importar_validacao(preparados, repo, dry_run=False, confirmar_atualizacao=False)
    with repo.engine.connect() as conn:
        assert conn.execute(select(TABELAS["NCM"])).first() is None


def test_falha_de_escrita_reverte_todas_as_tabelas(tmp_path):
    caminho = tmp_path / "carga.csv"
    _csv(caminho, _linhas())
    preparados, _ = ler_validacao(caminho)
    repo = _repo()
    with repo.engine.begin() as conn:
        conn.execute(text("CREATE TRIGGER impedir_aliquota BEFORE INSERT ON aliquotas BEGIN SELECT RAISE(ABORT, 'erro simulado'); END"))
    with pytest.raises(IntegrityError):
        importar_validacao(preparados, repo, dry_run=False, confirmar_atualizacao=False)
    with repo.engine.connect() as conn:
        assert all(conn.execute(select(tabela)).first() is None for tabela in TABELAS.values())

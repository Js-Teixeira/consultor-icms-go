"""Compatibilidade das rotinas administrativas de benefícios legados."""

import csv

import pytest
from sqlalchemy import create_engine, inspect, select, text

from scripts.validacao_carga_sql import ErroImportacao
from scripts.importar_validacao_ncm import COLUNAS, importar_validacao, ler_validacao
from scripts.migrar_operacao_beneficios import migrar
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import beneficios as tabela_beneficios, metadata


def test_migracao_aditiva_idempotente_preserva_registro():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conexao:
        conexao.execute(text("CREATE TABLE beneficios (id_beneficio TEXT PRIMARY KEY, condicoes TEXT)"))
        conexao.execute(text("INSERT INTO beneficios VALUES ('B1', 'Condição legada')"))
    assert migrar(engine) == ["escopo_operacao", "cbenef"]
    assert migrar(engine) == []
    with engine.connect() as conexao:
        assert {c["name"] for c in inspect(conexao).get_columns("beneficios")} == {
            "id_beneficio", "condicoes", "escopo_operacao", "cbenef",
        }
        linha = conexao.execute(text("SELECT * FROM beneficios WHERE id_beneficio='B1'")).mappings().one()
        assert linha["condicoes"] == "Condição legada"
        assert linha["escopo_operacao"] is None and linha["cbenef"] is None


def test_importador_aceita_novas_colunas_e_rejeita_escopo_invalido(tmp_path):
    caminho = tmp_path / "beneficios.csv"
    campos = ["tipo_registro", "id_beneficio", "chave_ncm", "tipo_correspondencia", "tipo_beneficio",
              "id_legislacao", "ativo", "exige_descricao", "escopo_operacao", "cbenef"]
    linha = {"tipo_registro": "BENEFICIO", "id_beneficio": "B1", "chave_ncm": "12345678",
             "tipo_correspondencia": "EXATO", "tipo_beneficio": "ISENCAO", "id_legislacao": "L1",
             "ativo": "SIM", "exige_descricao": "NAO", "escopo_operacao": "INTERNA",
             "cbenef": "CODIGO_FICTICIO"}
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerow(linha)
    preparados, _ = ler_validacao(caminho)
    assert preparados["Beneficios"][0]["escopo_operacao"] == "INTERNA"
    assert preparados["Beneficios"][0]["cbenef"] == "CODIGO_FICTICIO"
    linha["escopo_operacao"] = "EXTERNA"
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerow(linha)
    with pytest.raises(ErroImportacao, match="escopo_operacao inválido"):
        ler_validacao(caminho)


def test_importador_legado_e_alteracao_de_cbenef_exigem_confirmacao(tmp_path):
    caminho = tmp_path / "carga.csv"
    campos_antigos = sorted(COLUNAS - {"escopo_operacao", "cbenef"})
    linhas = [
        {"tipo_registro": "NCM", "ncm": "12345678", "descricao_oficial": "Produto fictício", "ativo": "SIM"},
        {"tipo_registro": "LEGISLACAO", "id_legislacao": "L1", "norma": "Norma fictícia",
         "texto_relevante": "Texto fictício", "url_fonte": "https://exemplo.gov.br/norma", "ativo": "SIM"},
        {"tipo_registro": "BENEFICIO", "id_beneficio": "B1", "chave_ncm": "12345678",
         "tipo_correspondencia": "EXATO", "tipo_beneficio": "ISENCAO", "id_legislacao": "L1",
         "ativo": "SIM", "exige_descricao": "NAO"},
    ]
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos_antigos)
        escritor.writeheader()
        escritor.writerows(linhas)
    antigos, _ = ler_validacao(caminho)
    assert antigos["Beneficios"][0]["escopo_operacao"] is None
    assert antigos["Beneficios"][0]["cbenef"] is None
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repo = PostgresRepository("postgresql+psycopg://teste:teste@localhost/teste", engine=engine)
    importar_validacao(antigos, repo, dry_run=False, confirmar_atualizacao=False)

    linhas[2]["escopo_operacao"] = "INTERNA"
    linhas[2]["cbenef"] = "CODIGO_FICTICIO"
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=sorted(COLUNAS))
        escritor.writeheader()
        escritor.writerows(linhas)
    novos, _ = ler_validacao(caminho)
    with pytest.raises(ErroImportacao, match="confirmar-atualizacao"):
        importar_validacao(novos, repo, dry_run=False, confirmar_atualizacao=False)
    with engine.connect() as conexao:
        linha = conexao.execute(select(tabela_beneficios)).mappings().one()
    assert linha["escopo_operacao"] is None and linha["cbenef"] is None

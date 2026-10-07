"""Operação e aplicabilidade com NCMs e fundamentos inteiramente sintéticos."""

import csv

import pytest
from sqlalchemy import create_engine, inspect, select, text

from scripts.importar_excel_postgres import ErroImportacao
from scripts.importar_validacao_ncm import COLUNAS, importar_validacao, ler_validacao
from scripts.migrar_operacao_beneficios import migrar
from src.busca import consultar
from src.carregamento import carregar_base
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import beneficios as tabela_beneficios, metadata
from src.formatacao import EXIBICAO_BENEFICIO, campos_preenchidos
from tests.test_consulta import HOJE, base, beneficio
from tests.test_consulta_e_apresentacao import _planilha_teste


def _consulta_beneficio(escopo, operacao="INTERNA", **campos):
    b = base(beneficios=[beneficio(escopo_operacao=escopo, exige_descricao="NAO", **campos)])
    resultado = consultar(b, "12345678", data_referencia=HOJE, operacao=operacao)
    return resultado, resultado.beneficios_encontrados[0]


@pytest.mark.parametrize(("escopo", "operacao", "esperado"), [
    ("INTERNA", "INTERNA", "APLICAVEL"),
    ("INTERNA", "INTERESTADUAL", "NAO_APLICAVEL"),
    ("INTERESTADUAL", "INTERESTADUAL", "APLICAVEL"),
    ("INTERESTADUAL", "INTERNA", "NAO_APLICAVEL"),
    ("AMBAS", "INTERNA", "APLICAVEL"),
    ("AMBAS", "INTERESTADUAL", "APLICAVEL"),
    ("NAO_DEFINIDA", "INTERNA", "REVISAO_NECESSARIA"),
    (None, "INTERNA", "REVISAO_NECESSARIA"),
])
def test_matriz_operacao_estruturada(escopo, operacao, esperado):
    resultado, candidato = _consulta_beneficio(escopo, operacao)
    assert candidato.aplicabilidade == esperado
    assert resultado.operacao_consultada == operacao
    if esperado == "NAO_APLICAVEL":
        assert "vinculado a operação" in candidato.motivo_aplicabilidade
    if escopo in (None, "NAO_DEFINIDA"):
        assert resultado.nivel_confianca == "REVISAO_NECESSARIA"
        assert "não está estruturado" in candidato.motivo_aplicabilidade


def test_condicao_textual_gera_condicional_sem_interpretacao_automatica():
    condicao = "Somente para indústria em Goiás; comprovação documental necessária."
    resultado, candidato = _consulta_beneficio("INTERNA", condicoes=condicao)
    assert candidato.aplicabilidade == "CONDICIONAL"
    assert candidato.dados["condicoes"] == condicao
    assert resultado.nivel_confianca == "ALTA"
    assert "não podem ser comprovadas" in candidato.motivo_aplicabilidade
    _, outra_operacao = _consulta_beneficio("INTERNA", "INTERESTADUAL", condicoes=condicao)
    assert outra_operacao.aplicabilidade == "NAO_APLICAVEL"


def test_cbenef_cadastrado_e_vazio_nao_inferido():
    _, preenchido = _consulta_beneficio("INTERNA", cbenef="CODIGO_FICTICIO")
    assert preenchido.cbenef == "CODIGO_FICTICIO"
    assert dict(campos_preenchidos(preenchido, EXIBICAO_BENEFICIO))["cBenef"] == "CODIGO_FICTICIO"
    _, vazio = _consulta_beneficio("INTERNA")
    assert vazio.cbenef == ""
    assert "cBenef" not in dict(campos_preenchidos(vazio, EXIBICAO_BENEFICIO))


def test_multiplos_beneficios_exibidos_com_status_individuais():
    b = base(beneficios=[
        beneficio("B1", escopo_operacao="INTERNA", aplicacao="UNICO", exige_descricao="NAO"),
        beneficio("B2", escopo_operacao="INTERESTADUAL", aplicacao="CUMULATIVO", exige_descricao="NAO"),
    ])
    resultado = consultar(b, "12345678", data_referencia=HOJE, operacao="INTERNA")
    assert {c.identificador: c.aplicabilidade for c in resultado.beneficios_encontrados} == {
        "B1": "APLICAVEL", "B2": "NAO_APLICAVEL",
    }
    assert {c.identificador for c in resultado.beneficios_priorizados} == {"B1", "B2"}


def test_alternativos_nao_ocultam_candidata_nao_selecionada():
    b = base(beneficios=[
        beneficio("B1", descricao_regra="Produto de teste", palavras_chave="produto de teste", escopo_operacao="INTERNA",
                  aplicacao="ALTERNATIVO", grupo_beneficio="G", exige_descricao="SIM"),
        beneficio("B2", descricao_regra="Bateria automotiva", palavras_chave="bateria", escopo_operacao="INTERNA",
                  aplicacao="ALTERNATIVO", grupo_beneficio="G", exige_descricao="SIM"),
    ])
    resultado = consultar(b, "12345678", "Produto de teste", data_referencia=HOJE)
    assert {c.identificador for c in resultado.beneficios_encontrados} == {"B1", "B2"}
    assert {c.aplicabilidade for c in resultado.beneficios_encontrados} == {"APLICAVEL", "REVISAO_NECESSARIA"}


def test_alternativos_empatados_exigem_revisao_individual():
    b = base(beneficios=[
        beneficio("B1", escopo_operacao="INTERNA", aplicacao="ALTERNATIVO", grupo_beneficio="G"),
        beneficio("B2", escopo_operacao="INTERNA", aplicacao="ALTERNATIVO", grupo_beneficio="G"),
    ])
    resultado = consultar(b, "12345678", data_referencia=HOJE)
    assert not resultado.beneficios_priorizados
    assert len(resultado.beneficios_encontrados) == 2
    assert all(c.aplicabilidade == "REVISAO_NECESSARIA" for c in resultado.beneficios_encontrados)
    assert resultado.nivel_confianca == "REVISAO_NECESSARIA"


def test_prioridade_exato_6_4_2_e_sem_fallback_de_capitulo():
    regras = [
        beneficio("B2", "12", "PREFIXO", escopo_operacao="INTERNA", aplicacao="ALTERNATIVO", grupo_beneficio="G"),
        beneficio("B4", "1234", "PREFIXO", escopo_operacao="INTERNA", aplicacao="ALTERNATIVO", grupo_beneficio="G"),
        beneficio("B6", "123456", "PREFIXO", escopo_operacao="INTERNA", aplicacao="ALTERNATIVO", grupo_beneficio="G"),
        beneficio("B8", "12345678", "EXATO", escopo_operacao="INTERNA", aplicacao="ALTERNATIVO", grupo_beneficio="G"),
    ]
    for quantidade, esperado in ((4, "B8"), (3, "B6"), (2, "B4"), (1, "B2")):
        resultado = consultar(base(beneficios=regras[:quantidade]), "12345678", data_referencia=HOJE)
        assert len(resultado.beneficios_encontrados) == quantidade
        assert resultado.beneficios_priorizados[0].identificador == esperado
        assert sum(c.aplicabilidade == "APLICAVEL" for c in resultado.beneficios_encontrados) == 1
    sem_capitulo = consultar(base(beneficios=[regras[1]]), "12345678", data_referencia=HOJE)
    assert {c.chave_ncm for c in sem_capitulo.beneficios_encontrados} == {"1234"}


def test_descricao_obrigatoria_sem_texto_nao_confirma_beneficio():
    b = base(beneficios=[beneficio(escopo_operacao="INTERNA", exige_descricao="SIM",
                                   descricao_regra="Produto de teste", palavras_chave="produto")])
    resultado = consultar(b, "12345678", data_referencia=HOJE)
    assert not resultado.beneficios_priorizados
    assert resultado.beneficios_encontrados[0].aplicabilidade == "REVISAO_NECESSARIA"


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


def test_excel_legado_sem_colunas_novas_carrega_com_escopo_indefinido(tmp_path):
    caminho = tmp_path / "legado.xlsx"
    _planilha_teste(caminho, beneficios=[beneficio(exige_descricao="NAO", aplicacao="UNICO",
                                                   grupo_beneficio="")])
    carregada = carregar_base(caminho)
    resultado = consultar(carregada, "12345678", data_referencia=HOJE)
    assert resultado.beneficios_encontrados[0].escopo_operacao == "NAO_DEFINIDA"
    assert resultado.beneficios_encontrados[0].cbenef == ""


def test_operacao_invalida_rejeitada():
    with pytest.raises(ValueError, match="Operação inválida"):
        consultar(base(), "12345678", operacao="EXTERNA")

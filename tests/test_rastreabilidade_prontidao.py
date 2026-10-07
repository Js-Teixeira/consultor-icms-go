"""Vínculos curados, migração aditiva e diagnóstico de produção sem escrita."""

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, create_engine, event, inspect, select, text
from sqlalchemy.exc import OperationalError

from scripts.importar_excel_postgres import ErroImportacao, _normalizar_linha, validar_rastreabilidade
from scripts.importar_validacao_ncm import importar_validacao, ler_validacao
from scripts.migrar_rastreabilidade_fiscal import migrar
from scripts.verificar_prontidao_producao import verificar_schema
import scripts.verificar_prontidao_producao as prontidao
from src.auditor_integridade import auditar_integridade
from src.cobertura_fiscal import resumir_cobertura
from src.dados.schema import TABELAS, metadata
from src.modelos import BaseTributaria


def _base():
    return BaseTributaria(
        ncm=pd.DataFrame([{"ncm": "85021319", "ativo": "SIM", "descricao_oficial": "Produto sintético"}]),
        aliquotas=pd.DataFrame([{"id_regra": "A1", "chave_ncm": "85021319", "tipo_correspondencia": "EXATO",
                                "aliquota_icms": "12", "id_legislacao": "L1", "ativo": "SIM",
                                "exige_descricao": "NAO", "vigencia_inicio": "2020-01-01", "vigencia_fim": "2030-12-31"}]),
        beneficios=pd.DataFrame(columns=[c.name for c in TABELAS["Beneficios"].columns]),
        legislacao=pd.DataFrame([{"id_legislacao": "L1", "ativo": "SIM", "norma": "Norma sintética",
                                  "url_fonte": "https://exemplo.gov.br", "texto_relevante": "Trecho sintético",
                                  "vigencia_inicio": "2020-01-01", "vigencia_fim": "2030-12-31"}]),
    )


def _updater():
    return {
        "regras_consolidadas": [{"id": 10, "regra_origem_id": 20}],
        "regras_extraidas": [{"id": 20, "confianca": "ALTA", "ncm_chave": "85021319"},
                              {"id": 21, "confianca": "ALTA", "ncm_chave": "85021319"}],
        "evidencias_extracao": [{"id": 30, "regra_extraida_id": 20, "tipo_evidencia": "NCM",
                                  "valor_extraido": "8502.13.19", "texto_origem": "Trecho", "metodo": "manual"}],
    }


def _codigos(base, updater=None):
    return {(o.codigo, o.nivel, o.tabela) for o in auditar_integridade(base, updater=updater).ocorrencias}


def test_rastreabilidade_vazia_aceita_sem_ocorrencia():
    assert not any(c.startswith("RASTREABILIDADE") for c, _, _ in _codigos(_base(), _updater()))


@pytest.mark.parametrize("campo,valor,codigo", [
    ("regra_consolidada_id", 999, "RASTREABILIDADE_CONSOLIDACAO_INEXISTENTE"),
    ("evidencia_ncm_id", 999, "RASTREABILIDADE_EVIDENCIA_INEXISTENTE"),
])
def test_alvo_inexistente_e_erro(campo, valor, codigo):
    base = _base()
    base.aliquotas.loc[0, campo] = valor
    assert (codigo, "ERRO", "aliquotas") in _codigos(base, _updater())


def test_cadeia_incompativel_e_erro():
    base = _base()
    base.aliquotas.loc[0, "regra_consolidada_id"] = 10
    base.aliquotas.loc[0, "evidencia_ncm_id"] = 30
    updater = _updater()
    updater["evidencias_extracao"][0]["regra_extraida_id"] = 21
    assert ("RASTREABILIDADE_INCONSISTENTE", "ERRO", "aliquotas") in _codigos(base, updater)


def test_origem_equivalente_explicita_pertence_a_cadeia():
    base = _base()
    base.aliquotas.loc[0, "regra_consolidada_id"] = 10
    base.aliquotas.loc[0, "evidencia_ncm_id"] = 30
    updater = _updater()
    updater["regras_consolidadas"][0]["origens_equivalentes"] = "[21]"
    updater["evidencias_extracao"][0]["regra_extraida_id"] = 21
    assert ("RASTREABILIDADE_INCONSISTENTE", "ERRO", "aliquotas") not in _codigos(base, updater)


def test_ato_de_consolidacao_incompativel_com_extracao():
    base = _base()
    base.aliquotas.loc[0, "regra_consolidada_id"] = 10
    updater = _updater()
    updater["regras_consolidadas"][0]["ato_origem_id"] = 5
    updater["regras_extraidas"][0]["ato_id"] = 6
    assert ("RASTREABILIDADE_INCONSISTENTE", "ERRO", "aliquotas") in _codigos(base, updater)


def test_evidencia_ncm_formatada_compativel_e_incompativel():
    base = _base()
    base.aliquotas.loc[0, "evidencia_ncm_id"] = 30
    updater = _updater()
    assert not any(c == "NCM_EVIDENCIA_INCOMPATIVEL" for c, _, _ in _codigos(base, updater))
    updater["evidencias_extracao"][0]["valor_extraido"] = "8502.13.20"
    assert ("NCM_EVIDENCIA_INCOMPATIVEL", "ERRO", "aliquotas") in _codigos(base, updater)


def test_origem_baixa_alerta_na_regra_final():
    base = _base()
    base.aliquotas.loc[0, "regra_consolidada_id"] = 10
    updater = _updater()
    updater["regras_extraidas"][0]["confianca"] = "BAIXA"
    assert ("REGRA_ORIGEM_BAIXA_CONFIANCA", "ALERTA", "aliquotas") in _codigos(base, updater)


def test_beneficio_pode_ter_vinculo_curado_sem_alterar_regra_fiscal():
    base = _base()
    base.beneficios = pd.DataFrame([{
        "id_beneficio": "B1", "chave_ncm": "85021319", "tipo_correspondencia": "EXATO",
        "tipo_beneficio": "ISENCAO", "id_legislacao": "L1", "ativo": "SIM", "exige_descricao": "NAO",
        "escopo_operacao": "INTERNA", "cbenef": "FICTICIO", "regra_consolidada_id": 10,
        "evidencia_ncm_id": 30, "vigencia_inicio": "2020-01-01", "vigencia_fim": "2030-12-31",
    }])
    assert not any(c.startswith("RASTREABILIDADE") or c == "NCM_EVIDENCIA_INCOMPATIVEL"
                   for c, _, _ in _codigos(base, _updater()))


def test_migracao_aditiva_idempotente_preserva_linhas():
    engine = create_engine("sqlite://")
    with engine.begin() as conexao:
        for tabela, chave in (("aliquotas", "id_regra"), ("beneficios", "id_beneficio")):
            conexao.execute(text(f"CREATE TABLE {tabela} ({chave} TEXT PRIMARY KEY)"))
            conexao.execute(text(f"INSERT INTO {tabela} VALUES ('LEGADO')"))
    assert len(migrar(engine)) == 4
    assert migrar(engine) == []
    with engine.connect() as conexao:
        for tabela in ("aliquotas", "beneficios"):
            colunas = {c["name"]: c for c in inspect(conexao).get_columns(tabela)}
            assert colunas["regra_consolidada_id"]["nullable"]
            assert colunas["evidencia_ncm_id"]["nullable"]
            assert conexao.execute(text(f"SELECT count(*) FROM {tabela}")).scalar_one() == 1


@pytest.mark.parametrize("valor", ["-1", "1.2", "abc", "0"])
def test_importador_rejeita_id_invalido(valor):
    linha = pd.Series({"id_regra": "A1", "chave_ncm": "85021319", "tipo_correspondencia": "EXATO",
                       "ativo": "SIM", "exige_descricao": "NAO", "regra_consolidada_id": valor})
    with pytest.raises(ErroImportacao, match="ID inválido"):
        _normalizar_linha("Aliquotas", TABELAS["Aliquotas"], linha, 2)


@pytest.mark.parametrize("chave,tipo,aceito", [
    ("12", "PREFIXO", True), ("1234", "PREFIXO", True), ("123456", "PREFIXO", True),
    ("1", "PREFIXO", False), ("123", "PREFIXO", False), ("12345", "PREFIXO", False),
    ("1234567", "PREFIXO", False), ("12345678", "PREFIXO", False),
    ("12345678", "EXATO", True), ("123456", "EXATO", False),
])
def test_importador_valida_comprimento_da_correspondencia(chave, tipo, aceito):
    linha = pd.Series({"id_regra": "A1", "chave_ncm": chave, "tipo_correspondencia": tipo,
                       "ativo": "SIM", "exige_descricao": "NAO"})
    if aceito:
        assert _normalizar_linha("Aliquotas", TABELAS["Aliquotas"], linha, 2)["chave_ncm"] == chave
    else:
        with pytest.raises(ErroImportacao, match="tipo_correspondencia inválido"):
            _normalizar_linha("Aliquotas", TABELAS["Aliquotas"], linha, 2)


def test_importador_aborta_id_sem_updater_antes_de_escrever():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    preparados, _ = ler_validacao()
    preparados["Aliquotas"][0]["regra_consolidada_id"] = 999
    repo = type("Repo", (), {"engine": engine})()
    with pytest.raises(ErroImportacao, match="regras_consolidadas"):
        importar_validacao(preparados, repo, dry_run=False, confirmar_atualizacao=False)
    with engine.connect() as conexao:
        assert conexao.execute(select(TABELAS["Aliquotas"])).first() is None


def test_importador_rejeita_id_inexistente_com_tabelas_updater():
    engine = create_engine("sqlite://")
    meta = MetaData()
    Table("regras_consolidadas", meta, Column("id", Integer, primary_key=True), Column("regra_origem_id", Integer),
          Column("origens_equivalentes", Text), Column("ato_origem_id", Integer))
    Table("regras_extraidas", meta, Column("id", Integer, primary_key=True), Column("ato_id", Integer))
    Table("evidencias_extracao", meta, Column("id", Integer, primary_key=True),
          Column("regra_extraida_id", Integer), Column("tipo_evidencia", String), Column("valor_extraido", Text))
    meta.create_all(engine)
    preparados = {nome: [] for nome in TABELAS}
    preparados["Aliquotas"] = [{"id_regra": "A1", "chave_ncm": "85021319", "regra_consolidada_id": 99,
                                "evidencia_ncm_id": None}]
    with engine.connect() as conexao, pytest.raises(ErroImportacao, match="CONSOLIDACAO_INEXISTENTE"):
        validar_rastreabilidade(conexao, preparados)


def test_importador_confere_cadeia_e_aceita_ids_curados():
    engine = create_engine("sqlite://")
    meta = MetaData()
    Table("regras_consolidadas", meta, Column("id", Integer, primary_key=True), Column("regra_origem_id", Integer),
          Column("origens_equivalentes", Text), Column("ato_origem_id", Integer))
    Table("regras_extraidas", meta, Column("id", Integer, primary_key=True), Column("ato_id", Integer))
    Table("evidencias_extracao", meta, Column("id", Integer, primary_key=True),
          Column("regra_extraida_id", Integer), Column("tipo_evidencia", String), Column("valor_extraido", Text))
    meta.create_all(engine)
    preparados = {nome: [] for nome in TABELAS}
    preparados["Aliquotas"] = [{"id_regra": "A1", "chave_ncm": "85021319", "regra_consolidada_id": 10,
                                "evidencia_ncm_id": 30}]
    with engine.begin() as conexao:
        conexao.execute(text("INSERT INTO regras_extraidas (id) VALUES (20), (21)"))
        conexao.execute(text("INSERT INTO regras_consolidadas (id, regra_origem_id) VALUES (10, 20)"))
        conexao.execute(text("INSERT INTO evidencias_extracao VALUES (30, 21, 'NCM', '8502.13.19')"))
        with pytest.raises(ErroImportacao, match="RASTREABILIDADE_INCONSISTENTE"):
            validar_rastreabilidade(conexao, preparados)
        conexao.execute(text("UPDATE evidencias_extracao SET regra_extraida_id=20 WHERE id=30"))
        validar_rastreabilidade(conexao, preparados)


def test_cobertura_exato_prefixo_sem_tratamento_cadastrado():
    base = _base()
    base.ncm = pd.concat([base.ncm, pd.DataFrame([
        {"ncm": "85029999", "ativo": "SIM"}, {"ncm": "99999999", "ativo": "SIM"}])], ignore_index=True)
    base.beneficios = pd.DataFrame([{"id_beneficio": "B1", "chave_ncm": "8502", "tipo_correspondencia": "PREFIXO",
                                    "ativo": "SIM"}])
    assert resumir_cobertura(base) == {
        "ncms_cadastrados": 3, "ncms_com_aliquota": 1, "ncms_com_beneficio": 2,
        "ncms_sem_tratamento_cadastrado": 1, "regras_exato": 1, "regras_prefixo": 1,
    }


def test_verificador_somente_leitura_detecta_migracao_pendente():
    engine = create_engine("sqlite://")
    with engine.begin() as conexao:
        for nome, chave in (("ncm", "ncm"), ("aliquotas", "id_regra"),
                            ("beneficios", "id_beneficio"), ("legislacao", "id_legislacao")):
            conexao.execute(text(f"CREATE TABLE {nome} ({chave} TEXT PRIMARY KEY)"))
    comandos = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cursor, statement, *_: comandos.append(statement))
    resultado = verificar_schema(engine)
    assert resultado["conexao"] and not resultado["operacao"] and not resultado["rastreabilidade"]
    assert not resultado["schema"]
    assert all(not comando.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE"))
               for comando in comandos)


def test_verificador_aceita_credencial_publica_select_only_sem_updater(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as conexao:
        conexao.execute(TABELAS["NCM"].insert().values(
            ncm="85021319", descricao_oficial="Produto sintético", ativo="SIM"))
    for tabela in ("regras_consolidadas", "regras_extraidas", "evidencias_extracao"):
        with engine.begin() as conexao:
            conexao.execute(text(f"CREATE TABLE {tabela} (id INTEGER PRIMARY KEY)"))
    comandos = []

    def negar_admin(_conexao, _cursor, sql, _params, _contexto, _many):
        comandos.append(sql)
        if "FROM regras_consolidadas" in sql:
            raise OperationalError(sql, {}, Exception("permission denied"))

    event.listen(engine, "before_cursor_execute", negar_admin)
    monkeypatch.setenv("DATA_SOURCE", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://usuario:segredo@host/banco")
    monkeypatch.setattr(prontidao, "criar_repositorio", lambda **_kwargs: type("Repo", (), {"engine": engine})())
    monkeypatch.setattr(prontidao, "verificar_schema", lambda _engine: {
        "conexao": True, "schema": True, "operacao": True, "rastreabilidade": True,
        "tabelas": {t.name: True for t in TABELAS.values()},
        "contagens": {"NCM": 1, "Aliquotas": 0, "Beneficios": 0, "Legislacao": 0},
        "ncms_banco": {"85021319"},
        "permissoes": {t.name: {"SELECT": True, "INSERT": False, "UPDATE": False, "DELETE": False}
                       for t in TABELAS.values()},
    })
    cache = tmp_path / "cache.json"
    cache.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(prontidao, "CAMINHO_CACHE", cache)
    monkeypatch.setattr(prontidao, "carregar_cache", lambda: (
        {"85021319": {}}, None, {"download_em": "2026-10-04T12:00:00+00:00"}))
    monkeypatch.setattr(prontidao, "conferir_snapshot_base", lambda _base: (14, 4))
    estados, motivos, detalhes = prontidao.verificar_prontidao()
    assert estados["PostgreSQL"] == "OK"
    assert estados["Auditoria"].startswith("OK")
    assert estados["Permissões"] == "OK (somente leitura)"
    assert estados["Regressões PostgreSQL"] == "OK (14 casos, 4 benefícios)"
    assert detalhes["auditoria"]["INFO"] == 1
    assert motivos == []
    assert all(not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP"))
               for sql in comandos)

    def divergencia(_base):
        raise AssertionError("NCM 02013000: alíquota ou fundamento divergente")

    monkeypatch.setattr(prontidao, "conferir_snapshot_base", divergencia)
    estados, motivos, _ = prontidao.verificar_prontidao()
    assert estados["PostgreSQL"] == "OK"
    assert estados["Auditoria"].startswith("OK")
    assert estados["Regressões PostgreSQL"] == "FALHA"
    assert any("02013000" in motivo for motivo in motivos)


def test_app_publico_permanece_consulta_e_sem_modulos_fora_do_escopo():
    raiz = Path(__file__).resolve().parents[1]
    app = (raiz / "app.py").read_text(encoding="utf-8")
    assert "form_submit_button(\"CONSULTAR\"" in app
    assert not any(f"{nome}(" in app for nome in ("migrar", "importar_base", "importar_validacao"))
    busca = (raiz / "src" / "busca.py").read_text(encoding="utf-8")
    assert not any(nome in busca for nome in ("CFOP", "CST", "CSOSN", "CEST"))

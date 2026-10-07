"""Auditor somente leitura com dados sintéticos e sem fonte externa."""

import csv
import json
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError

import scripts.auditar_integridade as cli
from src.auditor_integridade import ADMINISTRATIVO_NAO_VERIFICADO, auditar_integridade
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import metadata, ncm
from src.modelos import BaseTributaria

REFERENCIA = date(2026, 10, 3)


def _base():
    periodo = {"vigencia_inicio": "2020-01-01", "vigencia_fim": "2030-12-31"}
    return BaseTributaria(
        ncm=pd.DataFrame([{"ncm": "12345678", "descricao_oficial": "Produto sintético", "ativo": "SIM"}]),
        aliquotas=pd.DataFrame([{"id_regra": "A1", "chave_ncm": "12345678", "tipo_correspondencia": "EXATO",
                                "aliquota_icms": "12", "id_legislacao": "L1", "ativo": "SIM",
                                "exige_descricao": "NAO", **periodo}]),
        beneficios=pd.DataFrame([{"id_beneficio": "B1", "chave_ncm": "12345678", "tipo_correspondencia": "EXATO",
                                 "tipo_beneficio": "ISENCAO", "grupo_beneficio": "", "aplicacao": "UNICO",
                                 "carga_efetiva": "7", "escopo_operacao": "INTERNA", "cbenef": "CODIGO_FICTICIO",
                                 "condicoes": "Condição fictícia", "id_legislacao": "L1", "ativo": "SIM",
                                 "exige_descricao": "NAO", **periodo}]),
        legislacao=pd.DataFrame([{"id_legislacao": "L1", "norma": "Norma fictícia",
                                  "url_fonte": "https://exemplo.gov.br/norma", "texto_relevante": "Trecho fictício",
                                  "ativo": "SIM", **periodo}]),
    )


def _ocorrencias(base, **kwargs):
    return auditar_integridade(base, referencia=REFERENCIA, **kwargs).ocorrencias


def _codigos(base, **kwargs):
    return {o.codigo for o in _ocorrencias(base, **kwargs)}


def test_base_sintetica_estruturalmente_completa():
    relatorio = auditar_integridade(_base(), referencia=REFERENCIA)
    assert relatorio.contagem_niveis() == {"ERRO": 0, "ALERTA": 0, "INFO": 0}
    assert relatorio.totais_tabelas == {"ncm": 1, "aliquotas": 1, "beneficios": 1, "legislacao": 1}
    assert "LACUNA DE RASTREABILIDADE" in relatorio.lacunas[0]


def test_pk_duplicada_e_primeira_ocorrencia():
    b = _base()
    b.ncm = pd.concat([b.ncm, b.ncm], ignore_index=True)
    assert _ocorrencias(b)[0].codigo == "PK_DUPLICADA"


def test_ncm_invalido_incompleto_e_inexistente():
    b = _base()
    b.ncm.loc[0, "ncm"] = "1234X678"
    b.aliquotas.loc[0, "chave_ncm"] = "123456"
    b.beneficios.loc[0, "chave_ncm"] = "99999999"
    codigos = _codigos(b)
    assert {"NCM_INVALIDO", "NCM_INCOMPLETO", "NCM_INEXISTENTE"} <= codigos
    inexistente = next(o for o in _ocorrencias(b) if o.codigo == "NCM_INEXISTENTE")
    assert inexistente.nivel == "ALERTA"


@pytest.mark.parametrize("prefixo", ["12", "1234", "123456"])
def test_prefixo_estruturado_valido_nao_e_ncm_incompleto(prefixo):
    b = _base()
    b.aliquotas.loc[0, "tipo_correspondencia"] = "PREFIXO"
    b.aliquotas.loc[0, "chave_ncm"] = prefixo
    assert "NCM_INCOMPLETO" not in _codigos(b)
    assert "NCM_INVALIDO" not in _codigos(b)


def test_prefixo_nao_estruturado_e_catalogo_oficial_opcional():
    b = _base()
    b.aliquotas.loc[0, "tipo_correspondencia"] = "PREFIXO"
    b.aliquotas.loc[0, "chave_ncm"] = "123"
    assert "NCM_INVALIDO" in _codigos(b)
    b.aliquotas.loc[0, "chave_ncm"] = "12"
    assert "NCM_INEXISTENTE" not in _codigos(b)
    assert "NCM_INEXISTENTE" in _codigos(b, catalogo_oficial={"99999999"})


@pytest.mark.parametrize("prefixo", ["1", "123", "12345", "1234567", "12345678"])
def test_auditor_rejeita_prefixos_fora_da_estrutura(prefixo):
    b = _base()
    b.aliquotas.loc[0, "tipo_correspondencia"] = "PREFIXO"
    b.aliquotas.loc[0, "chave_ncm"] = prefixo
    assert "NCM_INVALIDO" in _codigos(b)


def test_beneficio_sem_ncm_e_fundamento_ausente():
    b = _base()
    b.beneficios.loc[0, "chave_ncm"] = ""
    b.beneficios.loc[0, "id_legislacao"] = ""
    assert {"BENEFICIO_SEM_NCM", "BENEFICIO_SEM_LEGISLACAO"} <= _codigos(b)


def test_legislacao_inexistente_e_sem_fonte_ou_trecho():
    b = _base()
    b.beneficios.loc[0, "id_legislacao"] = "INEXISTENTE"
    b.legislacao.loc[0, "url_fonte"] = ""
    b.legislacao.loc[0, "texto_relevante"] = ""
    assert {"LEGISLACAO_INEXISTENTE", "LEGISLACAO_SEM_FONTE",
            "LEGISLACAO_SEM_TEXTO_RELEVANTE"} <= _codigos(b)


def test_regra_ativa_com_fundamento_inativo():
    b = _base()
    b.legislacao.loc[0, "ativo"] = "NAO"
    assert "LEGISLACAO_INATIVA" in _codigos(b)


def test_vigencia_inconsistente_aberta_ausente_e_encerrada():
    b = _base()
    b.aliquotas.loc[0, "vigencia_inicio"] = "2031-01-01"
    assert "VIGENCIA_INCONSISTENTE" in _codigos(b)
    b.aliquotas.loc[0, "vigencia_inicio"] = "2020-01-01"
    b.aliquotas.loc[0, "vigencia_fim"] = None
    assert "VIGENCIA_INCONSISTENTE" not in _codigos(b)
    b.aliquotas.loc[0, "vigencia_inicio"] = None
    assert "VIGENCIA_NAO_ESTRUTURADA" in _codigos(b)
    b.aliquotas.loc[0, "vigencia_fim"] = "2025-12-31"
    assert "REGRA_ATIVA_COM_VIGENCIA_ENCERRADA" in _codigos(b)
    assert "BENEFICIO_REVOGADO_ATIVO" not in _codigos(b)


def test_aliquota_ausente_e_conflito_sem_escolha():
    b = _base()
    b.aliquotas.loc[0, "aliquota_icms"] = None
    assert any(o.codigo == "ALIQUOTA_AUSENTE" and o.nivel == "ERRO" for o in _ocorrencias(b))
    b = _base()
    segunda = b.aliquotas.iloc[0].to_dict()
    segunda.update(id_regra="A2", aliquota_icms="19")
    b.aliquotas = pd.concat([b.aliquotas, pd.DataFrame([segunda])], ignore_index=True)
    assert any(o.codigo == "CONFLITO_ALIQUOTA" and o.nivel == "ERRO" for o in _ocorrencias(b))


def test_beneficios_distintos_coexistem_duplicidade_e_conflito_material():
    b = _base()
    segunda = b.beneficios.iloc[0].to_dict()
    segunda.update(id_beneficio="B2", tipo_beneficio="DIFERIMENTO")
    b.beneficios = pd.concat([b.beneficios, pd.DataFrame([segunda])], ignore_index=True)
    assert "CONFLITO_BENEFICIO" not in _codigos(b)
    assert "DUPLICIDADE_FUNCIONAL" not in _codigos(b)
    b.beneficios.loc[1, "tipo_beneficio"] = "ISENCAO"
    assert "DUPLICIDADE_FUNCIONAL" in _codigos(b)
    b.beneficios.loc[1, "carga_efetiva"] = "5"
    assert any(o.codigo == "CONFLITO_BENEFICIO" and o.nivel == "ALERTA" for o in _ocorrencias(b))


def test_reducao_com_carga_efetiva_e_sem_ambos_valores():
    b = _base()
    b.beneficios.loc[0, "tipo_beneficio"] = "REDUCAO_BASE_CALCULO"
    assert "REDUCAO_SEM_VALOR" not in _codigos(b)
    b.beneficios.loc[0, "carga_efetiva"] = None
    assert "REDUCAO_SEM_VALOR" in _codigos(b)


def test_operacao_cbenef_condicoes_e_descricao():
    b = _base()
    b.beneficios.loc[0, "escopo_operacao"] = "NAO_DEFINIDA"
    b.beneficios.loc[0, "cbenef"] = None
    b.beneficios.loc[0, "condicoes"] = None
    b.beneficios.loc[0, "exige_descricao"] = "SIM"
    b.beneficios.loc[0, "descricao_regra"] = None
    b.beneficios.loc[0, "palavras_chave"] = None
    codigos = _codigos(b)
    assert {"OPERACAO_NAO_ESTRUTURADA", "CBENEF_NAO_CADASTRADO", "CONDICOES_AUSENTES",
            "REGRA_EXIGE_DESCRICAO_SEM_REFERENCIA"} <= codigos
    assert next(o for o in _ocorrencias(b) if o.codigo == "CBENEF_NAO_CADASTRADO").nivel == "INFO"
    b.beneficios.loc[0, "escopo_operacao"] = "EXTERNA"
    assert "OPERACAO_INVALIDA" in _codigos(b)


def test_texto_revogado_sem_vinculo_estruturado_nao_gera_conclusao():
    b = _base()
    b.beneficios.loc[0, "condicoes"] = "Palavra revogado em observação sem relação estruturada."
    assert "BENEFICIO_REVOGADO_ATIVO" not in _codigos(b)


def test_updater_baixa_confianca_apenas_com_id_ligado():
    b = _base()
    updater = {"regras_extraidas": [{"id": 10, "confianca": "BAIXA", "ncm_chave": "12345678"}],
               "regras_consolidadas": [{"id": 20, "regra_origem_id": 10, "ncm_chave": "12345678"}]}
    assert "REGRA_ORIGEM_BAIXA_CONFIANCA" in _codigos(b, updater=updater)
    updater["regras_consolidadas"][0]["regra_origem_id"] = 99
    assert "REGRA_ORIGEM_BAIXA_CONFIANCA" not in _codigos(b, updater=updater)


def test_ncm_automatico_sem_evidencia_so_com_prova_estruturada():
    b = _base()
    updater = {"regras_extraidas": [{"id": 10, "ncm_chave": "12345678", "confianca": "MEDIA"}],
               "evidencias_extracao": [{"id": 30, "regra_extraida_id": 10, "tipo_evidencia": "NCM",
                                        "valor_extraido": "1234.56.78", "metodo": "varredura_integral_v3",
                                        "texto_origem": ""}]}
    assert "NCM_AUTOMATICO_SEM_EVIDENCIA" in _codigos(b, updater=updater)
    updater["evidencias_extracao"][0]["texto_origem"] = "NCM 1234.56.78"
    assert "NCM_AUTOMATICO_SEM_EVIDENCIA" not in _codigos(b, updater=updater)
    updater["evidencias_extracao"] = []
    assert "NCM_AUTOMATICO_SEM_EVIDENCIA" not in _codigos(b, updater=updater)


def _csv_cli(caminho, *, aliquota="12"):
    campos = ["tipo_registro", "ncm", "descricao_oficial", "ativo", "id_regra", "chave_ncm",
              "tipo_correspondencia", "aliquota_icms", "id_legislacao", "vigencia_inicio", "vigencia_fim",
              "url_fonte", "texto_relevante"]
    linhas = [
        {"tipo_registro": "NCM", "ncm": "12345678", "descricao_oficial": "Produto sintético", "ativo": "SIM"},
        {"tipo_registro": "LEGISLACAO", "id_legislacao": "L1", "ativo": "SIM",
         "url_fonte": "https://exemplo.gov.br", "texto_relevante": "Trecho fictício"},
        {"tipo_registro": "ALIQUOTA", "id_regra": "A1", "chave_ncm": "12345678",
         "tipo_correspondencia": "EXATO", "aliquota_icms": aliquota, "id_legislacao": "L1",
         "ativo": "SIM", "vigencia_inicio": "2020-01-01"},
    ]
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)


def test_cli_exit_code_alerta_e_erro_json(monkeypatch, tmp_path, capsys):
    caminho = tmp_path / "auditoria.csv"
    _csv_cli(caminho)
    monkeypatch.setattr("sys.argv", ["auditar_integridade", "--arquivo-csv", str(caminho), "--json"])
    assert cli.main() == 0
    dados = json.loads(capsys.readouterr().out)
    assert dados["niveis"]["ERRO"] == 0
    assert dados["niveis"]["ALERTA"] >= 1
    _csv_cli(caminho, aliquota="")
    assert cli.main() == 1
    dados = json.loads(capsys.readouterr().out)
    assert dados["por_codigo"]["ALIQUOTA_AUSENTE"] == 1


def test_leitura_postgres_simulada_nao_executa_dml():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as conexao:
        conexao.execute(ncm.insert().values(ncm="12345678", descricao_oficial="Produto", ativo="SIM"))
    comandos = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cur, sql, _p, _ctx, _many: comandos.append(sql))
    repo = PostgresRepository("postgresql+psycopg://teste:teste@localhost/teste", engine=engine)
    base, updater = cli.carregar_postgres_somente_leitura(repo)
    assert base.ncm.iloc[0]["ncm"] == "12345678"
    assert ADMINISTRATIVO_NAO_VERIFICADO in updater
    relatorio = auditar_integridade(base, updater=updater)
    assert relatorio.contagem_codigos()["RASTREABILIDADE_ADMINISTRATIVA_NAO_VERIFICADA"] == 1
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "DROP")) for sql in comandos)
    with engine.connect() as conexao:
        assert conexao.execute(select(ncm.c.ncm)).scalar_one() == "12345678"


def test_leitura_postgres_legado_sem_migracao_de_operacao():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conexao:
        for ddl in ("CREATE TABLE ncm (ncm TEXT PRIMARY KEY, ativo TEXT)",
                    "CREATE TABLE aliquotas (id_regra TEXT PRIMARY KEY, ativo TEXT)",
                    "CREATE TABLE beneficios (id_beneficio TEXT PRIMARY KEY, ativo TEXT)",
                    "CREATE TABLE legislacao (id_legislacao TEXT PRIMARY KEY, ativo TEXT)"):
            conexao.execute(text(ddl))
        conexao.execute(text("INSERT INTO beneficios VALUES ('B_LEGADO', 'SIM')"))
    repo = PostgresRepository("postgresql+psycopg://teste:teste@localhost/teste", engine=engine)
    base, _ = cli.carregar_postgres_somente_leitura(repo)
    assert len(base.beneficios) == 1
    assert pd.isna(base.beneficios.iloc[0]["escopo_operacao"])
    assert pd.isna(base.beneficios.iloc[0]["cbenef"])


def _engine_fiscal_com_updater_sintetico():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as conexao:
        conexao.execute(ncm.insert().values(ncm="12345678", descricao_oficial="Produto", ativo="SIM"))
        for tabela in ("regras_consolidadas", "regras_extraidas", "evidencias_extracao"):
            conexao.execute(text(f"CREATE TABLE {tabela} (id INTEGER PRIMARY KEY)"))
    return engine


class _PermissaoNegada(Exception):
    sqlstate = "42501"


def test_quatro_tabelas_fiscais_acessiveis_updater_negado_gera_info(capsys):
    engine = _engine_fiscal_com_updater_sintetico()
    comandos = []

    def negar_updater(_conexao, _cursor, sql, _params, _contexto, _many):
        comandos.append(sql)
        if "FROM regras_consolidadas" in sql:
            raise OperationalError(sql, {}, _PermissaoNegada())

    event.listen(engine, "before_cursor_execute", negar_updater)
    repo = PostgresRepository("postgresql+psycopg://teste:teste@localhost/teste", engine=engine)
    base, updater = cli.carregar_postgres_somente_leitura(repo)
    assert len(base.ncm) == 1 and len(base.aliquotas) == len(base.beneficios) == len(base.legislacao) == 0
    assert updater[ADMINISTRATIVO_NAO_VERIFICADO][0] == {
        "tabela": "regras_consolidadas", "causa": "permissão SELECT negada (SQLSTATE 42501)"}
    relatorio = auditar_integridade(base, updater=updater)
    assert relatorio.contagem_niveis() == {"ERRO": 0, "ALERTA": 0, "INFO": 1}
    assert relatorio.contagem_codigos() == {"RASTREABILIDADE_ADMINISTRATIVA_NAO_VERIFICADA": 1}
    cli.mostrar_relatorio(relatorio)
    saida = capsys.readouterr().out
    assert "A credencial utilizada não possui acesso às estruturas administrativas" in saida
    assert "regras_consolidadas (permissão SELECT negada" in saida
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE"))
                   for sql in comandos)


def test_updater_sem_acesso_nao_gera_alerta_por_regra_com_vinculo():
    base = _base()
    base.aliquotas.loc[0, "regra_consolidada_id"] = 10
    updater = {ADMINISTRATIVO_NAO_VERIFICADO: [{"tabela": "regras_consolidadas", "causa": "SELECT não permitido"}]}
    relatorio = auditar_integridade(base, referencia=REFERENCIA, updater=updater)
    assert relatorio.contagem_niveis() == {"ERRO": 0, "ALERTA": 0, "INFO": 1}
    assert "RASTREABILIDADE_NAO_VERIFICAVEL" not in relatorio.contagem_codigos()


def test_select_negado_em_tabela_fiscal_e_erro_identificado(monkeypatch, capsys):
    engine = _engine_fiscal_com_updater_sintetico()

    def negar_ncm(_conexao, _cursor, sql, _params, _contexto, _many):
        if "FROM ncm" in sql:
            raise OperationalError(sql, {}, _PermissaoNegada())

    event.listen(engine, "before_cursor_execute", negar_ncm)
    repo = PostgresRepository("postgresql+psycopg://teste:teste@localhost/teste", engine=engine)
    with pytest.raises(cli.ErroLeituraFiscal, match="ncm.*42501"):
        cli.carregar_postgres_somente_leitura(repo)
    monkeypatch.setattr(cli, "criar_repositorio", lambda: repo)
    monkeypatch.setattr("sys.argv", ["auditar_integridade"])
    assert cli.main() == 2
    saida = capsys.readouterr().out
    assert "tabela fiscal obrigatória ncm" in saida and "SQLSTATE 42501" in saida
    assert "verifique conexão e schema" not in saida

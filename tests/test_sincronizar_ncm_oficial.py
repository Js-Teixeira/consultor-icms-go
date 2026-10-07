"""Sincronização da NCM oficial com fonte e banco inteiramente simulados."""

import json
import hashlib

import httpx
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError

import scripts.sincronizar_ncm_oficial as modulo
from scripts.sincronizar_ncm_oficial import (
    ErroSincronizacao, baixar_json, campos_diferentes, extrair_ncms, planejar, sincronizar,
)
from src.dados import criar_repositorio
from src.dados.postgres_repository import PostgresRepository
from src.dados.schema import aliquotas, beneficios, legislacao, metadata, ncm


def _documento(*itens):
    return {"Nomenclaturas": list(itens)}


def _item(codigo="1006.30.21", descricao="Polido ou brunido"):
    return {"Codigo": codigo, "Descricao": descricao}


def _item_real(codigo, descricao):
    return {"Codigo": codigo, "Descricao": descricao, "Data_Inicio": "01/04/2022",
            "Data_Fim": "31/12/9999", "Tipo_Ato_Ini": "Res Gecex",
            "Numero_Ato_Ini": "272", "Ano_Ato_Ini": "2021"}


@pytest.fixture
def documento_hierarquico():
    """Recorte sintético com as mesmas chaves e profundidades observadas no Classif."""
    return _documento(*[_item_real(*linha) for linha in (
        ("02.01", "Carnes de animais da espécie bovina, frescas ou refrigeradas."),
        ("0201.30.00", "- Desossadas"),
        ("07.13", "Legumes de vagem, secos, em grão."),
        ("0713.3", "- Feijões:"),
        ("0713.33", "-- Feijão comum (<i>Phaseolus vulgaris</i>)"),
        ("0713.33.1", "Preto"),
        ("0713.33.19", "Outros"),
        ("09.01", "Café, mesmo torrado ou descafeinado."),
        ("0901.2", "- Café torrado:"),
        ("0901.21.00", "-- Não descafeinado"),
        ("10.06", "Arroz."),
        ("1006.30", "- Arroz semibranqueado ou branqueado, mesmo polido ou brunido (glaciado*)"),
        ("1006.30.2", "Não parboilizado"),
        ("1006.30.21", "Polido ou brunido"),
        ("19.02", "Massas alimentícias, mesmo cozidas ou recheadas."),
        ("1902.1", "- Massas alimentícias não cozidas, nem recheadas, nem preparadas de outro modo:"),
        ("1902.11.00", "-- Que contenham ovos"),
        ("1902.19.00", "-- Outras"),
        ("04.01", "Leite e creme de leite (nata), não concentrados."),
        ("0401.20", "- Com um teor, em peso, de matérias gordas, superior a 1 %, mas não superior a 6 %"),
        ("0401.20.10", "Leite UHT (<i>Ultra High Temperature</i>)"),
    )])


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return engine


def _oficiais(*itens):
    return extrair_ncms(_documento(*itens))[0]


@pytest.fixture(autouse=True)
def permitir_fonte_pequena_simulada(monkeypatch):
    monkeypatch.setattr(modulo, "MIN_NCMS_CACHE", 1)


def test_codigos_finais_pontuados_e_sem_pontuacao_e_hierarquia():
    oficiais, contagem = extrair_ncms(_documento(
        _item("1006.30.21", "  Polido   ou brunido  "),
        _item("10063021", "Polido ou brunido"),
        _item("10", "Capítulo"), _item("1006", "Posição"),
        _item("100630", "Subposição"),
    ))
    assert list(oficiais) == ["10063021"]
    assert oficiais["10063021"] == {
        "ncm": "10063021", "descricao_oficial": "Polido ou brunido",
        "capitulo": "10", "posicao": "1006", "subposicao": "100630", "ativo": "SIM",
    }
    assert contagem.invalidos == 3
    assert contagem.duplicidades == 1


def test_descricoes_hierarquicas_de_recorte_com_estrutura_real(documento_hierarquico):
    oficiais, _ = extrair_ncms(documento_hierarquico)
    assert oficiais["02013000"]["descricao_oficial"] == (
        "Carnes de animais da espécie bovina, frescas ou refrigeradas — Desossadas")
    assert oficiais["07133319"]["descricao_oficial"] == "Feijão comum (Phaseolus vulgaris) — Preto — Outros"
    assert oficiais["09012100"]["descricao_oficial"] == "Café torrado — Não descafeinado"
    assert oficiais["10063021"]["descricao_oficial"] == (
        "Arroz semibranqueado ou branqueado — Não parboilizado — Polido ou brunido (glaciado*)")
    assert oficiais["19021100"]["descricao_oficial"] == (
        "Massas alimentícias não cozidas, nem recheadas, nem preparadas de outro modo — Que contenham ovos")
    assert oficiais["19021900"]["descricao_oficial"] == (
        "Massas alimentícias não cozidas, nem recheadas, nem preparadas de outro modo — Outras")
    assert oficiais["04012010"]["descricao_oficial"] == (
        "Leite e creme de leite (nata), não concentrados — Com um teor, em peso, de matérias gordas, "
        "superior a 1 %, mas não superior a 6 % — Leite UHT (Ultra High Temperature)")
    assert all("<" not in r["descricao_oficial"] and not r["descricao_oficial"].startswith("-")
               for r in oficiais.values())


def test_sobreposicao_textual_nao_repete_ancestrais():
    oficiais = _oficiais(_item("02.01", "Carnes"),
                         _item("0201.30", "- Carnes desossadas"),
                         _item("0201.30.00", "Desossadas"))
    assert oficiais["02013000"]["descricao_oficial"] == "Carnes desossadas"


@pytest.mark.parametrize("itens", [
    [_item("1006.30.21", "Polido"), _item("10063021", "Brunido")],
    [_item("1006.30.21", "Polido"), _item("10063021", "Outro")],
])
def test_duplicidade_conflitante_aborta(itens):
    with pytest.raises(ErroSincronizacao, match="descrições oficiais divergentes"):
        extrair_ncms(_documento(*itens))


@pytest.mark.parametrize("documento", [
    {}, {"Nomenclaturas": []}, {"Nomenclaturas": [_item("10", "Capítulo")]},
    {"Nomenclaturas": [_item(descricao=" ")]},
])
def test_fonte_invalida_ou_sem_ncm_final_aborta(documento):
    with pytest.raises(ErroSincronizacao):
        extrair_ncms(documento)


@pytest.mark.parametrize("status", [404, 500])
def test_download_http_erro(status):
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(status, request=pedido))
    with httpx.Client(transport=transporte) as cliente:
        with pytest.raises(ErroSincronizacao, match=f"HTTP {status}"):
            baixar_json(cliente)


def test_download_timeout():
    def falhar(_pedido):
        raise httpx.ReadTimeout("simulado")

    with httpx.Client(transport=httpx.MockTransport(falhar)) as cliente:
        with pytest.raises(ErroSincronizacao, match="Tempo esgotado"):
            baixar_json(cliente)


def test_download_json_invalido():
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(200, text="{", request=pedido))
    with httpx.Client(transport=transporte) as cliente:
        with pytest.raises(ErroSincronizacao, match="JSON inválido"):
            baixar_json(cliente)


def test_download_json_valido_com_mock():
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(200, json=_documento(_item()), request=pedido))
    with httpx.Client(transport=transporte) as cliente:
        assert baixar_json(cliente)["Nomenclaturas"][0]["Codigo"] == "1006.30.21"


def test_download_limite_de_acessos_informa_causa():
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(
        422, json={"message": "Foi atingido o limite de 3 acessos permitidos à funcionalidade em uma hora."}, request=pedido,
    ))
    with httpx.Client(transport=transporte) as cliente:
        with pytest.raises(ErroSincronizacao, match="limitou temporariamente"):
            baixar_json(cliente)


def test_plano_novo_igual_atualizar_descricao_e_hierarquia():
    oficiais = _oficiais(_item("1006.30.21", "Polido ou brunido"), _item("0101.21.00", "Reprodutores"))
    atual = {"ncm": "10063021", "descricao_oficial": "Polido ou brunido",
             "capitulo": "10", "posicao": "1006", "subposicao": "100630", "ativo": "SIM"}
    plano = planejar(oficiais, {"10063021": atual})
    assert len(plano.inserir) == 1 and plano.inserir[0]["ncm"] == "01012100"
    assert plano.iguais == 1 and not plano.atualizar

    plano = planejar(oficiais, {"10063021": {**atual, "descricao_oficial": "Antiga"}})
    assert len(plano.atualizar) == 1 and plano.atualizar[0][1]["descricao_oficial"] == "Polido ou brunido"
    plano = planejar(oficiais, {"10063021": {**atual, "subposicao": "000000"}})
    assert len(plano.atualizar) == 1
    assert campos_diferentes({**atual, "subposicao": "000000"}, oficiais["10063021"]) == ["subposicao"]


def test_comparacao_normaliza_so_espacos_e_ativo_diferente_atualiza():
    oficial = _oficiais(_item())["10063021"]
    atual = {**oficial, "descricao_oficial": " Polido   ou brunido ", "observacao": "Livre"}
    assert not campos_diferentes(atual, oficial)
    assert planejar({oficial["ncm"]: oficial}, {oficial["ncm"]: atual}).iguais == 1
    alterado = {**atual, "ativo": "NAO"}
    plano = planejar({oficial["ncm"]: oficial}, {oficial["ncm"]: alterado})
    assert len(plano.atualizar) == 1
    assert campos_diferentes(alterado, oficial) == ["ativo"]


def test_banco_vazio_e_contagem_soma_e_codigo_somente_no_banco():
    oficiais = _oficiais(_item(), _item("0101.21.00", "Reprodutores"))
    vazio = sincronizar(_engine(), oficiais, dry_run=True)
    assert vazio.registros_atuais == 0 and len(vazio.inserir) == 2
    assert vazio.iguais == 0 and not vazio.atualizar and not vazio.somente_no_banco
    plano = planejar(oficiais, {
        "10063021": {**oficiais["10063021"], "ativo": "NAO"},
        "99999999": {"ncm": "99999999", "descricao_oficial": "Legado"},
    })
    assert len(plano.inserir) + plano.iguais + len(plano.atualizar) == len(oficiais)
    assert plano.registros_atuais == 2 and plano.somente_no_banco == ["99999999"]


def test_dry_run_nao_grava_nada():
    engine = _engine()
    with engine.begin() as conexao:
        conexao.execute(ncm.insert().values(ncm="10063021", descricao_oficial="Antiga", capitulo="10",
                                          posicao="1006", subposicao="100630", ativo="NAO", observacao="Manter"))
    comandos_dml = []

    def registrar(_conexao, _cursor, comando, _parametros, _contexto, _multiplos):
        if comando.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            comandos_dml.append(comando)

    event.listen(engine, "before_cursor_execute", registrar)
    plano = sincronizar(engine, _oficiais(_item(), _item("0101.21.00", "Reprodutores")), dry_run=True)
    assert len(plano.inserir) == 1 and len(plano.atualizar) == 1
    assert comandos_dml == []
    with engine.connect() as conexao:
        linhas = conexao.execute(select(ncm)).mappings().all()
    assert len(linhas) == 1 and linhas[0]["descricao_oficial"] == "Antiga"
    assert linhas[0]["ativo"] == "NAO" and linhas[0]["observacao"] == "Manter"


def test_escrita_so_toca_ncm_e_preserva_existentes_ausentes_da_fonte():
    engine = _engine()
    with engine.begin() as conexao:
        conexao.execute(ncm.insert().values(ncm="10063021", descricao_oficial="Antiga", capitulo="10",
                                          posicao="1006", subposicao="100630", ativo="NAO", observacao="Manter"))
        conexao.execute(ncm.insert().values(ncm="99999999", descricao_oficial="Legado sintético", ativo="SIM"))
        conexao.execute(legislacao.insert().values(id_legislacao="L1", ativo="SIM"))
        conexao.execute(aliquotas.insert().values(id_regra="R1", chave_ncm="10063021",
                                                  tipo_correspondencia="EXATO", ativo="SIM", exige_descricao="NAO"))
        conexao.execute(beneficios.insert().values(id_beneficio="B1", chave_ncm="10063021",
                                                    tipo_correspondencia="EXATO", ativo="SIM", exige_descricao="NAO"))
    plano = sincronizar(engine, _oficiais(_item(), _item("0101.21.00", "Reprodutores")), dry_run=False)
    assert len(plano.inserir) == 1 and len(plano.atualizar) == 1
    with engine.connect() as conexao:
        linhas = {r["ncm"]: r for r in conexao.execute(select(ncm)).mappings()}
        assert linhas["10063021"]["descricao_oficial"] == "Polido ou brunido"
        assert linhas["10063021"]["ativo"] == "SIM" and linhas["10063021"]["observacao"] == "Manter"
        assert linhas["01012100"]["ativo"] == "SIM" and "99999999" in linhas
        assert conexao.execute(select(aliquotas.c.id_regra)).scalar_one() == "R1"
        assert conexao.execute(select(beneficios.c.id_beneficio)).scalar_one() == "B1"
        assert conexao.execute(select(legislacao.c.id_legislacao)).scalar_one() == "L1"


def test_erro_em_atualizacao_reverte_insercao_anterior():
    engine = _engine()
    with engine.begin() as conexao:
        conexao.execute(ncm.insert().values(ncm="10063021", descricao_oficial="Antiga", ativo="SIM"))
        conexao.execute(text("CREATE TRIGGER bloquear_atualizacao BEFORE UPDATE ON ncm "
                            "BEGIN SELECT RAISE(ABORT, 'falha simulada'); END"))
    with pytest.raises(IntegrityError):
        sincronizar(engine, _oficiais(_item(), _item("0101.21.00", "Reprodutores")), dry_run=False)
    with engine.connect() as conexao:
        linhas = conexao.execute(select(ncm)).mappings().all()
    assert len(linhas) == 1 and linhas[0]["descricao_oficial"] == "Antiga"


def test_postgres_configurado_usa_engine_para_ler_so_ncm():
    engine = _engine()
    repo = criar_repositorio(data_source="postgres", database_url="postgresql+psycopg://teste:teste@localhost/teste", engine=engine)
    assert isinstance(repo, PostgresRepository)
    consultas = []

    def registrar(_conexao, _cursor, comando, _parametros, _contexto, _multiplos):
        consultas.append(comando)

    event.listen(engine, "before_cursor_execute", registrar)
    sincronizar(repo.engine, _oficiais(_item()), dry_run=True)
    assert len(consultas) == 1
    assert "FROM ncm" in consultas[0]
    assert all(nome not in consultas[0] for nome in ("aliquotas", "beneficios", "legislacao"))


def test_cli_sem_database_url_falha_claramente_sem_comparacao(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    def download_indevido(_cliente):
        pytest.fail("Configuração ausente não deve consumir download oficial")

    monkeypatch.setattr(modulo, "baixar_json", download_indevido)
    monkeypatch.setattr("sys.argv", ["sincronizar_ncm_oficial", "--dry-run"])
    assert modulo.main() == 1
    saida = capsys.readouterr().out
    assert "Não foi possível comparar com PostgreSQL: DATABASE_URL não configurada." in saida
    assert "Inserir:" not in saida and "DRY-RUN: nenhuma escrita realizada." not in saida


def test_cli_falha_conexao_expoe_tipo_do_erro_sem_resultado_falso(monkeypatch, tmp_path, capsys):
    engine = create_engine("sqlite+pysqlite:///:memory:")  # tabela ncm ausente de propósito
    monkeypatch.setattr(modulo, "CAMINHO_CACHE", tmp_path / "cache_ncm_oficial.json")
    monkeypatch.setattr(modulo, "baixar_json", lambda _cliente: _documento(_item()))
    monkeypatch.setattr(modulo, "criar_repositorio", lambda **_kwargs: type("Repo", (), {"engine": engine})())
    monkeypatch.setattr("sys.argv", ["sincronizar_ncm_oficial", "--dry-run"])
    assert modulo.main() == 1
    saida = capsys.readouterr().out
    assert "OperationalError" in saida
    assert "Inserir:" not in saida


def test_cache_criado_apos_download_oficial_valido(tmp_path):
    caminho = tmp_path / "cache_ncm_oficial.json"
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(
        200, json=_documento(_item()), request=pedido,
    ))
    with httpx.Client(transport=transporte) as cliente:
        metadados = modulo.salvar_cache(baixar_json(cliente), caminho)
    oficiais, _, lidos = modulo.carregar_cache(caminho)
    assert list(oficiais) == ["10063021"]
    assert lidos == metadados
    assert lidos["url_origem"] == modulo.URL_CLASSIF
    assert lidos["ncms_finais"] == 1
    assert lidos["versao_cache"] == 2
    assert lidos["quantidade_recebida"] == 1
    assert len(lidos["sha256"]) == 64
    assert not caminho.with_name(caminho.name + ".tmp").exists()


def test_paridade_http_e_cache_com_mesma_resposta_bruta(documento_hierarquico, tmp_path):
    caminho = tmp_path / "cache.json"
    transporte = httpx.MockTransport(lambda pedido: httpx.Response(
        200, json=documento_hierarquico, request=pedido))
    with httpx.Client(transport=transporte) as cliente:
        baixado = baixar_json(cliente)
    via_http, estatisticas_http = extrair_ncms(baixado)
    modulo.salvar_cache(baixado, caminho)
    via_cache, estatisticas_cache, metadados = modulo.carregar_cache(caminho)
    assert via_http == via_cache
    assert estatisticas_http == estatisticas_cache
    assert metadados["quantidade_recebida"] == len(documento_hierarquico["Nomenclaturas"])
    assert json.loads(caminho.read_text(encoding="utf-8"))["documento"] == documento_hierarquico


def test_cache_legado_bruto_com_ancestrais_pode_ser_reprocessado(documento_hierarquico, tmp_path):
    caminho = tmp_path / "cache_legado.json"
    oficiais, _ = extrair_ncms(documento_hierarquico)
    caminho.write_text(json.dumps({"metadados": {
        "url_origem": modulo.URL_CLASSIF, "download_em": "2026-10-04T12:00:00+00:00",
        "ncms_finais": len(oficiais),
        "sha256": hashlib.sha256(modulo._conteudo_normalizado(documento_hierarquico)).hexdigest(),
    }, "documento": documento_hierarquico}), encoding="utf-8")
    lidos, _, metadados = modulo.carregar_cache(caminho)
    assert lidos == oficiais
    assert "versao_cache" not in metadados


def test_cache_antigo_so_com_folhas_e_rejeitado_sem_apagar(tmp_path):
    caminho = tmp_path / "cache_antigo.json"
    documento = _documento(*(_item(f"{indice:08d}", "Outros") for indice in range(10000)))
    caminho.write_text(json.dumps({"metadados": {
        "url_origem": modulo.URL_CLASSIF, "download_em": "2026-10-04T12:00:00+00:00",
        "ncms_finais": 10000,
        "sha256": hashlib.sha256(modulo._conteudo_normalizado(documento)).hexdigest(),
    }, "documento": documento}), encoding="utf-8")
    anterior = caminho.read_bytes()
    with pytest.raises(ErroSincronizacao, match="Cache NCM antigo não contém hierarquia suficiente"):
        modulo.carregar_cache(caminho)
    assert caminho.read_bytes() == anterior


def test_novo_download_preserva_cache_invalido_anterior_para_auditoria(tmp_path):
    caminho = tmp_path / "cache.json"
    caminho.write_text("{", encoding="utf-8")
    modulo.salvar_cache(_documento(_item()), caminho)
    assert caminho.with_name("cache.json.legacy").read_text(encoding="utf-8") == "{"
    assert modulo.carregar_cache(caminho)[2]["versao_cache"] == 2


@pytest.mark.parametrize("resposta", [
    httpx.Response(500), httpx.Response(200, text="{"),
    httpx.Response(200, json=_documento()),
    httpx.Response(200, json=_documento(_item(descricao=" "))),
    httpx.Response(200, json=_documento(_item(), _item(descricao="Divergente"))),
    httpx.Response(200, json={"outra_chave": []}),
])
def test_download_invalido_nao_substitui_cache(tmp_path, resposta):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item()), caminho)
    anterior = caminho.read_bytes()
    with httpx.Client(transport=httpx.MockTransport(lambda pedido: httpx.Response(
        resposta.status_code, content=resposta.content, request=pedido,
    ))) as cliente:
        with pytest.raises(ErroSincronizacao):
            modulo.salvar_cache(baixar_json(cliente), caminho)
    assert caminho.read_bytes() == anterior


def test_cache_invalido_e_hash_divergente_rejeitados(tmp_path):
    caminho = tmp_path / "cache_ncm_oficial.json"
    caminho.write_text("{", encoding="utf-8")
    with pytest.raises(ErroSincronizacao, match="Cache oficial local inválido"):
        modulo.carregar_cache(caminho)
    modulo.salvar_cache(_documento(_item()), caminho)
    cache = json.loads(caminho.read_text(encoding="utf-8"))
    cache["documento"]["Nomenclaturas"][0]["Descricao"] = "Alterado"
    caminho.write_text(json.dumps(cache), encoding="utf-8")
    with pytest.raises(ErroSincronizacao, match="SHA-256 divergente"):
        modulo.carregar_cache(caminho)


def test_cache_revalida_conteudo_e_contagem_mesmo_com_hash_recalculado(tmp_path):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item()), caminho)
    cache = json.loads(caminho.read_text(encoding="utf-8"))
    cache["metadados"]["ncms_finais"] = 2
    caminho.write_text(json.dumps(cache), encoding="utf-8")
    with pytest.raises(ErroSincronizacao, match="contagem divergente"):
        modulo.carregar_cache(caminho)


def test_download_possivelmente_incompleto_nao_substitui_cache(tmp_path, monkeypatch):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item()), caminho)
    anterior = caminho.read_bytes()
    monkeypatch.setattr(modulo, "MIN_NCMS_CACHE", 10000)
    with pytest.raises(ErroSincronizacao, match="possivelmente incompleto"):
        modulo.salvar_cache(_documento(_item()), caminho)
    assert caminho.read_bytes() == anterior


def test_download_com_menos_ncms_que_cache_valido_nao_substitui(tmp_path):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item(), _item("0101.21.00", "Reprodutores")), caminho)
    anterior = caminho.read_bytes()
    with pytest.raises(ErroSincronizacao, match="contra 2 no cache válido"):
        modulo.salvar_cache(_documento(_item()), caminho)
    assert caminho.read_bytes() == anterior


def test_falha_na_substituicao_atomica_preserva_cache(tmp_path, monkeypatch):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item()), caminho)
    anterior = caminho.read_bytes()

    def falhar_replace(_origem, _destino):
        raise OSError("falha simulada")

    monkeypatch.setattr(modulo.os, "replace", falhar_replace)
    with pytest.raises(ErroSincronizacao, match="Não foi possível gravar"):
        modulo.salvar_cache(_documento(_item(descricao="Nova descrição")), caminho)
    assert caminho.read_bytes() == anterior
    assert not caminho.with_name(caminho.name + ".tmp").exists()


def test_usar_cache_compara_banco_sem_http_ou_escrita(monkeypatch, tmp_path, capsys):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item(), _item("0101.21.00", "Reprodutores")), caminho)
    engine = _engine()
    with engine.begin() as conexao:
        conexao.execute(ncm.insert().values(ncm="10063021", descricao_oficial="Antiga", ativo="SIM"))
        conexao.execute(ncm.insert().values(ncm="99999999", descricao_oficial="Legado", ativo="SIM"))
    comandos_dml = []

    def registrar(_conexao, _cursor, comando, _parametros, _contexto, _multiplos):
        if comando.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            comandos_dml.append(comando)

    event.listen(engine, "before_cursor_execute", registrar)
    monkeypatch.setattr(modulo, "CAMINHO_CACHE", caminho)
    monkeypatch.setattr(modulo, "criar_repositorio", lambda **_kwargs: type("Repo", (), {"engine": engine})())
    monkeypatch.setattr(modulo.httpx, "Client", lambda **_kwargs: pytest.fail("--usar-cache não pode fazer HTTP"))
    monkeypatch.setattr("sys.argv", ["sincronizar_ncm_oficial", "--dry-run", "--usar-cache"])
    assert modulo.main() == 0
    saida = capsys.readouterr().out
    assert "Fonte: cache de download oficial" in saida
    assert "Data do download:" in saida and "SHA-256:" in saida
    assert "Registros atuais: 2" in saida
    assert "Inserir: 1" in saida and "Iguais: 0" in saida
    assert "Atualizar: 1" in saida and "Somente no banco: 1" in saida
    assert "DRY-RUN: nenhuma escrita realizada." in saida
    assert comandos_dml == []
    with engine.connect() as conexao:
        assert conexao.execute(select(ncm.c.descricao_oficial).where(ncm.c.ncm == "10063021")).scalar_one() == "Antiga"


def test_usar_cache_ausente_falha_claramente_sem_http(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(modulo, "CAMINHO_CACHE", tmp_path / "inexistente.json")
    monkeypatch.setattr(modulo.httpx, "Client", lambda **_kwargs: pytest.fail("HTTP indevido"))
    monkeypatch.setattr("sys.argv", ["sincronizar_ncm_oficial", "--dry-run", "--usar-cache"])
    assert modulo.main() == 1
    assert "Cache oficial local não encontrado" in capsys.readouterr().out


def test_fonte_indisponivel_nao_usa_cache_implicitamente(monkeypatch, tmp_path, capsys):
    caminho = tmp_path / "cache_ncm_oficial.json"
    modulo.salvar_cache(_documento(_item()), caminho)
    engine = _engine()
    monkeypatch.setattr(modulo, "CAMINHO_CACHE", caminho)
    monkeypatch.setattr(modulo, "criar_repositorio", lambda **_kwargs: type("Repo", (), {"engine": engine})())
    monkeypatch.setattr(modulo, "baixar_json", lambda _cliente: (_ for _ in ()).throw(
        ErroSincronizacao("Tempo esgotado ao baixar a NCM oficial.")))
    monkeypatch.setattr(modulo, "sincronizar", lambda *_args, **_kwargs: pytest.fail("Cache usado sem permissão"))
    monkeypatch.setattr("sys.argv", ["sincronizar_ncm_oficial", "--dry-run"])
    assert modulo.main() == 1
    saida = capsys.readouterr().out
    assert "Fonte oficial indisponível. Existe cache oficial local de" in saida
    assert "Use --usar-cache explicitamente" in saida
    assert "Tempo esgotado" in saida

"""Regressões novas da recuperação parcial; dados fictícios, sem valor fiscal.

Não são a suíte histórica 2.5.4. Os testes de seleção adaptam a intenção do
diff recuperado à base disponível, usando somente SQLite em memória.
"""

from datetime import date

import pytest
from sqlalchemy import event, select, update

from src.dados.schema import metadata as metadata_fiscal
from tests.test_consolidador import inserir_extraida
from tests.test_extrator import inserir_ato, repo_sqlite
from updater.consolidacao import planejar_regra
from updater.extracao_fiscal import EXTRACTOR_VERSION, extrair_regras
from updater.normalizacao import limpar_html
from updater.propostas_publicacao import simular_publicacao
from updater.repositorio_consolidacao import RepositorioConsolidacao
from updater.schema import (
    atos_legislativos, evidencias_extracao, metadata, processamentos_extracao,
    regras_consolidadas, regras_extraidas,
)


def test_remissao_expressa_prevalece_sobre_beneficio_mais_proximo():
    texto = (
        "Art. 1º Fica isento do ICMS o produto fictício alfa.\n"
        "Art. 2º Fica isento do ICMS o produto fictício beta.\n"
        "Art. 3º Deve celebrar termo de acordo para o benefício previsto no art. 1º deste ato."
    )
    alfa, beta, condicao = extrair_regras(texto)
    assert alfa.grupo_regra_id and alfa.grupo_regra_id != beta.grupo_regra_id
    assert condicao.grupo_regra_id == alfa.grupo_regra_id
    assert all(r.elegivel_consulta_ncm == "NAO" for r in (alfa, beta, condicao))


def test_condicao_ambigua_nao_e_associada_por_proximidade():
    regras = extrair_regras(
        "Art. 1º Fica isento do ICMS o NCM 1234.56.78.\n"
        "Art. 2º Deve celebrar termo de acordo para utilizar a isenção."
    )
    principal, condicao = regras
    assert condicao.grupo_regra_id is None
    assert principal.elegivel_consulta_ncm == "NAO"
    assert all(r.status_revisao == "PENDENTE" for r in regras)
    assert any(e.tipo_evidencia == "PENDENCIA_ASSOCIACAO" for e in principal.evidencias)


def test_duas_mercadorias_no_mesmo_artigo_nao_disputam_condicao():
    regras = extrair_regras(
        "Art. 1º\n"
        "Fica isento do ICMS o produto fictício alfa.\n"
        "Fica isento do ICMS o produto fictício beta.\n"
        "Deve celebrar termo de acordo para utilizar a isenção."
    )
    alfa, beta, condicao = regras
    assert alfa.grupo_regra_id and alfa.grupo_regra_id != beta.grupo_regra_id
    assert condicao.grupo_regra_id is None
    assert all(r.elegivel_consulta_ncm == "NAO" for r in regras)


def test_itcd_nao_contamina_icms_explicito_em_artigo_independente():
    regras = extrair_regras(
        "CAPÍTULO I\nDO ITCD\nArt. 1º Alíquota de 4% para a hipótese fictícia.\n"
        "Art. 2º Alíquota do ICMS de 19% para o NCM 1234.56.78."
    )
    historica = next(r for r in regras if r.artigo == "1")
    icms = next(r for r in regras if r.artigo == "2" and r.papel_dispositivo == "REGRA_MATERIAL")
    assert historica.aliquota_icms is None and historica.elegivel_consolidacao == "NAO"
    assert not any(e.tipo_evidencia == "ALIQUOTA" for e in historica.evidencias)
    assert str(icms.aliquota_icms) == "19" and icms.elegivel_consolidacao == "SIM"


@pytest.mark.parametrize("texto", [
    "Art. 1º Não se aplica a redução de 50% da base de cálculo do ICMS ao NCM 1234.56.78.",
    "Art. 1º É vedada a concessão de crédito outorgado de 5% ao NCM 1234.56.78.",
])
def test_restricao_nao_e_concessao_nem_revogacao(texto):
    regra, = extrair_regras(texto)
    assert regra.papel_dispositivo in {"VEDACAO", "EXCECAO"}
    assert regra.acao_legislativa != "REVOGA"
    assert regra.elegivel_consolidacao == regra.elegivel_consulta_ncm == "NAO"
    assert regra.status_revisao == "PENDENTE" and regra.evidencias


def test_concessao_com_excecao_preserva_condicao():
    regra, = extrair_regras(
        "Art. 1º Fica isento do ICMS o produto fictício alfa, exceto quando destinado à revenda."
    )
    assert regra.papel_dispositivo == "REGRA_MATERIAL"
    assert "exceto quando destinado à revenda" in regra.condicoes_texto
    assert regra.elegivel_consolidacao == "SIM" and regra.elegivel_consulta_ncm == "NAO"


def test_nota_inaplicavel_nao_bloqueia_artigo_seguinte():
    html = (
        '<p>NOTA: sem aplicabilidade por decurso de prazo.</p>'
        '<p>Alíquota do ICMS de 12% para o NCM 1234.56.78.</p>'
        '<p>Art. 2º Alíquota do ICMS de 19% para o NCM 2202.10.00.</p>'
    )
    texto = limpar_html(html)
    regras = extrair_regras(texto, html)
    antiga = next(r for r in regras if "12%" in r.trecho_origem)
    atual = next(r for r in regras if "19%" in r.trecho_origem)
    assert antiga.elegivel_consolidacao == antiga.elegivel_consulta_ncm == "NAO"
    assert atual.elegivel_consolidacao == "SIM"
    assert all(r.status_revisao == "PENDENTE" for r in regras)


@pytest.mark.parametrize("data", ["31/02/2026", "03.07.26"])
def test_data_invalida_ou_ano_abreviado_nao_autoriza_consulta(data):
    regra, = extrair_regras(
        f"Art. 1º Fica isento do ICMS o NCM 1234.56.78; produz efeitos a partir de {data}."
    )
    assert regra.vigencia_inicio is None and regra.elegivel_consulta_ncm == "NAO"
    assert any(e.tipo_evidencia == "PENDENCIA_TEMPORAL" for e in regra.evidencias)


@pytest.mark.parametrize("ordem", [
    ("2.5.0", "2.5.1", "2.5.2", "2.5.3", "RECOVERY"),
    ("RECOVERY", "2.5.3", "2.5.0", "2.5.2", "2.5.1"),
])
def test_selecao_nao_duplica_regra_e_preserva_historico(repo_sqlite, ordem):
    assert EXTRACTOR_VERSION != "2.5.0"
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    anteriores, provas_anteriores = [], []
    for versao in ordem:
        versao = EXTRACTOR_VERSION if versao == "RECOVERY" else versao
        repo_sqlite.salvar(ato, extrair_regras(texto), versao)
        with repo_sqlite.engine.connect() as conexao:
            historico = [dict(r) for r in conexao.execute(select(regras_extraidas).order_by(regras_extraidas.c.id)).mappings()]
            provas = [dict(e) for e in conexao.execute(select(evidencias_extracao).order_by(evidencias_extracao.c.id)).mappings()]
        assert historico[:len(anteriores)] == anteriores
        assert provas[:len(provas_anteriores)] == provas_anteriores
        anteriores, provas_anteriores = historico, provas
    fonte, = RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas()
    assert fonte["extrator_versao"] == EXTRACTOR_VERSION
    assert len(anteriores) == 5 and all(r["status_revisao"] == "PENDENTE" for r in anteriores)


def test_nova_extracao_bloqueada_nao_restaura_regra_antiga(repo_sqlite):
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    repo_sqlite.salvar(ato, extrair_regras(texto), "2.5.0")
    nova = extrair_regras(texto)
    nova[0].elegivel_consolidacao = nova[0].elegivel_consulta_ncm = "NAO"
    repo_sqlite.salvar(ato, nova, "2.5.4-recovery.1")
    assert RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas() == []
    with repo_sqlite.engine.connect() as conexao:
        historico = list(conexao.execute(select(regras_extraidas)).mappings())
    assert len(historico) == 2 and all(r["status_revisao"] == "PENDENTE" for r in historico)


@pytest.mark.parametrize("status", ["PENDENTE", "FALHOU"])
def test_extracao_nova_incompleta_bloqueia_selecao_sem_apagar_historico(repo_sqlite, status):
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    for versao in ("2.5.0", EXTRACTOR_VERSION):
        repo_sqlite.salvar(ato, extrair_regras(texto), versao)
    with repo_sqlite.engine.begin() as conexao:
        antes = [dict(r) for r in conexao.execute(select(regras_extraidas)).mappings()]
        conexao.execute(update(processamentos_extracao).where(
            processamentos_extracao.c.extrator_versao == EXTRACTOR_VERSION,
        ).values(status=status))
    assert RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas() == []
    with repo_sqlite.engine.connect() as conexao:
        depois = [dict(r) for r in conexao.execute(select(regras_extraidas)).mappings()]
    assert antes == depois and len(depois) == 2


def test_referencia_sem_anexo_nao_vincula_beneficio_de_outro_anexo():
    html = (
        '<h2>ANEXO IX</h2><p>Art. 1º Fica isento do ICMS o NCM 1234.56.78.</p>'
        '<h2>ANEXO X</h2><p>Art. 3º Deve celebrar termo de acordo para o benefício '
        'previsto no art. 1º deste ato.</p>'
    )
    principal, condicao = extrair_regras(limpar_html(html), html)
    assert condicao.grupo_regra_id is None
    assert principal.elegivel_consulta_ncm == "SIM"
    assert condicao.anexo == "X" and principal.anexo == "IX"


def test_html_sem_correspondencia_com_texto_mantem_candidata_pendente():
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    regra, = extrair_regras(texto, '<p>Art. 2º Texto diferente.</p>')
    assert regra.elegivel_consulta_ncm == "NAO" and regra.status_revisao == "PENDENTE"
    assert any(e.tipo_evidencia == "PENDENCIA_ASSOCIACAO" for e in regra.evidencias)


def test_prazo_para_apresentacao_de_requerimento_nao_encerra_beneficio():
    regra, = extrair_regras(
        "Art. 1º Fica isento do ICMS o produto fictício alfa; "
        "produz efeitos a partir de 1 de janeiro de 2026; "
        "o prazo para apresentação do requerimento vai até 31 de dezembro de 2026."
    )
    assert regra.vigencia_fim is None
    assert any(e.tipo_evidencia == "PRAZO_OPERACIONAL" for e in regra.evidencias)


def test_selecao_usa_versao_numerica_e_nao_ordem_de_insercao(repo_sqlite):
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    for versao in ("2.5.10", "2.5.9", EXTRACTOR_VERSION):
        repo_sqlite.salvar(ato, extrair_regras(texto), versao)
    fonte, = RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas()
    assert fonte["extrator_versao"] == "2.5.10"


def test_versao_desconhecida_bloqueia_selecao_explicitamente(repo_sqlite):
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    repo_sqlite.salvar(ato, extrair_regras(texto), "versao_desconhecida")
    with pytest.raises(ValueError, match="Versão de extrator não reconhecida"):
        RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas()


def test_extracao_nova_vazia_nao_restaura_beneficio_antigo(repo_sqlite):
    texto = "Art. 1º Fica isento do ICMS o NCM 1234.56.78."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    repo_sqlite.salvar(ato, extrair_regras(texto), "2.5.0")
    repo_sqlite.salvar(ato, [], EXTRACTOR_VERSION)
    assert RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas() == []
    with repo_sqlite.engine.connect() as conexao:
        assert len(list(conexao.execute(select(regras_extraidas)))) == 1


def test_fragmento_extenso_nao_autoriza_aplicacao_com_condicao_cortada():
    texto = (
        "Art. 1º Fica isento do ICMS o NCM 1234.56.78, desde que "
        + "condição fictícia a verificar; " * 140
        + "não seja destinado à revenda."
    )
    regras = extrair_regras(texto)
    materiais = [r for r in regras if r.papel_dispositivo == "REGRA_MATERIAL"]
    assert materiais and all(r.elegivel_consulta_ncm == "NAO" for r in materiais)
    assert all(r.status_revisao == "PENDENTE" for r in regras)
    assert all(r.trecho_origem == texto[r.inicio_trecho:r.fim_trecho] for r in regras)


def test_efeitos_de_cancelamento_nao_iniciam_vigencia_do_beneficio():
    regra, = extrair_regras(
        "Art. 1º Fica isento do ICMS o produto fictício alfa; "
        "o cancelamento do pedido produz efeitos a partir de 1 de janeiro de 2026."
    )
    assert regra.vigencia_inicio is None
    assert any(e.tipo_evidencia == "PRAZO_OPERACIONAL" for e in regra.evidencias)


def test_data_invalida_em_condicao_vinculada_bloqueia_principal():
    regras = extrair_regras(
        "Art. 1º Fica isento do ICMS o NCM 1234.56.78.\n"
        "§ 1º O benefício fica condicionado ao pedido protocolado até 31/02/2026."
    )
    principal, condicao = regras
    assert condicao.grupo_regra_id == principal.grupo_regra_id
    assert principal.elegivel_consulta_ncm == "NAO" and principal.status_revisao == "PENDENTE"
    assert any(e.tipo_evidencia == "PENDENCIA_TEMPORAL" for e in principal.evidencias)


def test_multiplos_ncms_e_percentuais_nao_recebem_primeiro_percentual():
    regras = extrair_regras(
        "Art. 1º Para o NCM 1234.56.78 a alíquota do ICMS é de 19%; "
        "para o NCM 2202.10.00 a alíquota do ICMS é de 7%."
    )
    assert len(regras) == 2
    assert {r.ncm_chave for r in regras} == {"12345678", "22021000"}
    assert all(r.elegivel_consulta_ncm == "NAO" and r.aliquota_icms is None for r in regras)
    assert all(r.status_revisao == "PENDENTE" for r in regras)
    assert all(any(e.tipo_evidencia == "PERCENTUAL_NAO_CLASSIFICADO" for e in r.evidencias)
               for r in regras)


@pytest.fixture
def consolidada_historica(repo_sqlite):
    """Uma consolidação sintética antiga, sem aprovação fiscal real."""
    metadata_fiscal.create_all(repo_sqlite.engine)
    repo = RepositorioConsolidacao(repo_sqlite.engine)
    ato_id, _, _ = inserir_extraida(repo, fim=date(2030, 12, 31))
    with repo.engine.begin() as conexao:
        conexao.execute(update(atos_legislativos).where(
            atos_legislativos.c.id == ato_id,
        ).values(status="PROCESSADO"))
        conexao.execute(update(regras_extraidas).values(extrator_versao="2.5.0"))
        conexao.execute(update(processamentos_extracao).values(extrator_versao="2.5.0"))
    fonte, = repo.listar_extraidas()
    repo.salvar(planejar_regra(fonte, [], date(2026, 10, 19)))
    return repo_sqlite, repo, repo_sqlite.listar_atos()[0]


def _historico_simulacao(engine):
    with engine.connect() as conexao:
        return {tabela.name: [dict(r) for r in conexao.execute(
            select(tabela).order_by(*tabela.primary_key.columns),
        ).mappings()] for tabela in (*metadata.sorted_tables, *metadata_fiscal.sorted_tables)}


@pytest.mark.parametrize("cenario", [
    "nova_bloqueada", "nova_valida", "nova_vazia", "PENDENTE", "FALHOU", "origem_bloqueada",
])
def test_simulacao_nao_apresenta_consolidacao_historica_como_atual(consolidada_historica, cenario):
    extracao, repo, ato = consolidada_historica
    historico_antigo = _historico_simulacao(repo.engine)
    if cenario == "origem_bloqueada":
        with repo.engine.begin() as conexao:
            conexao.execute(update(regras_extraidas).values(
                elegivel_consolidacao="NAO", elegivel_consulta_ncm="NAO",
            ))
    else:
        novas = [] if cenario == "nova_vazia" else extrair_regras(ato.texto_limpo)
        if cenario == "nova_bloqueada":
            for regra in novas:
                regra.elegivel_consolidacao = regra.elegivel_consulta_ncm = "NAO"
        extracao.salvar(ato, novas, EXTRACTOR_VERSION)
        if cenario in {"PENDENTE", "FALHOU"}:
            with repo.engine.begin() as conexao:
                conexao.execute(update(processamentos_extracao).where(
                    processamentos_extracao.c.extrator_versao == EXTRACTOR_VERSION,
                ).values(status=cenario))
    antes = _historico_simulacao(repo.engine)
    assert antes[regras_consolidadas.name] == historico_antigo[regras_consolidadas.name]
    assert antes[evidencias_extracao.name][:len(historico_antigo[evidencias_extracao.name])] == (
        historico_antigo[evidencias_extracao.name])

    def somente_select(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT")

    event.listen(repo.engine, "before_cursor_execute", somente_select)
    propostas, leis, aliquotas = repo.dados_para_simulacao()
    proposta, = propostas
    assert proposta["status_regra"] == "VIGENTE"
    assert proposta["fonte_atual"] is False
    assert not any(p["fonte_atual"] for p in propostas)
    if cenario != "nova_valida":
        assert repo.listar_extraidas() == []
    plano = simular_publicacao(propostas, legislacoes_existentes=leis, aliquotas_existentes=aliquotas)
    assert not plano.para_revisao
    assert any("versão superada" in motivo for motivo in plano.bloqueadas[0]["motivos"])
    assert _historico_simulacao(repo.engine) == antes


def test_simulacao_preserva_fonte_atual_valida_sem_autorizar_publicacao(consolidada_historica):
    _, repo, _ = consolidada_historica
    antes = _historico_simulacao(repo.engine)
    propostas, leis, aliquotas = repo.dados_para_simulacao()
    proposta, = propostas
    assert proposta["fonte_atual"] is True
    assert proposta["status_regra"] == "VIGENTE"
    assert proposta["fonte_verificada"] is False
    plano = simular_publicacao(propostas, legislacoes_existentes=leis, aliquotas_existentes=aliquotas)
    assert not plano.para_revisao
    assert any("Fonte oficial sem confirmação" in motivo for motivo in plano.bloqueadas[0]["motivos"])
    assert _historico_simulacao(repo.engine) == antes

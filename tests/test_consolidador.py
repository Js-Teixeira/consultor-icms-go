"""Cenários fictícios da Fase 3, sem acesso ao Neon ou a sites oficiais."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, insert, select

from updater.consolidacao import (
    CONSOLIDATOR_VERSION, aplicar_em_memoria, chave_consolidacao, planejar_regra,
)
from updater.consolidador import executar
from updater.persistencia import hash_conteudo
from updater.repositorio_consolidacao import RepositorioConsolidacao
from updater.schema import (
    atos_legislativos, evidencias_extracao, metadata, processamentos_extracao,
    regras_consolidadas, regras_extraidas, relacoes_regras, versoes_ato,
)

REFERENCIA = date(2026, 10, 1)


def fonte(identificador=1, *, ato_id=1, acao="INCLUI", ncm="22021000",
          correspondencia="EXATO", artigo="8", norma="Norma fictícia 1/2020",
          aliquota="19", inicio=date(2020, 1, 1), fim=None, tipo="ALIQUOTA",
          beneficio=None, condicoes=None, confianca="ALTA", alertas=None):
    return {
        "id": identificador, "ato_id": ato_id, "tipo_ato": "DECRETO",
        "numero": str(ato_id), "ano": 2026, "tipo_regra": tipo,
        "acao_legislativa": acao, "ncm_chave": ncm,
        "tipo_correspondencia": correspondencia if ncm else None,
        "descricao_legal": None, "aliquota_icms": Decimal(aliquota) if aliquota else None,
        "percentual_reducao_bc": None, "carga_efetiva": None,
        "credito_outorgado_percentual": None, "tipo_beneficio": beneficio,
        "norma_alterada": norma, "anexo": "IX", "artigo": artigo,
        "paragrafo": None, "inciso": None, "alinea": None, "item": None,
        "condicoes_texto": condicoes, "vigencia_inicio": inicio, "vigencia_fim": fim,
        "confianca": confianca, "alertas": alertas,
    }


def aplicar(f, anteriores, identificador):
    decisao = planejar_regra(f, anteriores, REFERENCIA)
    aplicar_em_memoria(decisao, anteriores, identificador)
    return decisao


def test_inclusao_nova_e_vigencia_futura():
    existentes = []
    atual = aplicar(fonte(), existentes, 101)
    futura = aplicar(fonte(2, ato_id=2, artigo="9", inicio=date(2030, 1, 1)), existentes, 102)
    assert atual.status_previsto == "VIGENTE"
    assert futura.status_previsto == "FUTURA"
    assert all(r.valor("status_validacao") == "PENDENTE" for r in existentes)


def test_chave_considera_artigo_e_nao_so_ncm():
    assert chave_consolidacao(fonte(artigo="8")) != chave_consolidacao(fonte(artigo="9"))


@pytest.mark.parametrize("acao", ["ALTERA", "SUBSTITUI"])
def test_alteracao_ou_substituicao_preserva_historico(acao):
    existentes = []
    aplicar(fonte(fim=date(2030, 12, 31)), existentes, 101)
    antiga_data_fim = existentes[0].valor("vigencia_fim")
    decisao = aplicar(fonte(2, ato_id=2, acao=acao, aliquota="7",
                           inicio=date(2026, 1, 1)), existentes, 102)
    assert decisao.status_previsto == "VIGENTE"
    assert (existentes[0].valor("status_regra"), existentes[1].valor("status_regra")) == (
        "SUBSTITUIDA", "VIGENTE")
    assert existentes[0].valor("vigencia_fim") == antiga_data_fim
    assert existentes[1].valor("regra_anterior_id") == 101
    assert any(r.tipo == acao and r.destino_id == 101 for r in decisao.relacoes)


def test_alteracao_sem_inicio_expresso_fica_indeterminada():
    existentes = []
    aplicar(fonte(), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, acao="ALTERA", aliquota="7", inicio=None), existentes, 102)
    assert decisao.status_previsto == "INDETERMINADA"
    assert existentes[0].valor("status_regra") == "VIGENTE"


def test_revogacao_com_alvo_unico_e_data_explicitada():
    existentes = []
    aplicar(fonte(), existentes, 101)
    revogacao = fonte(2, ato_id=2, acao="REVOGA", ncm=None, tipo="REVOGACAO",
                     aliquota=None, inicio=date(2026, 1, 1), confianca="MEDIA")
    decisao = aplicar(revogacao, existentes, 102)
    assert existentes[0].valor("status_regra") == "REVOGADA"
    assert decisao.nova.valor("status_regra") == "INDETERMINADA"
    assert any(r.tipo == "REVOGA" for r in decisao.relacoes)


def test_revogacao_sem_data_nao_revoga_automaticamente():
    existentes = []
    aplicar(fonte(), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, acao="REVOGA", ncm=None, tipo="REVOGACAO",
                           aliquota=None, inicio=None), existentes, 102)
    assert decisao.status_previsto == "INDETERMINADA"
    assert existentes[0].valor("status_regra") == "VIGENTE"


def test_revogacao_de_baixa_confianca_nao_altera_alvo():
    existentes = []
    aplicar(fonte(), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, acao="REVOGA", ncm=None, tipo="REVOGACAO",
                           aliquota=None, inicio=date(2026, 1, 1), confianca="BAIXA"), existentes, 102)
    assert decisao.status_previsto == "INDETERMINADA"
    assert existentes[0].valor("status_regra") == "VIGENTE"


@pytest.mark.parametrize("acao", ["PRORROGA", "RENOVA"])
def test_prorrogacao_e_renovacao_criam_versao_sem_apagar_anterior(acao):
    existentes = []
    aplicar(fonte(fim=date(2025, 12, 31)), existentes, 101)
    inicio = date(2026, 1, 1) if acao == "RENOVA" else date(2020, 1, 1)
    decisao = aplicar(fonte(2, ato_id=2, acao=acao, aliquota=None,
                           inicio=inicio, fim=date(2030, 12, 31)), existentes, 102)
    assert decisao.status_previsto == "VIGENTE"
    assert existentes[0].valor("status_regra") == "SUBSTITUIDA"
    assert existentes[1].valor("aliquota_icms") == Decimal("19")
    assert existentes[1].valor("vigencia_fim") == date(2030, 12, 31)
    assert any(r.tipo == acao for r in decisao.relacoes)


def test_renovacao_com_lacuna_fica_indeterminada():
    existentes = []
    aplicar(fonte(fim=date(2025, 12, 31)), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, acao="RENOVA", inicio=date(2026, 2, 1),
                           fim=date(2030, 12, 31)), existentes, 102)
    assert decisao.status_previsto == "INDETERMINADA"
    assert existentes[0].valor("status_regra") != "SUBSTITUIDA"


def test_prorrogacao_com_percentual_novo_nao_herda_regra_antiga():
    existentes = []
    aplicar(fonte(fim=date(2025, 12, 31)), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, acao="PRORROGA", aliquota="7",
                           fim=date(2030, 12, 31)), existentes, 102)
    assert decisao.status_previsto == "INDETERMINADA"
    assert existentes[0].valor("status_regra") != "SUBSTITUIDA"


def test_conflito_mantem_ambas_pendentes():
    existentes = []
    aplicar(fonte(fim=date(2030, 12, 31)), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, aliquota="7", fim=date(2030, 12, 31)), existentes, 102)
    assert decisao.status_previsto == "CONFLITO"
    assert existentes[0].valor("status_regra") == "CONFLITO"
    assert all(r.valor("status_validacao") == "PENDENTE" for r in existentes)
    assert any(r.tipo == "CONFLITA_COM" for r in decisao.relacoes)


def test_conflito_por_beneficios_incompativeis():
    existentes = []
    aplicar(fonte(tipo="OUTRO_BENEFICIO", beneficio="ISENCAO", aliquota=None,
                 fim=date(2030, 12, 31)), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, tipo="OUTRO_BENEFICIO",
                           beneficio="DIFERIMENTO", aliquota=None,
                           fim=date(2030, 12, 31)), existentes, 102)
    assert decisao.status_previsto == "CONFLITO"


def test_conflito_nao_sobrescreve_validacao_manual():
    existentes = []
    aplicar(fonte(fim=date(2030, 12, 31)), existentes, 101)
    existentes[0].dados["status_validacao"] = "VALIDADA"
    decisao = aplicar(fonte(2, ato_id=2, aliquota="7", fim=date(2030, 12, 31)), existentes, 102)
    assert decisao.status_previsto == "CONFLITO"
    assert existentes[0].valor("status_regra") == "VIGENTE"
    assert existentes[0].valor("status_validacao") == "VALIDADA"


def test_duplicidade_do_mesmo_ato_vincula_origem_sem_nova_regra():
    existentes = []
    aplicar(fonte(), existentes, 101)
    decisao = aplicar(fonte(2), existentes, 102)
    assert decisao.status_previsto == "DUPLICADA"
    assert decisao.duplicada_de == 101
    assert len(existentes) == 1
    assert existentes[0].valor("origens_equivalentes") == "[2]"


def test_ncm_prefixo_e_exato_coexistem_com_relacao():
    existentes = []
    aplicar(fonte(ncm="2202", correspondencia="PREFIXO"), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, ncm="22021000"), existentes, 102)
    assert [r.valor("status_regra") for r in existentes] == ["VIGENTE", "VIGENTE"]
    assert existentes[0].valor("relacao_regra") == "GERAL"
    assert existentes[1].valor("relacao_regra") == "ESPECIFICA"
    assert any(r.tipo == "ESPECIFICA_DE" for r in decisao.relacoes)


def test_excecao_nao_revoga_regra_geral():
    existentes = []
    aplicar(fonte(ncm="2202", correspondencia="PREFIXO"), existentes, 101)
    decisao = aplicar(fonte(2, ato_id=2, ncm="22021000", condicoes="exceto caso fictício",
                           alertas="Exceção explícita"), existentes, 102)
    assert decisao.nova.valor("relacao_regra") == "EXCECAO"
    assert any(r.tipo == "EXCECAO_DE" for r in decisao.relacoes)
    assert existentes[0].valor("status_regra") == "VIGENTE"


def test_acao_nao_identificada_fica_indeterminada():
    decisao = planejar_regra(fonte(acao="SEM_IDENTIFICACAO"), [], REFERENCIA)
    assert decisao.status_previsto == "INDETERMINADA"
    assert decisao.nova.valor("confianca") == "BAIXA"


def test_inclusao_sem_valor_explicito_nao_vira_vigente():
    decisao = planejar_regra(fonte(aliquota=None), [], REFERENCIA)
    assert decisao.status_previsto == "INDETERMINADA"


@pytest.fixture
def repo():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return RepositorioConsolidacao(engine)


def inserir_extraida(repo, *, texto="NCM 2202.10.00: alíquota de 19% no art. 8º.",
                    acao="INCLUI", norma="Norma fictícia 1/2020", numero="1",
                    aliquota="19", fim=None):
    with repo.engine.begin() as conexao:
        ato_id = conexao.execute(insert(atos_legislativos).values(
            tipo_ato="DECRETO", numero=numero, ano=2026, data_ato=date(2026, 1, 1),
            titulo="Ato fictício", url_descoberta="https://goias.gov.br/lista",
            url_texto_oficial="https://goias.gov.br/ato", fonte="Fonte oficial fictícia",
            texto_original=texto, texto_limpo=texto, hash_conteudo=hash_conteudo(texto),
            status="NOVO", relevancia="ALTA", motivos_relevancia="Teste fictício",
        ).returning(atos_legislativos.c.id)).scalar_one()
        versao_id = conexao.execute(insert(versoes_ato).values(
            ato_id=ato_id, hash_conteudo=hash_conteudo(texto),
            texto_original=texto, texto_limpo=texto,
        ).returning(versoes_ato.c.id)).scalar_one()
        processamento_id = conexao.execute(insert(processamentos_extracao).values(
            ato_id=ato_id, versao_ato_id=versao_id, extrator_versao="2.0.0",
            status="COMPLETO",
        ).returning(processamentos_extracao.c.id)).scalar_one()
        regra_id = conexao.execute(insert(regras_extraidas).values(
            ato_id=ato_id, versao_ato_id=versao_id, processamento_id=processamento_id,
            chave_extracao=hash_conteudo(texto), tipo_regra="ALIQUOTA",
            acao_legislativa=acao, ncm_chave="22021000", tipo_correspondencia="EXATO",
            aliquota_icms=Decimal(aliquota), norma_alterada=norma, anexo="IX", artigo="8",
            vigencia_inicio=date(2020, 1, 1), vigencia_fim=fim, trecho_origem=texto,
            inicio_trecho=0, fim_trecho=len(texto), confianca="ALTA",
            status_revisao="PENDENTE", motivos_confianca="Teste fictício",
            escopo_fiscal="ALIQUOTA_BENEFICIO", elegivel_consolidacao="SIM",
            motivo_elegibilidade="Regra material fictícia.",
            papel_dispositivo="REGRA_MATERIAL",
            elegivel_consulta_ncm="SIM", status_vinculo_ncm="NCM_EXPLICITO",
            motivo_consulta_ncm="NCM explícito em teste fictício.",
            extrator_versao="2.0.0",
        ).returning(regras_extraidas.c.id)).scalar_one()
        conexao.execute(insert(evidencias_extracao).values(
            regra_extraida_id=regra_id, tipo_evidencia="NCM", valor_extraido="2202.10.00",
            texto_origem="2202.10.00", posicao_inicio=4, posicao_fim=14,
            confianca="ALTA", metodo="teste_ficticio",
        ))
    return ato_id, versao_id, regra_id


def contar(repo, tabela):
    with repo.engine.connect() as conexao:
        return conexao.execute(select(func.count()).select_from(tabela)).scalar_one()


def test_dry_run_nao_escreve(repo, capsys):
    inserir_extraida(repo)
    totais = executar(repo, dry_run=True)
    assert totais["novas"] == 1
    assert "DRY-RUN" in capsys.readouterr().out
    assert contar(repo, regras_consolidadas) == contar(repo, relacoes_regras) == 0


def test_modo_normal_idempotencia_e_rastreabilidade_completa(repo):
    ato_id, versao_id, regra_id = inserir_extraida(repo)
    assert executar(repo)["novas"] == 1
    assert executar(repo)["novas"] == 0
    assert contar(repo, regras_consolidadas) == 1
    with repo.engine.connect() as conexao:
        linha = conexao.execute(select(
            regras_consolidadas.c.regra_origem_id, regras_extraidas.c.versao_ato_id,
            evidencias_extracao.c.texto_origem, atos_legislativos.c.url_texto_oficial,
        ).select_from(regras_consolidadas).join(regras_extraidas,
            regras_consolidadas.c.regra_origem_id == regras_extraidas.c.id).join(
            evidencias_extracao, evidencias_extracao.c.regra_extraida_id == regras_extraidas.c.id,
        ).join(atos_legislativos, regras_extraidas.c.ato_id == atos_legislativos.c.id)).one()
    assert linha[0] == regra_id and linha[1] == versao_id
    assert linha[2] == "2202.10.00" and linha[3] == "https://goias.gov.br/ato"
    assert repo.painel()[0]["status_validacao"] == "PENDENTE"


def test_nova_versao_consolidador_mantem_historico(repo):
    inserir_extraida(repo)
    assert executar(repo, versao=CONSOLIDATOR_VERSION)["novas"] == 1
    assert executar(repo, versao="3.4.0")["novas"] == 1
    assert contar(repo, regras_consolidadas) == 2


def test_modo_normal_grava_conflito_e_relacao_sem_escolher_percentual(repo):
    inserir_extraida(repo, numero="1", fim=date(2030, 12, 31))
    inserir_extraida(repo, numero="2", texto="NCM 2202.10.00: alíquota de 7% no art. 8º.",
                    aliquota="7", fim=date(2030, 12, 31))
    totais = executar(repo)
    assert totais["novas"] == 2 and totais["conflitos"] == 1
    with repo.engine.connect() as conexao:
        linhas = conexao.execute(select(regras_consolidadas.c.status_regra,
                                        regras_consolidadas.c.status_validacao)).all()
        relacao = conexao.execute(select(relacoes_regras.c.tipo_relacao)).scalar_one()
    assert linhas == [("CONFLITO", "PENDENTE"), ("CONFLITO", "PENDENTE")]
    assert relacao == "CONFLITA_COM"


def test_modo_normal_vincula_duplicata_extraida_sem_duplicar_consolidada(repo):
    ato_id, versao_id, _ = inserir_extraida(repo)
    with repo.engine.begin() as conexao:
        processamento_id = conexao.execute(select(processamentos_extracao.c.id).where(
            processamentos_extracao.c.ato_id == ato_id)).scalar_one()
        conexao.execute(insert(regras_extraidas).values(
            ato_id=ato_id, versao_ato_id=versao_id, processamento_id=processamento_id,
            chave_extracao="b" * 64, tipo_regra="ALIQUOTA", acao_legislativa="INCLUI",
            ncm_chave="22021000", tipo_correspondencia="EXATO", aliquota_icms=Decimal("19"),
            norma_alterada="Norma fictícia 1/2020", anexo="IX", artigo="8",
            vigencia_inicio=date(2020, 1, 1), trecho_origem="Outro trecho equivalente fictício",
            inicio_trecho=0, fim_trecho=33, confianca="ALTA", status_revisao="PENDENTE",
            motivos_confianca="Teste fictício", extrator_versao="2.0.0",
            escopo_fiscal="ALIQUOTA_BENEFICIO", elegivel_consolidacao="SIM",
            motivo_elegibilidade="Regra material fictícia.",
            papel_dispositivo="REGRA_MATERIAL",
            elegivel_consulta_ncm="SIM", status_vinculo_ncm="NCM_EXPLICITO",
            motivo_consulta_ncm="NCM explícito em teste fictício.",
        ))
    totais = executar(repo)
    assert totais["novas"] == 1 and totais["duplicadas"] == 1
    assert contar(repo, regras_consolidadas) == 1
    with repo.engine.connect() as conexao:
        origens = conexao.execute(select(regras_consolidadas.c.origens_equivalentes)).scalar_one()
    assert origens.startswith("[") and origens.endswith("]") and origens != "[]"


def test_selecao_por_ano_ato_e_limite(repo):
    primeiro, _, _ = inserir_extraida(repo, numero="1")
    segundo, _, _ = inserir_extraida(repo, numero="2")
    assert len(repo.listar_extraidas(ano=2026, limite=1)) == 1
    assert [r["ato_id"] for r in repo.listar_extraidas(ato_id=segundo)] == [segundo]
    assert repo.listar_extraidas(ato_id=primeiro, ano=2025) == []


def test_fase_3_ignora_extraida_fora_do_escopo_sem_apagar(repo):
    _, _, regra_id = inserir_extraida(repo)
    with repo.engine.begin() as conexao:
        conexao.execute(regras_extraidas.update().where(regras_extraidas.c.id == regra_id).values(
            escopo_fiscal="PAUTA_PRECO", elegivel_consolidacao="NAO",
            motivo_elegibilidade="Apenas pauta de preços.",
        ))
    assert repo.listar_extraidas() == []
    assert executar(repo)["novas"] == 0
    assert contar(repo, regras_extraidas) == 1
    assert contar(repo, regras_consolidadas) == 0


def test_schema_fiscal_permanece_separado():
    from src.dados.schema import TABELAS

    assert set(TABELAS) == {"NCM", "Legislacao", "Aliquotas", "Beneficios"}
    assert "regras_consolidadas" in metadata.tables
    assert "relacoes_regras" in metadata.tables

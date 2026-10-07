"""Fase 2: casos fictícios, sem consultar a rede nem o banco real."""

from __future__ import annotations

from decimal import Decimal
import json

import pytest
from sqlalchemy import create_engine, func, insert, select

from updater.extracao_fiscal import EXTRACTOR_VERSION, detectar_ncms, extrair_regras
from updater.extrator import executar
from updater.consolidador import executar as consolidar
from updater.persistencia import hash_conteudo
from updater.repositorio_extracao import RepositorioExtracao
from updater.repositorio_consolidacao import RepositorioConsolidacao
from updater.schema import (
    atos_legislativos, evidencias_extracao, metadata, processamentos_extracao,
    regras_extraidas, regras_consolidadas, versoes_ato,
)


def unica(texto: str):
    regras = extrair_regras(texto)
    assert len(regras) == 1
    return regras[0]


@pytest.mark.parametrize(("ncm", "chave", "correspondencia"), [
    ("22021000", "22021000", "EXATO"),
    ("2202.10.00", "22021000", "EXATO"),
    ("2202.10", "220210", "PREFIXO"),
    ("posição 2202", "2202", "PREFIXO"),
])
def test_ncm_contextual(ncm, chave, correspondencia):
    entrada = ncm if ncm.startswith("posição") else "NCM " + ncm
    regra = unica(f"{entrada}: alíquota de 19% no art. 8º do Anexo IX.")
    assert (regra.ncm_original, regra.ncm_chave, regra.tipo_correspondencia) == (
        ncm.removeprefix("posição "), chave, correspondencia)


def test_numero_comum_nao_vira_ncm():
    regra = unica("Art. 1234 - alíquota de 19% para mercadoria fictícia.")
    assert regra.ncm_chave is None


def test_tabela_com_multiplas_linhas_preserva_associacao():
    texto = "NCM | descrição | alíquota\n2202.10.00 | Bebida fictícia | 19%\n2202.20.00 | Produto fictício | 7%"
    regras = extrair_regras(texto)
    assert [(r.ncm_chave, r.descricao_legal, r.aliquota_icms) for r in regras] == [
        ("22021000", "Bebida fictícia", Decimal("19")),
        ("22022000", "Produto fictício", Decimal("7")),
    ]
    assert all(r.trecho_origem == texto[r.inicio_trecho:r.fim_trecho] for r in regras)
    assert not any("Produto fictício" in r.trecho_origem for r in regras[:1])


def test_tabela_html_preserva_linhas():
    html = "<table><tr><th>NCM</th><th>Descrição</th><th>Alíquota</th></tr><tr><td>2202.10.00</td><td>Bebida</td><td>19%</td></tr><tr><td>2202.20.00</td><td>Outro produto</td><td>7%</td></tr></table>"
    from updater.normalizacao import limpar_html

    texto = limpar_html(html)
    regras = extrair_regras(texto, html)
    assert [(r.ncm_chave, r.descricao_legal, r.aliquota_icms) for r in regras] == [
        ("22021000", "Bebida", Decimal("19")),
        ("22022000", "Outro produto", Decimal("7")),
    ]


@pytest.mark.parametrize(("frase", "tipo", "campo", "valor"), [
    ("alíquota de 19%", "ALIQUOTA", "aliquota_icms", Decimal("19")),
    ("redução de 60% da base de cálculo", "REDUCAO_BASE_CALCULO", "percentual_reducao_bc", Decimal("60")),
    ("de forma que a carga tributária resulte em 7%", "ALTERACAO_LEGISLATIVA", "carga_efetiva", Decimal("7")),
    ("crédito outorgado de 5%", "CREDITO_OUTORGADO", "credito_outorgado_percentual", Decimal("5")),
    ("alíquota de 0,1%", "ALIQUOTA", "aliquota_icms", Decimal("0.1")),
])
def test_percentuais_com_contexto(frase, tipo, campo, valor):
    regra = unica(f"NCM 2202.10.00: {frase}, art. 8º do Anexo IX.")
    assert regra.tipo_regra == tipo
    assert getattr(regra, campo) == valor
    assert not regra.alertas


def test_percentual_sem_contexto_fica_sem_classificacao():
    regra = unica("NCM 2202.10.00 | 7%")
    assert regra.confianca == "BAIXA"
    assert all(getattr(regra, campo) is None for campo in (
        "aliquota_icms", "percentual_reducao_bc", "carga_efetiva", "credito_outorgado_percentual"))
    assert any(e.tipo_evidencia == "PERCENTUAL_NAO_CLASSIFICADO" for e in regra.evidencias)


def test_dispositivos_condicao_excecao_e_norma_alterada():
    regra = unica('NCM 2202.10.00: alíquota de 19% no inciso III do art. 8º do Anexo IX, § 1º, alínea "a", item 2, desde que destinado a exemplo fictício, exceto um caso. Altera o Decreto nº 4.852/1997 — RCTE.')
    assert (regra.anexo, regra.artigo, regra.paragrafo, regra.inciso, regra.alinea, regra.item) == (
        "IX", "8", "1", "III", "a", "2")
    assert regra.condicoes_texto and "exceto" in regra.condicoes_texto
    assert regra.norma_alterada and "Decreto nº 4.852/1997" in regra.norma_alterada
    assert regra.confianca == "BAIXA" and regra.alertas


def test_vigencia_explicita_e_ausencia():
    regra = unica("NCM 2202.10.00: alíquota de 19% no art. 8º; produz efeitos a partir de 1 de março de 2026 até 31 de dezembro de 2026.")
    assert str(regra.vigencia_inicio) == "2026-03-01"
    assert str(regra.vigencia_fim) == "2026-12-31"
    assert unica("NCM 2202.10.00: alíquota de 19% no art. 8º.").vigencia_inicio is None


def test_revogacao_sem_apagar_regra_fiscal():
    regra = unica("Fica revogado o inciso X do art. 8º do Anexo IX.")
    assert (regra.tipo_regra, regra.acao_legislativa, regra.inciso) == ("REVOGACAO", "REVOGA", "X")
    assert regra.ncm_chave is None


@pytest.mark.parametrize(("frase", "tipo", "acao"), [
    ("Fica acrescido o inciso III do art. 8º do Anexo IX: isento o NCM 2202.10.00.", "ISENCAO", "INCLUI"),
    ("Passa a vigorar com a seguinte redação: fica diferido o ICMS do NCM 2202.10.00.", "DIFERIMENTO", "ALTERA"),
    ("Fica prorrogada a suspensão do recolhimento do ICMS nas operações com NCM 2202.10.00.", "SUSPENSAO", "PRORROGA"),
])
def test_tipo_e_acao_explicitos(frase, tipo, acao):
    regra = unica(frase)
    assert (regra.tipo_regra, regra.acao_legislativa) == (tipo, acao)


@pytest.mark.parametrize("texto", [
    "A exigibilidade do crédito tributário fica suspensa.",
    "TARE suspenso por decisão administrativa.",
    "Dívida ativa com exigibilidade suspensa.",
    "Fica suspensa a exigibilidade do crédito tributário constituído.",
])
def test_suspensao_de_credito_nao_e_beneficio(texto):
    regra = unica(texto)
    assert regra.tipo_regra != "SUSPENSAO"
    assert (regra.escopo_fiscal, regra.elegivel_consolidacao) == ("CREDITO_TRIBUTARIO", "NAO")
    assert regra.motivo_elegibilidade and regra.confianca == "BAIXA"
    assert any(e.tipo_evidencia == "ESCOPO_FISCAL" for e in regra.evidencias)


def test_suspensao_fiscal_explicita_sem_ncm_nao_vai_para_consolidacao_ncm():
    regra = unica("Fica suspenso o recolhimento do ICMS nas operações com mercadorias descritas no art. 8º.")
    assert regra.tipo_regra == "SUSPENSAO"
    assert regra.ncm_chave is None
    assert (regra.escopo_fiscal, regra.elegivel_consolidacao) == ("ALIQUOTA_BENEFICIO", "NAO")
    assert regra.elegivel_consulta_ncm == "NAO"


@pytest.mark.parametrize("texto", [
    "Alteram-se os preços da Pauta de Mercadorias.",
    "Todos os preços publicados passam a vigorar nesta data.",
])
def test_pauta_de_precos_nao_elegivel(texto):
    regra = unica(texto)
    assert (regra.escopo_fiscal, regra.elegivel_consolidacao) == ("PAUTA_PRECO", "NAO")
    assert regra.trecho_origem == texto


def test_pauta_que_apenas_menciona_aliquota_continua_fora_do_escopo():
    regra = unica("A pauta de mercadorias fixa valores de referência para cálculo da alíquota do ICMS.")
    assert (regra.escopo_fiscal, regra.elegivel_consolidacao) == ("PAUTA_PRECO", "NAO")


def test_pauta_com_aliquota_explicita_no_mesmo_trecho_e_elegivel():
    regra = unica("Para o NCM 2202.10.00, a alíquota do ICMS é de 19%; atualiza-se a pauta de mercadorias.")
    assert regra.aliquota_icms == Decimal("19")
    assert (regra.escopo_fiscal, regra.elegivel_consolidacao) == ("ALIQUOTA_BENEFICIO", "SIM")


def test_cabecalho_generico_nao_promove_regra_mas_conteudo_seguinte_e_analisado():
    regras = extrair_regras("Passa a vigorar com as seguintes alterações:\nFica isenta do ICMS a operação de saída de produto fictício.")
    assert len(regras) == 2
    assert (regras[0].escopo_fiscal, regras[0].elegivel_consolidacao, regras[0].confianca) == (
        "INDETERMINADO", "NAO", "BAIXA")
    assert (regras[1].tipo_regra, regras[1].elegivel_consolidacao, regras[1].ncm_chave) == (
        "ISENCAO", "NAO", None)


def test_beneficio_generico_sem_ncm_nao_cria_grupo_de_consolidacao():
    texto = "\n".join([
        "Art. 1º Fica autorizado a conceder crédito outorgado do ICMS a estabelecimentos industriais do Programa Exemplo.",
        "Art. 2º Para ser beneficiário do crédito outorgado, deve celebrar termo de acordo.",
        "Art. 3º O cálculo do crédito outorgado observará a produção do estabelecimento.",
        "Art. 4º O valor do crédito outorgado deve ser utilizado na apuração.",
        "Art. 5º O contribuinte deverá estornar o crédito se descumprir o acordo.",
        "Art. 6º Fica condicionado ao cumprimento do regime especial.",
        "Art. 7º É vedada a utilização do crédito outorgado fora do programa.",
    ])
    regras = extrair_regras(texto)
    assert len(regras) == 7
    principal, *complementos = regras
    assert (principal.tipo_regra, principal.papel_dispositivo, principal.elegivel_consolidacao) == (
        "CREDITO_OUTORGADO", "REGRA_MATERIAL", "NAO")
    assert principal.credito_outorgado_percentual is None
    assert principal.ncm_chave is None
    assert principal.elegivel_consulta_ncm == "NAO"
    assert principal.grupo_regra_id is None
    assert [r.papel_dispositivo for r in complementos] == [
        "BENEFICIARIO", "CALCULO", "UTILIZACAO", "CONSEQUENCIA", "CONDICAO", "VEDACAO",
    ]
    assert all(r.elegivel_consolidacao == "NAO" and r.grupo_regra_id is None for r in complementos)
    assert all(r.trecho_origem == texto[r.inicio_trecho:r.fim_trecho] for r in regras)
    assert all(texto[e.posicao_inicio:e.posicao_fim] == e.texto_origem
               for r in regras for e in r.evidencias)


def test_condicao_e_estorno_isolados_nao_criam_credito_outorgado():
    regras = extrair_regras("Deve celebrar termo de acordo para o crédito outorgado.\nDeverá estornar o crédito outorgado.")
    assert [r.papel_dispositivo for r in regras] == ["CONDICAO", "CONSEQUENCIA"]
    assert all(r.tipo_regra != "CREDITO_OUTORGADO" and r.elegivel_consolidacao == "NAO"
               and r.grupo_regra_id is None for r in regras)


def test_cabecalhos_de_artigo_separados_preservam_dispositivo_e_evidencia():
    texto = "Art. 1º\nFica autorizado a conceder crédito outorgado do ICMS a estabelecimento industrial.\nArt. 2º\nDeve celebrar termo de acordo para usar o benefício."
    principal, complemento = extrair_regras(texto)
    assert (principal.artigo, complemento.artigo) == ("1", "2")
    assert complemento.grupo_regra_id is principal.grupo_regra_id is None
    assert any(e.tipo_evidencia == "ARTIGO" and e.texto_origem == "Art. 2º" for e in complemento.evidencias)
    assert all(texto[e.posicao_inicio:e.posicao_fim] == e.texto_origem for e in complemento.evidencias)


def test_percentual_em_calculo_complementar_nao_e_herdado_pelo_principal():
    principal, calculo = extrair_regras(
        "Art. 1º Fica autorizado a conceder crédito outorgado do ICMS ao contribuinte.\n"
        "Art. 2º O valor do crédito outorgado de 5% será apurado em regime especial."
    )
    assert principal.papel_dispositivo == "REGRA_MATERIAL"
    assert principal.credito_outorgado_percentual is None
    assert calculo.papel_dispositivo == "CALCULO"
    assert calculo.elegivel_consolidacao == "NAO"
    assert calculo.grupo_regra_id is principal.grupo_regra_id is None


def test_beneficio_material_sem_ncm_nao_cria_grupos():
    regras = extrair_regras("\n".join([
        "Art. 1º Fica autorizado a conceder crédito outorgado do ICMS ao Programa A.",
        "Art. 2º Deve celebrar termo de acordo para obter o benefício.",
        "Art. 3º Fica concedido crédito outorgado do ICMS ao Programa B.",
        "Art. 4º Deve celebrar termo de acordo para obter o benefício.",
    ]))
    assert len(regras) == 4
    assert all(r.grupo_regra_id is None for r in regras)
    assert sum(r.elegivel_consolidacao == "SIM" for r in regras) == 0


def test_dispositivos_complementares_acompanham_principal_na_fase_3(repo_sqlite, capsys):
    texto = "\n".join([
        "Art. 1º Fica autorizado a conceder crédito outorgado do ICMS ao NCM 2202.10.00 em estabelecimento industrial.",
        "Art. 2º Para ser beneficiário, deve celebrar termo de acordo.",
        "Art. 3º O valor do crédito deve ser utilizado na apuração.",
        "Art. 4º Deverá estornar o crédito em caso de descumprimento.",
    ])
    inserir_ato(repo_sqlite, texto)
    executar(repo_sqlite, dry_run=True)
    saida = capsys.readouterr().out
    assert "Regras materiais: 1" in saida
    assert "Dispositivos complementares: 3" in saida
    assert "Grupos NCM com complementos: 1" in saida
    assert "Regras fora do escopo: 0" in saida
    assert "Art. 4 — CONSEQUENCIA" in saida
    assert contagem(repo_sqlite, regras_extraidas) == 0
    executar(repo_sqlite)
    fase3 = RepositorioConsolidacao(repo_sqlite.engine)
    fontes = fase3.listar_extraidas()
    assert len(fontes) == 1
    complementos = json.loads(fontes[0]["complementos_json"])
    assert [r["papel"] for r in complementos] == ["BENEFICIARIO", "UTILIZACAO", "CONSEQUENCIA"]
    assert all(r["regra_extraida_id"] and r["evidencias"] for r in complementos)
    assert "deve celebrar termo" in fontes[0]["condicoes_texto"]
    assert contagem(repo_sqlite, regras_extraidas) == 4
    assert consolidar(fase3)["novas"] == 1
    with repo_sqlite.engine.connect() as conexao:
        consolidada = conexao.execute(select(regras_consolidadas)).mappings().one()
    assert len(json.loads(consolidada["complementos_json"])) == 3
    assert "deve celebrar termo" in consolidada["condicoes_texto"]


@pytest.mark.parametrize(("texto", "chave", "correspondencia"), [
    ("NCM 22021000: fica isenta do ICMS a operação de saída do produto.", "22021000", "EXATO"),
    ("posição 2202: redução de 50% da base de cálculo do ICMS.", "2202", "PREFIXO"),
], ids=["isencao_ncm_exato", "reducao_posicao_prefixo"])
def test_beneficio_com_ncm_explicito_e_elegivel_para_consulta(texto, chave, correspondencia):
    regra = unica(texto)
    assert (regra.ncm_chave, regra.tipo_correspondencia) == (chave, correspondencia)
    assert (regra.elegivel_consulta_ncm, regra.status_vinculo_ncm) == ("SIM", "NCM_EXPLICITO")


def test_produto_descrito_sem_ncm_aguarda_vinculo_oficial():
    regra = unica("Produto refrigerante de cola: fica isento do ICMS nas operações de saída.")
    assert regra.ncm_chave is None
    assert regra.elegivel_consolidacao == "NAO"
    assert (regra.elegivel_consulta_ncm, regra.status_vinculo_ncm) == (
        "NAO", "PENDENTE_VINCULO_NCM")
    assert "associação a NCM oficial" in regra.motivo_consulta_ncm


@pytest.mark.parametrize("texto", [
    "Fica autorizado a conceder crédito outorgado do ICMS aos participantes do PROGOIÁS.",
    "Fica autorizado a conceder crédito outorgado do ICMS ao estabelecimento industrial.",
    "Fica isento do ICMS o contribuinte participante do programa de incentivo.",
    "Fica concedido crédito outorgado do ICMS à empresa beneficiária do PRODUZIR.",
    "Fica concedido crédito outorgado do ICMS à empresa vinculada ao FOMENTAR.",
    "Fica concedido crédito outorgado do ICMS para produtos industrializados no PROGOIÁS.",
])
def test_beneficio_generico_sem_mercadoria_fica_fora_da_consulta_ncm(texto):
    regra = unica(texto)
    assert regra.escopo_fiscal == "ALIQUOTA_BENEFICIO"
    assert regra.papel_dispositivo == "REGRA_MATERIAL"
    assert (regra.elegivel_consulta_ncm, regra.status_vinculo_ncm) == (
        "NAO", "SEM_VINCULO_NCM")
    assert regra.motivo_consulta_ncm == (
        "Benefício fiscal sem vínculo suficiente com NCM ou mercadoria consultável.")


def test_codigo_sem_rotulo_fiscal_nao_e_inventado_como_ncm():
    regra = unica("Mercadoria de código 22021000: fica isenta do ICMS.")
    assert regra.ncm_chave is None
    assert regra.elegivel_consulta_ncm == "NAO"


@pytest.mark.parametrize(("texto", "original", "normalizado", "tipo"), [
    ("NCM 2202.10.00", "2202.10.00", "22021000", "EXATO"),
    ("NCM/SH 2710.12.49", "2710.12.49", "27101249", "EXATO"),
    ("NCM-SH 2710.12.49", "2710.12.49", "27101249", "EXATO"),
    ("NCM 22021000", "22021000", "22021000", "EXATO"),
    ("Mercadoria classificada como 2710.12.49", "2710.12.49", "27101249", "EXATO"),
    ("Mercadoria classificada sob o código 27101249", "27101249", "27101249", "EXATO"),
    ("posição 2202 da NCM", "2202", "2202", "PREFIXO"),
    ("subposição 2202.10", "2202.10", "220210", "PREFIXO"),
])
def test_varredura_integral_detecta_formatos_ncm(texto, original, normalizado, tipo):
    deteccao = detectar_ncms(texto)
    assert len(deteccao) == 1
    assert (deteccao[0].original, deteccao[0].normalizado,
            deteccao[0].tipo_correspondencia) == (original, normalizado, tipo)
    assert texto[deteccao[0].inicio:deteccao[0].fim] == original
    regra = unica(texto)
    assert (regra.ncm_original, regra.ncm_normalizado,
            regra.tipo_correspondencia) == (original, normalizado, tipo)
    assert regra.elegivel_consulta_ncm == "NAO"


def test_varredura_nao_confunde_numeros_aleatorios_com_ncm():
    texto = "Art. 1234. Processo administrativo nº 12345678. Data 2026.10.01. Mercadoria de código 22021000."
    assert detectar_ncms(texto) == []


def test_regressao_ncm_procedimental_nafta_preserva_descricao_e_evidencia():
    texto = (
        "Art. 2º No caso de importação de nafta não petroquímica classificada na "
        "NCM/SH 2710.12.49, deve ser exigida também a manifestação do Fisco para fins de ICMS-ST."
    )
    regra = unica(texto)
    assert (regra.ncm_original, regra.ncm_normalizado, regra.tipo_correspondencia) == (
        "2710.12.49", "27101249", "EXATO")
    assert regra.descricao_proxima_ncm == "nafta não petroquímica"
    assert regra.papel_dispositivo == "PROCEDIMENTO"
    assert regra.elegivel_consulta_ncm == "NAO"
    assert regra.motivo_consulta_ncm == (
        "NCM identificado em dispositivo procedimental, sem tratamento tributário material suficiente para consulta.")
    assert all(texto[e.posicao_inicio:e.posicao_fim] == e.texto_origem for e in regra.evidencias)
    assert {e.tipo_evidencia for e in regra.evidencias} >= {"NCM", "DESCRICAO_PROXIMA_NCM", "ARTIGO"}


def test_descricao_proxima_tambem_e_preservada_em_regra_material_ja_detectada():
    texto = (
        "Art. 8º Fica isenta do ICMS a importação de nafta não petroquímica "
        "classificada na NCM/SH 2710.12.49."
    )
    regra = unica(texto)
    assert regra.ncm_chave == "27101249"
    assert regra.papel_dispositivo == "REGRA_MATERIAL"
    assert regra.descricao_proxima_ncm == "nafta não petroquímica"
    assert any(e.tipo_evidencia == "DESCRICAO_PROXIMA_NCM" and
               texto[e.posicao_inicio:e.posicao_fim] == "nafta não petroquímica"
               for e in regra.evidencias)


def test_ncm_dividido_entre_linhas_permanece_rastreavel():
    texto = "Art. 2º Nafta não petroquímica classificada na\nNCM/SH\n2710.12.49, com manifestação do Fisco."
    regra = unica(texto)
    assert regra.ncm_normalizado == "27101249"
    assert "Nafta não petroquímica" in regra.trecho_origem
    assert regra.elegivel_consulta_ncm == "NAO"


def test_resumo_escopo_no_dry_run_sem_escrita(repo_sqlite, capsys):
    inserir_ato(repo_sqlite, "Preços da Pauta de Mercadorias.\nNCM 2202.10.00: alíquota de 19% no art. 8º.")
    executar(repo_sqlite, dry_run=True)
    saida = capsys.readouterr().out
    assert "Regras detectadas: 2" in saida
    assert "Regras elegíveis para consolidação: 1" in saida
    assert "Regras fora do escopo: 1" in saida
    assert "Pauta de preços: 1" in saida
    assert "Crédito tributário/procedimento: 0" in saida
    assert "Regras indeterminadas: 0" in saida
    assert contagem(repo_sqlite, regras_extraidas) == 0


def test_resumo_consulta_ncm_no_dry_run_sem_escrita(repo_sqlite, capsys):
    inserir_ato(repo_sqlite, "\n".join([
        "NCM 22021000: fica isenta do ICMS a operação de saída.",
        "posição 2202: redução de 50% da base de cálculo do ICMS.",
        "Produto refrigerante de cola: fica isento do ICMS.",
        "Fica concedido crédito outorgado do ICMS ao PROGOIÁS.",
    ]))
    executar(repo_sqlite, dry_run=True)
    saida = capsys.readouterr().out
    for esperado in (
        "Regras detectadas: 4", "Regras com NCM explícito: 2",
        "Regras com prefixo NCM: 1", "Regras com mercadoria sem NCM: 1",
        "Regras elegíveis para consulta NCM: 2",
        "Regras pendentes de vínculo NCM: 1", "Regras fora do escopo NCM: 1",
    ):
        assert esperado in saida
    assert contagem(repo_sqlite, regras_extraidas) == 0


def test_fase_3_nao_recebe_beneficio_generico_sem_ncm(repo_sqlite):
    inserir_ato(repo_sqlite, "Fica autorizado a conceder crédito outorgado do ICMS ao PROGOIÁS.")
    executar(repo_sqlite)
    with repo_sqlite.engine.connect() as conexao:
        regra = conexao.execute(select(regras_extraidas)).mappings().one()
    assert regra["elegivel_consolidacao"] == "NAO"
    assert regra["elegivel_consulta_ncm"] == "NAO"
    assert regra["status_vinculo_ncm"] == "SEM_VINCULO_NCM"
    assert RepositorioConsolidacao(repo_sqlite.engine).listar_extraidas() == []
    assert contagem(repo_sqlite, regras_extraidas) == 1


def test_atos_com_ncm_têm_prioridade_na_selecao(repo_sqlite):
    com_ncm, _ = inserir_ato(repo_sqlite, "NCM 22021000: isenção do ICMS.")
    inserir_ato(repo_sqlite, "Crédito outorgado do ICMS para empresa de programa estadual.")
    assert [ato.id for ato in repo_sqlite.listar_atos(limite=1)] == [com_ncm]


def test_trecho_extenso_nao_descartado_silenciosamente():
    texto = "Texto introdutório fictício. " * 120 + "NCM 2202.10.00: alíquota de 19% no art. 8º."
    regras = extrair_regras(texto)
    assert any(r.ncm_chave == "22021000" and r.confianca == "BAIXA" for r in regras)
    assert all(len(r.trecho_origem) <= 3000 for r in regras)


def test_confianca_alta_media_baixa():
    alta = unica("NCM 2202.10.00: alíquota de 19% no art. 8º.")
    media = unica("NCM 2202.10.00: alíquota de 19%.")
    baixa = unica("NCM 2202.10.00 | 7%")
    assert (alta.confianca, media.confianca, baixa.confianca) == ("ALTA", "MEDIA", "BAIXA")
    assert all(r.motivos_confianca for r in (alta, media, baixa))


def test_evidencias_apontam_para_texto_origem():
    texto = "NCM 2202.10.00: alíquota de 19% no art. 8º do Anexo IX."
    regra = unica(texto)
    assert any(e.tipo_evidencia == "NCM" for e in regra.evidencias)
    for evidencia in regra.evidencias:
        assert texto[evidencia.posicao_inicio:evidencia.posicao_fim] == evidencia.texto_origem


@pytest.fixture
def repo_sqlite():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return RepositorioExtracao(engine)


def inserir_ato(repo: RepositorioExtracao, texto: str, *, relevancia="ALTA", fonte="https://goias.gov.br/ato", ano=2026):
    with repo.engine.begin() as conexao:
        ato_id = conexao.execute(insert(atos_legislativos).values(
            tipo_ato="DECRETO", numero=str(conexao.execute(select(func.count()).select_from(atos_legislativos)).scalar_one() + 1),
            ano=ano, titulo="Ato fictício", url_descoberta="https://goias.gov.br/lista",
            url_texto_oficial=fonte, texto_limpo=texto, texto_original=texto,
            hash_conteudo=hash_conteudo(texto), fonte="Fonte oficial fictícia",
            status="NOVO", relevancia=relevancia, motivos_relevancia="Teste fictício",
        ).returning(atos_legislativos.c.id)).scalar_one()
        versao_id = conexao.execute(insert(versoes_ato).values(
            ato_id=ato_id, hash_conteudo=hash_conteudo(texto),
            texto_original=texto, texto_limpo=texto,
        ).returning(versoes_ato.c.id)).scalar_one()
    return ato_id, versao_id


def contagem(repo, tabela):
    with repo.engine.connect() as conexao:
        return conexao.execute(select(func.count()).select_from(tabela)).scalar_one()


def test_dry_run_sem_escrita(repo_sqlite, capsys):
    inserir_ato(repo_sqlite, "NCM 2202.10.00: alíquota de 19% no art. 8º.")
    assert executar(repo_sqlite, dry_run=True) == (1, 1, 0)
    saida = capsys.readouterr().out
    assert "Regras candidatas: 1" in saida and "Trecho" in saida
    assert contagem(repo_sqlite, regras_extraidas) == 0
    assert contagem(repo_sqlite, processamentos_extracao) == 0


def test_dry_run_ncm_procedimental_mostra_codigo_e_nao_escreve(repo_sqlite, capsys):
    texto = (
        "Art. 2º No caso de importação de nafta não petroquímica classificada na "
        "NCM/SH 2710.12.49, deve ser exigida a manifestação do Fisco para fins de ICMS-ST."
    )
    inserir_ato(repo_sqlite, texto)
    executar(repo_sqlite, dry_run=True)
    saida = capsys.readouterr().out
    for esperado in (
        "2710.12.49", "27101249", "nafta não petroquímica",
        "NCMs encontrados no texto completo: 1", "NCMs exatos encontrados: 1",
        "Prefixos NCM encontrados: 0", "NCMs em regras materiais: 0",
        "NCMs em dispositivos procedimentais: 1",
        "Regras elegíveis para consulta NCM: 0",
        "NCMs detectados mas não elegíveis: 1",
    ):
        assert esperado in saida
    assert contagem(repo_sqlite, regras_extraidas) == 0
    assert contagem(repo_sqlite, evidencias_extracao) == 0
    assert contagem(repo_sqlite, processamentos_extracao) == 0


def test_ncm_procedimental_persistido_com_ato_versao_url_e_offsets(repo_sqlite):
    texto = (
        "Art. 2º Importação de nafta não petroquímica classificada na NCM/SH 2710.12.49; "
        "manifestação do Fisco exigida."
    )
    ato_id, versao_id = inserir_ato(repo_sqlite, texto)
    executar(repo_sqlite)
    with repo_sqlite.engine.connect() as conexao:
        linha = conexao.execute(select(
            regras_extraidas.c.ato_id, regras_extraidas.c.versao_ato_id,
            regras_extraidas.c.ncm_original, regras_extraidas.c.ncm_chave,
            regras_extraidas.c.descricao_proxima_ncm,
            regras_extraidas.c.tipo_correspondencia, regras_extraidas.c.elegivel_consulta_ncm,
            atos_legislativos.c.url_texto_oficial,
        ).join(atos_legislativos, regras_extraidas.c.ato_id == atos_legislativos.c.id)).one()
        evidencias = conexao.execute(select(evidencias_extracao)).mappings().all()
    assert linha == (ato_id, versao_id, "2710.12.49", "27101249", "nafta não petroquímica",
                     "EXATO", "NAO", "https://goias.gov.br/ato")
    assert any(e["tipo_evidencia"] == "NCM" for e in evidencias)
    assert all(texto[e["posicao_inicio"]:e["posicao_fim"]] == e["texto_origem"]
               for e in evidencias)


def test_execucao_normal_idempotencia_e_evidencias(repo_sqlite):
    texto = "NCM 2202.10.00: alíquota de 19% no art. 8º."
    ato_id, versao_id = inserir_ato(repo_sqlite, texto)
    assert executar(repo_sqlite) == (1, 1, 0)
    assert executar(repo_sqlite) == (1, 0, 1)
    assert contagem(repo_sqlite, regras_extraidas) == 1
    assert contagem(repo_sqlite, evidencias_extracao) >= 3
    with repo_sqlite.engine.connect() as conexao:
        regra = conexao.execute(select(regras_extraidas)).mappings().one()
        evidencias = conexao.execute(select(evidencias_extracao)).mappings().all()
    assert regra["ato_id"] == ato_id and regra["versao_ato_id"] == versao_id
    assert regra["extrator_versao"] == EXTRACTOR_VERSION
    assert regra["trecho_origem"] == texto
    assert all(e["regra_extraida_id"] == regra["id"] for e in evidencias)
    assert all(texto[e["posicao_inicio"]:e["posicao_fim"]] == e["texto_origem"] for e in evidencias)


def test_nova_versao_extrator_preserva_historico(repo_sqlite):
    texto = "NCM 2202.10.00: alíquota de 19% no art. 8º."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    regras = extrair_regras(texto)
    assert repo_sqlite.salvar(ato, regras, "2.0.0") == (1, [])
    assert repo_sqlite.salvar(ato, regras, "2.1.0") == (1, [])
    assert contagem(repo_sqlite, regras_extraidas) == 2


def test_nova_versao_ato_preserva_historico(repo_sqlite):
    original = "NCM 2202.10.00: alíquota de 19% no art. 8º."
    ato_id, _ = inserir_ato(repo_sqlite, original)
    executar(repo_sqlite)
    atualizado = "NCM 2202.10.00: alíquota de 7% no art. 8º."
    with repo_sqlite.engine.begin() as conexao:
        conexao.execute(atos_legislativos.update().where(atos_legislativos.c.id == ato_id).values(
            hash_conteudo=hash_conteudo(atualizado), texto_limpo=atualizado, texto_original=atualizado))
        conexao.execute(insert(versoes_ato).values(
            ato_id=ato_id, hash_conteudo=hash_conteudo(atualizado),
            texto_original=atualizado, texto_limpo=atualizado))
    assert executar(repo_sqlite) == (1, 1, 0)
    assert contagem(repo_sqlite, regras_extraidas) == 2


def test_sem_regra_nao_reprocessa(repo_sqlite):
    inserir_ato(repo_sqlite, "Texto administrativo fictício sem conteúdo fiscal.")
    assert executar(repo_sqlite) == (1, 0, 0)
    assert executar(repo_sqlite) == (1, 0, 1)
    assert contagem(repo_sqlite, regras_extraidas) == 0


def test_falha_em_regra_preserva_outras_e_permite_retentativa(repo_sqlite):
    texto = "NCM 2202.10.00: alíquota de 19% no art. 8º.\nNCM 2202.20.00: alíquota de 7% no art. 9º."
    inserir_ato(repo_sqlite, texto)
    ato = repo_sqlite.listar_atos()[0]
    regras = extrair_regras(texto)
    regras[0].confianca = "INVALIDA"
    gravadas, erros = repo_sqlite.salvar(ato, regras)
    assert gravadas == 1 and erros
    assert contagem(repo_sqlite, regras_extraidas) == 1
    regras[0].confianca = "ALTA"
    assert repo_sqlite.salvar(ato, regras) == (1, [])
    assert contagem(repo_sqlite, regras_extraidas) == 2


def test_filtros_de_ato_relevancia_e_fonte(repo_sqlite):
    alto, _ = inserir_ato(repo_sqlite, "NCM 2202.10.00: alíquota de 19%.")
    medio, _ = inserir_ato(repo_sqlite, "NCM 2202.20.00: alíquota de 7%.", relevancia="MEDIA")
    inserir_ato(repo_sqlite, "NCM 2202.30.00: alíquota de 5%.", relevancia="BAIXA")
    inserir_ato(repo_sqlite, "NCM 2202.40.00: alíquota de 3%.", fonte="https://exemplo.invalid/ato")
    assert [a.id for a in repo_sqlite.listar_atos(relevancia="ALTA")] == [alto]
    assert [a.id for a in repo_sqlite.listar_atos(relevancia="MEDIA")] == [medio]
    assert repo_sqlite.listar_atos(ato_id=medio, relevancia="ALTA") == []


def test_painel_pendentes_somente_leitura(repo_sqlite):
    inserir_ato(repo_sqlite, "NCM 2202.10.00: alíquota de 19% no art. 8º.")
    executar(repo_sqlite)
    pendentes = repo_sqlite.pendentes()
    assert len(pendentes) == 1
    assert pendentes[0]["ncm_chave"] == "22021000"
    assert pendentes[0]["status_revisao"] == "PENDENTE"

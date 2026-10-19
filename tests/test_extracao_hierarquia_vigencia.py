"""Etapa 3.2.1: excertos identificados no relatório e controles fictícios.

HTML mínimo reproduz a formatação dos parágrafos citados; não representa
leitura integral dos decretos. O calendário é informação fornecida pelo
usuário; as frases de ligação dos testes são sintéticas, sem efeito fiscal.
"""

from datetime import date

import pytest

from updater.extracao_fiscal import extrair_regras
from updater.normalizacao import limpar_html


def extrair_html(html):
    texto = limpar_html(html)
    regras = extrair_regras(texto, html)
    assert regras
    for regra in regras:
        assert regra.trecho_origem == texto[regra.inicio_trecho:regra.fim_trecho]
        assert regra.status_revisao == "PENDENTE"
        for evidencia in regra.evidencias:
            assert texto[evidencia.posicao_inicio:evidencia.posicao_fim] == evidencia.texto_origem
    return regras


def test_artigo_251c_nao_e_substituido_pela_remissao_251a():
    # RCTE p8683/p8686; relatório H02.
    html = (
        '<p>Art. 251-C. O arquivo digital da DC-e somente pode ser utilizado para '
        'acobertar o transporte das operações a que se refere o caput do '
        '<a>art. 251-A</a> deste Regulamento após ter seu uso autorizado pela administração tributária.</p>'
        '<p>§ 3º Fica dispensada a guarda do arquivo digital da DC-e '
        'desde que a DC-e esteja autorizada pela administração tributária.</p>'
    )
    regras = extrair_html(html)
    guarda = next(r for r in regras if "dispensada a guarda" in r.trecho_origem)
    assert guarda.artigo == "251-C" and guarda.paragrafo == "3"
    assert all(r.elegivel_consulta_ncm == "NAO" for r in regras)
    assert any(e.tipo_evidencia == "REFERENCIA_NORMATIVA" and "251-A" in e.texto_origem
               for r in regras for e in r.evidencias)


def test_nota_alteradora_nao_troca_artigo_6_pelo_artigo_1():
    # Anexo IX p385/p1899/p1900/p1911; relatório H01/H04.
    html = (
        '<h2>ANEXO IX</h2><p>Art. 6º São isentos do ICMS:</p>'
        '<p class="NovaRedao">CONFERIDA NOVA REDAÇÃO AO CAPUT DO INCISO CXLIII DO ART. 6º '
        'PELO <a>ART. 1º</a> DO DECRETO Nº 10.948, DE 03.07.26 - VIGÊNCIA: 03.07.26</p>'
        '<p>CXLIII - a operação interna com óleo diesel destinado à empresa de transporte coletivo '
        'detentora de contrato de concessão celebrado com a Companhia Metropolitana de Transportes '
        'Coletivos - CMTC e às empresas concessionárias do serviço de transporte coletivo no '
        'Município de Anápolis, ficando mantido o crédito e observado o seguinte:</p>'
        '<p>d) a utilização do benefício fica condicionada a celebração de Termo de Acordo '
        'de Regime Especial com a Secretaria de Estado da Fazenda, no qual serão estabelecidas '
        'as regras de utilização do benefício;</p>'
    )
    regras = extrair_html(html)
    tare = next(r for r in regras if "celebração" in r.trecho_origem)
    assert (tare.anexo, tare.artigo, tare.inciso, tare.alinea) == ("IX", "6", "CXLIII", "d")
    assert tare.grupo_regra_id is None  # Caput do inciso ainda exige composição/revisão.
    assert tare.elegivel_consulta_ncm == "NAO"


@pytest.mark.parametrize("sufixo", ["B", "C", "D"])
def test_sufixo_de_paragrafo_nao_se_perde(sufixo):
    # RCTE art. 76, §§ 3º-B/C/D; relatório H03. Conteúdo genérico fictício.
    regras = extrair_html(
        f'<p>Art. 76.</p><p>§ 3º-{sufixo} Fica dispensada a exigência da GLME '
        'na hipótese fictícia desde que atendidos os requisitos documentais.</p>'
    )
    regra, = regras
    assert (regra.artigo, regra.paragrafo) == ("76", f"3-{sufixo}")
    assert regra.elegivel_consulta_ncm == "NAO"


def test_condicao_251h_inteira_inclui_negacao_do_transporte():
    # RCTE p8702; relatório H04. A quebra decorre de span, não de outro dispositivo.
    html = (
        '<p>Art. 251-H. Em prazo não superior a vinte e quatro horas, contado do momento '
        'em que foi concedida a autorização pela administração tributária, o usuário emitente '
        'pode solicitar o cancelamento da respectiva DC-e, desde que '
        '<span>não se tenha iniciado o transporte</span> '
        '(Ajuste SINIEF 05/21, cláusula décima primeira).</p>'
    )
    regras = extrair_html(html)
    condicao, = [r for r in regras if r.condicoes_texto and "desde que" in r.condicoes_texto]
    assert "não se tenha iniciado o transporte" in condicao.condicoes_texto
    assert condicao.artigo == "251-H"
    assert condicao.elegivel_consulta_ncm == "NAO"


@pytest.mark.parametrize("fim", [
    "31 de outubro de 1999", "31 de dezembro de 2000", "30 de abril de 2004",
    "30 de julho de 2004", "31 de outubro de 2004",
])
def test_prazo_de_protocolo_do_relatorio_nao_vira_vigencia_fim(fim):
    # Anexo IX p2367–2372; relatório T03. Não é regra vigente para cadastro.
    texto = f"a) a isenção aplica-se aos pedidos protocolados até {fim}"
    regra, = extrair_regras(texto)
    assert regra.vigencia_fim is None
    assert any(e.tipo_evidencia == "PRAZO_OPERACIONAL" for e in regra.evidencias)
    assert regra.elegivel_consulta_ncm == "NAO" and regra.status_revisao == "PENDENTE"


@pytest.mark.parametrize("obrigacao", ["protocolo", "cancelamento", "entrega", "cumprimento da obrigação"])
def test_prazo_operacional_nao_encerra_beneficio_ficticio(obrigacao):
    texto = (
        "Art. 1º Fica isento do ICMS o produto fictício alfa, "
        f"desde que o prazo para {obrigacao} seja atendido até 31 de dezembro de 2026."
    )
    regra, = extrair_regras(texto)
    assert regra.vigencia_fim is None
    assert obrigacao in regra.condicoes_texto
    assert regra.elegivel_consolidacao == "SIM" and regra.elegivel_consulta_ncm == "NAO"


def test_publicacao_e_entrada_em_vigor_nao_viram_vigencia_de_tratamento():
    # Data de publicação informada pelo usuário; frase de entrada em vigor fictícia.
    regras = extrair_regras("Publicado em 08/07/2026.\nEntra em vigor em 8 de julho de 2026.")
    assert regras
    tipos = {e.tipo_evidencia for r in regras for e in r.evidencias}
    assert {"DATA_PUBLICACAO", "ENTRADA_VIGOR"} <= tipos
    assert all(r.vigencia_inicio is None and r.vigencia_fim is None
               and r.elegivel_consulta_ncm == "NAO" for r in regras)


@pytest.mark.parametrize("com_ncm", [False, True])
def test_calendario_informado_do_10951_preserva_pendencia_sem_propagar_datas(com_ncm):
    # Não reproduz o art. 9º oficial. Só usa o calendário informado pelo usuário.
    html = ''.join(f'<p>Art. {i}º Fica isento do ICMS o '
                   f'{"NCM 1234.56.78" if com_ncm and i == 6 else f"produto fictício número {i}"}.</p>'
                   for i in range(1, 9)) + (
        '<p>Art. 9º Produção de efeitos por dispositivo, conforme calendário informado para teste:</p>'
        '<p>I - Art. 5º: 09/12/2025.</p>'
        '<p>II - Arts. 2º, 3º e 7º: 01/02/2026.</p>'
        '<p>III - Art. 1º: 06/04/2026.</p>'
        '<p>IV - Arts. 4º e 8º: 04/05/2026.</p>'
        '<p>Publicado em 08/07/2026.</p>'
    )
    regras = extrair_html(html)
    materiais = [r for r in regras if r.papel_dispositivo == "REGRA_MATERIAL"]
    assert len(materiais) == 8
    assert all(r.vigencia_inicio is None and r.vigencia_fim is None
               and r.elegivel_consulta_ncm == "NAO" for r in materiais)
    assert all(r.status_revisao == "PENDENTE" for r in regras)
    valores = {e.valor_extraido for r in regras for e in r.evidencias}
    assert {"2025-12-09", "2026-02-01", "2026-04-06", "2026-05-04", "2026-07-08"} <= valores
    assert any("pendente" in a.lower() and "tempor" in a.lower() for r in regras for a in r.alertas)


def test_efeitos_locais_explicitos_preservam_periodo_do_tratamento():
    regra, = extrair_regras(
        "Art. 1º Fica isento do ICMS o produto fictício alfa; "
        "produz efeitos a partir de 1 de março de 2026 até 31 de dezembro de 2026."
    )
    assert regra.vigencia_inicio == date(2026, 3, 1)
    assert regra.vigencia_fim == date(2026, 12, 31)
    assert any(e.tipo_evidencia == "PRODUCAO_EFEITOS" for e in regra.evidencias)


def test_condicao_com_marcador_em_span_segue_o_proprio_artigo():
    regras = extrair_html(
        '<p>Art. 1º Fica isento do ICMS o NCM 1234.56.78.</p>'
        '<p><span>I -</span> <span>Para ser beneficiário da isenção deve celebrar termo de acordo.</span></p>'
    )
    principal, condicao = regras
    assert condicao.grupo_regra_id == principal.grupo_regra_id
    assert (condicao.artigo, condicao.inciso) == ("1", "I")


def test_dois_artigos_no_mesmo_paragrafo_html_ficam_bloqueados():
    regras = extrair_html(
        '<p>Art. 1º Fica isento do ICMS o NCM 1234.56.78.<br>'
        'Art. 2º Fica isento do ICMS o NCM 2202.10.00.</p>'
    )
    assert all(r.elegivel_consulta_ncm == "NAO" and r.elegivel_consolidacao == "NAO" for r in regras)
    assert all(any(e.tipo_evidencia == "BLOQUEIO_FISCAL" for e in r.evidencias) for r in regras)


def test_hierarquia_completa_nao_herda_identificadores_citados():
    regras = extrair_html(
        '<h2>ANEXO XII</h2><p>Art. 76.</p>'
        '<p>§ 3º-D Fica dispensada a exigência da GLME:</p>'
        '<p>XX-A - desde que atendidos os requisitos do inciso LV do art. 6º do Anexo IX.</p>'
        '<p>b) deve celebrar termo de acordo para a hipótese fictícia.</p>'
        '<p>2.1. deve celebrar termo de acordo no caso fictício.</p>'
    )
    ultimo = regras[-1]
    assert (ultimo.anexo, ultimo.artigo, ultimo.paragrafo, ultimo.inciso, ultimo.alinea, ultimo.item) == (
        "XII", "76", "3-D", "XX-A", "b", "2.1")
    assert all(r.elegivel_consulta_ncm == "NAO" for r in regras)


def test_remissao_a_artigo_com_sufixo_preserva_associacao_inequivoca():
    texto = (
        "Art. 2º-A Fica isento do ICMS o produto fictício alfa.\n"
        "Art. 3º Deve celebrar termo de acordo para o benefício previsto no art. 2º-A deste ato."
    )
    principal, condicao = extrair_regras(texto)
    assert principal.artigo == "2-A" and condicao.artigo == "3"
    assert principal.grupo_regra_id and principal.grupo_regra_id == condicao.grupo_regra_id


def test_efeitos_de_outro_artigo_no_mesmo_bloco_nao_datam_regra_principal():
    regra, = extrair_regras(
        "Art. 1º Fica isento do ICMS o NCM 1234.56.78; "
        "quanto ao art. 5º, produz efeitos a partir de 9 de dezembro de 2025."
    )
    assert regra.vigencia_inicio is None and regra.elegivel_consulta_ncm == "NAO"
    assert any(e.tipo_evidencia == "PENDENCIA_TEMPORAL" for e in regra.evidencias)


def test_qualificacao_operacional_posterior_a_data_nao_encerra_tratamento():
    regra, = extrair_regras(
        "Art. 1º Fica isento do ICMS o produto fictício alfa; "
        "produz efeitos a partir de 1 de janeiro de 2026; "
        "até 31 de dezembro de 2026, data limite para protocolo do pedido fictício."
    )
    assert regra.vigencia_inicio == date(2026, 1, 1)
    assert regra.vigencia_fim is None
    assert "protocolo" in regra.condicoes_texto

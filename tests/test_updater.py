"""Monitoramento com documentos fictícios e respostas HTTP simuladas."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from hashlib import sha256

import httpx
import pytest

from updater.casacivil_go import buscar_texto_oficial
from updater.economia_go import descobrir_atos
from updater.executor import _mostrar_resumo, coletar_ato, executar
from updater.foco_ncm import classificar_foco_ncm
from updater.fontes import ClienteOficial, ErroColeta
from updater.modelos import AVISO_DIVERGENCIA, AtoColetado, AtoDescoberto, ConteudoOficial
from updater.migracao import ERRO_ANTIGO_DIVERGENCIA, migrar_datas_monitoramento, migrar_prioridade_ncm
from updater.normalizacao import identificar_ato, limpar_html, normalizar_numero_ato
from updater.persistencia import RepositorioMonitoramento, ResumoExecucao, hash_conteudo
from updater.relevancia import classificar_relevancia
from updater.schema import metadata

URL_POST = "https://goias.gov.br/economia/lista-ficticia/"
URL_ARQUIVO = "https://goias.gov.br/economia/ato-ficticio.html"
URL_CASA = "https://legisla.casacivil.go.gov.br/api/v2/pesquisa/legislacoes/999"
TITULO = "DECRETO Nº 1.234, DE 2 DE MARÇO DE 2025"
EMENTA = "Altera o Anexo IX e dispõe sobre ICMS em exemplo fictício."


def ato_ficticio() -> AtoDescoberto:
    return AtoDescoberto("DECRETO", "1234", 2025, date(2025, 3, 2), TITULO, EMENTA, URL_POST, URL_ARQUIVO)


def coleta_ficticia(texto="Art. 1º - NCM 0012.34.56; ICMS e Anexo IX.") -> AtoColetado:
    return AtoColetado(
        ato_ficticio(), ConteudoOficial(URL_CASA, f"<p>{texto}</p>", texto),
        classificar_relevancia(texto),
    )


def cliente_ficticio(*, falha=None, vazio=False) -> ClienteOficial:
    def responder(request: httpx.Request) -> httpx.Response:
        if falha == "timeout":
            raise httpx.ReadTimeout("tempo esgotado")
        if falha == "http":
            return httpx.Response(503, request=request)
        caminho = request.url.path
        if caminho.endswith("/categoria/institucional/legislacao/"):
            conteudo = f'<article class="category-tributaria"><h2 class="entry-title"><a href="{URL_POST}">Lista fictícia</a></h2></article>'
            return httpx.Response(200, text=conteudo, headers={"content-type": "text/html"}, request=request)
        if caminho.endswith("/lista-ficticia/"):
            conteudo = f'<article><section class="entry-content"><p><a href="{URL_ARQUIVO}">{TITULO}</a><br>{EMENTA}</p></section></article>'
            return httpx.Response(200, text=conteudo, headers={"content-type": "text/html"}, request=request)
        if caminho.endswith("/pesquisa/legislacoes"):
            return httpx.Response(200, json={"resultados": [{
                "id": 999, "ano": 2025, "numero": "1.234",
                "tipo_legislacao": {"nome": "Decreto Numerado"},
                "diarios": [{"data_diario": "03/03/2025"}],
            }]}, request=request)
        if caminho.endswith("/pesquisa/legislacoes/999"):
            return httpx.Response(200, json={
                "id": 999, "ano": 2025, "numero": "1.234",
                "tipo_legislacao": {"nome": "Decreto Numerado"},
                "data_legislacao": "2025-03-02",
                "conteudo": "" if vazio else f"<p>{TITULO}</p><p>Art. 1º - NCM 0012.34.56; ICMS e Anexo IX.</p>",
            }, request=request)
        return httpx.Response(404, request=request)

    return ClienteOficial(httpx.Client(transport=httpx.MockTransport(responder)), tentativas=1)


class ResultadoFalso:
    def __init__(self, valor):
        self.valor = valor

    def mappings(self):
        return self

    def first(self):
        return self.valor

    def scalar_one(self):
        return self.valor


class EngineMonitoramentoFalso:
    """Simula as transações SQL das tabelas novas sem usar SQLite."""

    def __init__(self):
        self.atos = {}
        self.versoes = []
        self.execucoes = []

    @contextmanager
    def begin(self):
        atos, versoes, execucoes = deepcopy((self.atos, self.versoes, self.execucoes))

        class Conexao:
            def execute(self, comando):
                params = comando.compile().params
                nome = comando.table.name if hasattr(comando, "table") else "atos_legislativos"
                if comando.is_select:
                    chave = (params["tipo_ato_1"], params["numero_1"], params["ano_1"])
                    return ResultadoFalso(atos.get(chave))
                if comando.is_insert and nome == "atos_legislativos":
                    chave = (params["tipo_ato"], params["numero"], params["ano"])
                    params["id"] = len(atos) + 1
                    atos[chave] = params
                    return ResultadoFalso(params["id"])
                if comando.is_update:
                    registro = next(a for a in atos.values() if a["id"] == params["id_1"])
                    registro.update({k: v for k, v in params.items() if k != "id_1"})
                elif nome == "versoes_ato":
                    versoes.append(params)
                elif nome == "monitoramento_legislativo":
                    execucoes.append(params)
                return ResultadoFalso(None)

        yield Conexao()
        self.atos, self.versoes, self.execucoes = atos, versoes, execucoes


def test_normalizacao_numero_e_identificacao():
    assert normalizar_numero_ato("10.986", 2026) == "10986"
    assert normalizar_numero_ato("074/2026 SIF", 2026) == "74-SIF"
    assert normalizar_numero_ato("092 - SIF", 2026) == "92-SIF"
    ato = identificar_ato("INSTRUÇÃO NORMATIVA Nº 112/SIF, DE 10 DE SETEMBRO DE 2026", "Ementa fictícia", URL_POST, URL_ARQUIVO)
    assert ato and (ato.numero, ato.ano, ato.data_descoberta) == ("112-SIF", 2026, date(2026, 9, 10))
    assert ato.data_publicacao is None


@pytest.mark.parametrize(("texto", "esperado"), [
    ("ICMS e Anexo IX", "ALTA"), ("ICMS", "MEDIA"), ("Assunto administrativo fictício", "BAIXA"),
])
def test_classificacao_relevancia(texto, esperado):
    resultado = classificar_relevancia(texto)
    assert resultado.relevancia == esperado
    assert resultado.motivos


def test_sinais_de_ncm_e_mercadoria_priorizam_triagem():
    assert classificar_relevancia("NCM/SH 2202.10.00 com isenção do ICMS").relevancia == "ALTA"
    assert classificar_foco_ncm("NCM/SH 2202.10.00: isenção do ICMS.").relevancia == "MUITO_ALTA"
    assert classificar_foco_ncm("Crédito outorgado genérico para programa estadual").relevancia == "SEM_INDICIO"


@pytest.mark.parametrize(("texto", "nivel", "exato", "prefixo", "material", "procedimental"), [
    ("Ato administrativo de rotina.", "SEM_INDICIO", "NAO", "NAO", "NAO", False),
    ("NCM/SH 2710.12.49: manifestação do Fisco para ICMS-ST.", "ALTA", "SIM", "NAO", "NAO", True),
    ("NCM 2202.10.00 sujeito a ICMS.", "ALTA", "SIM", "NAO", "NAO", False),
    ("NCM 2202.10.00: isenção do ICMS.", "MUITO_ALTA", "SIM", "NAO", "SIM", False),
    ("NCM 2202.10.00: redução de base de cálculo do ICMS.", "MUITO_ALTA", "SIM", "NAO", "SIM", False),
    ("posição 2202 da NCM: ICMS.", "MEDIA", "NAO", "SIM", "NAO", False),
    ("subposição 2202.10 da NCM: ICMS.", "MEDIA", "NAO", "SIM", "NAO", False),
])
def test_prioridade_ncm_no_texto_oficial(texto, nivel, exato, prefixo, material, procedimental):
    prioridade = classificar_foco_ncm(texto)
    assert (prioridade.relevancia, prioridade.possui_ncm_explicito,
            prioridade.possui_prefixo_ncm, prioridade.possui_termo_material_icms,
            prioridade.apenas_procedimental) == (nivel, exato, prefixo, material, procedimental)


def test_credito_generico_distante_do_ncm_procedimental_nao_sobe_prioridade():
    texto = ("NCM/SH 2710.12.49: manifestação do Fisco para ICMS-ST.\n"
             "Introdução geral.\n" * 8 +
             "Crédito outorgado para programa empresarial sem mercadoria identificada.")
    prioridade = classificar_foco_ncm(texto)
    assert prioridade.relevancia == "ALTA"
    assert prioridade.possui_termo_material_icms == "NAO"


def test_ncm_sem_rotulo_e_nomenclatura_geram_indicios_sem_inferir_codigo():
    assert classificar_foco_ncm("Mercadoria 2202.10.00: ICMS.").ncms == ("22021000",)
    assert classificar_foco_ncm("Classificação fiscal 22021000 para ICMS.").ncms == ("22021000",)
    sem_codigo = classificar_foco_ncm("Nomenclatura Comum do Mercosul e ICMS.")
    assert sem_codigo.relevancia == "MEDIA" and sem_codigo.ncms == ()
    assert classificar_foco_ncm("Programa empresarial e crédito outorgado do ICMS.").relevancia == "SEM_INDICIO"


def test_anexo_em_tabela_mantem_ncm_e_tratamento_no_contexto():
    html = ("<h1>Anexo IX</h1><table><tr><th>NCM</th><th>Tratamento</th></tr>"
            "<tr><td>2202.10.00</td><td>Isenção do ICMS</td></tr></table>")
    prioridade = classificar_foco_ncm(limpar_html(html), html_original=html)
    assert prioridade.relevancia == "MUITO_ALTA"
    assert prioridade.ncms == ("22021000",)


def test_marcacao_consolidado_exige_indicacao_explicita_no_cabecalho():
    from updater.casacivil_go import _indicacao_consolidado

    assert _indicacao_consolidado("DECRETO 123\nTEXTO CONSOLIDADO\nArt. 1º") == "SIM"
    assert _indicacao_consolidado("Decreto que altera texto consolidado anterior.") == "NAO"
    assert _indicacao_consolidado("Art. 1º Sem indicação de consolidação.") == "NAO"


def test_limpeza_preserva_dispositivos_ncm_e_percentual():
    texto = limpar_html("<nav>Menu</nav><p>Art. 1º, inciso II: NCM 0012.34.56 e 7%.</p><script>ruido()</script>")
    assert "Art. 1º, inciso II: NCM 0012.34.56 e 7%." in texto
    assert "Menu" not in texto and "ruido" not in texto


def test_descoberta_filtro_ano_e_limite():
    cliente = cliente_ficticio()
    assert len(descobrir_atos(cliente, ano=2025, limite=1)) == 1
    assert descobrir_atos(cliente, ano=2026, limite=1) == []


def test_casa_civil_valida_identidade_e_preserva_url_oficial():
    conteudo = buscar_texto_oficial(ato_ficticio(), cliente_ficticio())
    assert conteudo and conteudo.url == URL_CASA
    assert conteudo.data_ato == date(2025, 3, 2)
    assert conteudo.data_publicacao == date(2025, 3, 3)
    assert "Art. 1º" in conteudo.texto_limpo
    assert "<p>" in conteudo.texto_original


def test_datas_iguais_nao_geram_divergencia_nem_erro():
    coleta = coletar_ato(ato_ficticio(), cliente_ficticio())
    assert coleta.conteudo and coleta.conteudo.data_ato == date(2025, 3, 2)
    assert coleta.descoberto.data_descoberta == date(2025, 3, 2)
    assert coleta.conteudo.data_publicacao == date(2025, 3, 3)
    assert coleta.divergencia_data == "NAO"
    assert coleta.advertencias == () and coleta.erro is None
    assert coleta.status == "NOVO"


def test_casa_civil_nao_confunde_tipos_de_lei():
    from updater.casacivil_go import _tipo_confere

    assert _tipo_confere("LEI", "Lei Ordinária")
    assert not _tipo_confere("LEI", "Lei Complementar")


@pytest.mark.parametrize("falha", ["http", "timeout"])
def test_erro_http_e_timeout(falha):
    cliente = cliente_ficticio(falha=falha)
    with pytest.raises(ErroColeta):
        cliente.html("https://goias.gov.br/economia/categoria/institucional/legislacao/")


def test_html_vazio_registra_erro():
    cliente = cliente_ficticio(vazio=True)
    with pytest.raises(ErroColeta, match="Texto integral ausente"):
        buscar_texto_oficial(ato_ficticio(), cliente)


def test_pagina_html_vazia_e_recusada():
    cliente = ClienteOficial(httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="  ", headers={"content-type": "text/html"}, request=request)
    )), tentativas=1)
    with pytest.raises(ErroColeta, match="Página oficial vazia"):
        cliente.html(URL_POST)


def test_doc_oficial_convertido_e_divergencia_de_data_sinalizada(monkeypatch, capsys):
    assinatura = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def responder(request):
        if request.url.path.endswith("/pesquisa/legislacoes"):
            return httpx.Response(200, json={"resultados": []}, request=request)
        return httpx.Response(200, content=assinatura + b"ficticio",
                              headers={"content-type": "application/msword"}, request=request)

    texto = "DECRETO Nº 1.234, DE 1 DE MARÇO DE 2025\n(PUBLICADO NO DOE de 03.03.25)\nArt. 1º - NCM 0012.34.56; ICMS e Anexo IX."
    monkeypatch.setattr("updater.casacivil_go.extrair_doc", lambda _: texto)
    ato = AtoDescoberto("DECRETO", "1234", 2025, date(2025, 3, 2), TITULO, EMENTA,
                       URL_POST, "https://goias.gov.br/economia/ato-ficticio.doc")
    cliente = ClienteOficial(httpx.Client(transport=httpx.MockTransport(responder)), tentativas=1)
    coleta = coletar_ato(ato, cliente)
    assert coleta.conteudo and coleta.conteudo.data_ato == date(2025, 3, 1)
    assert coleta.conteudo.data_publicacao == date(2025, 3, 3)
    assert coleta.descoberto.data_descoberta == date(2025, 3, 2)
    assert coleta.divergencia_data == "SIM"
    assert coleta.advertencias and coleta.erro is None and coleta.status == "NOVO"
    assert coleta.classificacao.relevancia == "ALTA"
    assert "0012.34.56" in coleta.conteudo.texto_limpo
    engine = EngineMonitoramentoFalso()
    assert RepositorioMonitoramento(engine).salvar_ato(coleta) == "novo"
    assert len(engine.versoes) == 1 and len(engine.atos) == 1
    salvo = engine.atos[("DECRETO", "1234", 2025)]
    assert (salvo["data_ato"], salvo["data_publicacao"], salvo["data_descoberta"]) == (
        date(2025, 3, 1), date(2025, 3, 3), date(2025, 3, 2),
    )
    assert salvo["divergencia_data"] == "SIM"
    assert "Divergência" in salvo["advertencia_data"]
    _mostrar_resumo(ResumoExecucao(encontrada=1, sem_comparacao=1), [coleta], ["candidato"], True)
    saida = capsys.readouterr().out
    assert "DECRETO 1234/2025 | ALTA | CANDIDATO" in saida
    assert "Aviso: Divergência de datas" in saida
    assert "Data do ato: 01/03/2025" in saida
    assert "Data da descoberta: 02/03/2025" in saida
    assert "Data de publicação: 03/03/2025" in saida


def test_doc_sem_conversor_registra_erro(monkeypatch):
    from updater.documentos import extrair_doc

    monkeypatch.setattr("updater.documentos.shutil.which", lambda _: None)
    with pytest.raises(ErroColeta, match="Conversor"):
        extrair_doc(b"arquivo ficticio")


def test_falha_real_de_download_continua_erro():
    coleta = coletar_ato(ato_ficticio(), cliente_ficticio(falha="http"))
    assert coleta.conteudo is None
    assert coleta.status == "ERRO" and coleta.erro
    assert coleta.divergencia_data == "NAO" and not coleta.advertencias


def test_url_nao_oficial_recusada():
    with pytest.raises(ErroColeta, match="URL fora"):
        cliente_ficticio().html("https://exemplo.invalid/ato")


def test_redirect_externo_recusado_antes_do_download():
    chamadas = []

    def responder(request):
        chamadas.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://exemplo.invalid/ato"}, request=request)

    cliente = ClienteOficial(httpx.Client(transport=httpx.MockTransport(responder)), tentativas=1)
    with pytest.raises(ErroColeta, match="URL fora"):
        cliente.html(URL_POST)
    assert chamadas == [URL_POST]


def test_dry_run_sem_escrita():
    class RepositorioEspiao:
        def prever_operacao(self, *_):
            return "novo"

        def salvar_ato(self, *_):
            raise AssertionError("dry-run não deve gravar atos")

        def registrar_execucao(self, *_):
            raise AssertionError("dry-run não deve gravar execuções")

    resumo, coletas, operacoes = executar(cliente_ficticio(), repositorio=RepositorioEspiao(), dry_run=True, limite=1)
    assert (resumo.encontrada, resumo.nova, resumo.erros) == (1, 1, 0)
    assert operacoes == ["novo"]
    assert len(coletas) == 1 and coletas[0].conteudo.url == URL_CASA


def test_foco_ncm_ordena_apos_ler_conteudo_e_dry_run_nao_escreve(monkeypatch, capsys):
    import updater.executor as modulo

    atos = [AtoDescoberto("DECRETO", str(numero), 2025, None, f"DECRETO {numero}",
                          "ementa genérica", URL_POST, URL_ARQUIVO) for numero in (1, 2, 3)]
    textos = {
        "1": "Programa empresarial de incentivo industrial.",
        "2": "NCM 2202.10.00: manifestação do Fisco para ICMS-ST.",
        "3": "NCM 2202.10.00: isenção do ICMS.",
    }
    monkeypatch.setattr(modulo, "descobrir_atos", lambda *_args, **_kwargs: atos)
    monkeypatch.setattr(modulo, "coletar_ato", lambda ato, _cliente: AtoColetado(
        ato, ConteudoOficial(URL_CASA, textos[ato.numero], textos[ato.numero]),
        classificar_relevancia(textos[ato.numero]),
        prioridade_ncm=classificar_foco_ncm(textos[ato.numero]),
    ))

    class RepositorioEspiao:
        def prever_operacao(self, *_):
            return "novo"

        def salvar_ato(self, *_):
            raise AssertionError("dry-run não pode gravar ato")

        def registrar_execucao(self, *_):
            raise AssertionError("dry-run não pode gravar monitoramento")

    resumo, coletas, operacoes = executar(cliente_ficticio(), repositorio=RepositorioEspiao(),
                                         dry_run=True, foco_ncm=True, limite=2)
    assert [coleta.descoberto.numero for coleta in coletas] == ["3", "2"]
    assert operacoes == ["novo", "novo"] and resumo.encontrada == 2
    assert resumo.descobertos_fonte == 3
    _mostrar_resumo(resumo, coletas, operacoes, True, True)
    saida = capsys.readouterr().out
    assert "Atos com NCM explícito: 2" in saida
    assert "Atos com NCM + termo material de ICMS: 1" in saida
    assert "Atos apenas procedimentais: 1" in saida
    assert "DRY-RUN: nenhuma escrita no banco." in saida


def test_descoberta_deduplica_e_pode_alcancar_ano_anterior_por_paginacao():
    categoria = "https://goias.gov.br/economia/categoria/institucional/legislacao/"
    proxima = "https://goias.gov.br/economia/categoria/institucional/legislacao/page/2/"
    post_antigo = "https://goias.gov.br/economia/post-antigo/"

    class ClientePaginas:
        def html(self, url):
            if url == categoria:
                return (f'<article class="category-tributaria"><h2 class="entry-title">'
                        f'<a href="{URL_POST}">Recentes</a></h2></article>'
                        f'<a class="next page-numbers" href="{proxima}">Próxima</a>')
            if url == proxima:
                return (f'<article class="category-tributaria"><h2 class="entry-title">'
                        f'<a href="{post_antigo}">Antigos</a></h2></article>')
            if url == URL_POST:
                return (f'<article><div class="entry-content"><p>'
                        f'<a href="{URL_ARQUIVO}">{TITULO}</a></p></div></article>')
            return ('<article><div class="entry-content">' + 2 * (
                '<p><a href="https://goias.gov.br/economia/ato-antigo.html">'
                'DECRETO Nº 123, DE 2 DE MARÇO DE 2020</a></p>') + '</div></article>')

    cliente = ClientePaginas()
    assert descobrir_atos(cliente, ano=2020, limite=10, max_paginas=1) == []
    antigos = descobrir_atos(cliente, ano=2020, limite=10, max_paginas=2)
    assert len(antigos) == 1 and antigos[0].ano == 2020


def test_metadados_ncm_atualizam_sem_duplicar_ato_e_preservam_versoes():
    engine = EngineMonitoramentoFalso()
    repo = RepositorioMonitoramento(engine)
    primeira = coleta_ficticia("NCM 2202.10.00: manifestação do Fisco para ICMS-ST.")
    assert repo.salvar_ato(primeira) == "novo"
    assert repo.salvar_ato(primeira) == "ignorado"
    segunda = coleta_ficticia("TEXTO CONSOLIDADO\nNCM 2202.10.00: isenção do ICMS.")
    segunda = AtoColetado(segunda.descoberto, ConteudoOficial(
        URL_CASA, segunda.conteudo.texto_original, segunda.conteudo.texto_limpo,
        texto_consolidado="SIM"), segunda.classificacao)
    assert repo.salvar_ato(segunda) == "atualizado"
    assert len(engine.atos) == 1 and len(engine.versoes) == 2
    salvo = engine.atos[("DECRETO", "1234", 2025)]
    assert salvo["relevancia_ncm"] == "MUITO_ALTA"
    assert salvo["quantidade_ncms_texto"] == 1
    assert salvo["possui_ncm_explicito"] == "SIM"
    assert salvo["possui_termo_material_icms"] == "SIM"
    assert salvo["texto_consolidado"] == "SIM"
    assert [v["url_origem"] for v in engine.versoes] == [URL_CASA, URL_CASA]
    assert [v["texto_consolidado"] for v in engine.versoes] == ["NAO", "SIM"]


def test_migracao_prioridade_ncm_e_aditiva_e_reexecutavel():
    class EngineEspiao:
        def __init__(self):
            self.comandos = []

        @contextmanager
        def begin(self):
            yield self

        def execute(self, comando):
            self.comandos.append(" ".join(str(comando).split()))

    engine = EngineEspiao()
    migrar_prioridade_ncm(engine)
    migrar_prioridade_ncm(engine)
    assert any("ADD COLUMN IF NOT EXISTS relevancia_ncm" in sql for sql in engine.comandos)
    assert any("ADD COLUMN IF NOT EXISTS url_origem" in sql for sql in engine.comandos)
    assert all("DROP " not in sql and "DELETE " not in sql for sql in engine.comandos)


def test_dry_run_sem_banco_nao_afirma_ato_novo():
    resumo, _, operacoes = executar(cliente_ficticio(), dry_run=True, limite=1)
    assert resumo.nova == 0 and resumo.sem_comparacao == 1
    assert operacoes == ["candidato"]


def test_previsao_dry_run_consulta_somente_leitura():
    class EngineLeitura:
        def __init__(self):
            self.atual = None
            self.consultas = 0

        @contextmanager
        def connect(self):
            engine = self

            class Conexao:
                def execute(self, comando):
                    assert comando.is_select
                    engine.consultas += 1
                    return ResultadoFalso(engine.atual)

            yield Conexao()

        def begin(self):
            raise AssertionError("previsão não pode abrir transação de escrita")

    engine = EngineLeitura()
    repo = RepositorioMonitoramento(engine)
    coleta = coleta_ficticia()
    assert repo.prever_operacao(coleta) == "novo"
    engine.atual = {"id": 1, "hash_conteudo": hash_conteudo(coleta.conteudo.texto_limpo)}
    assert repo.prever_operacao(coleta) == "ignorado"
    engine.atual = {"id": 1, "hash_conteudo": "0" * 64}
    assert repo.prever_operacao(coleta) == "atualizado"
    assert engine.consultas == 3


def test_previsao_dry_run_sem_texto_integral_nao_quebra():
    class EngineLeitura:
        @contextmanager
        def connect(self):
            class Conexao:
                def execute(self, comando):
                    assert comando.is_select
                    return ResultadoFalso({"id": 1, "hash_conteudo": None})
            yield Conexao()

    coleta = AtoColetado(ato_ficticio(), None, classificar_relevancia(""))
    assert RepositorioMonitoramento(EngineLeitura()).prever_operacao(coleta) == "ignorado"


def test_persistencia_nova_hash_igual_hash_alterado_e_sem_duplicar():
    engine = EngineMonitoramentoFalso()
    repo = RepositorioMonitoramento(engine)
    primeira = coleta_ficticia()
    assert repo.salvar_ato(primeira) == "novo"
    assert len(engine.atos) == 1 and len(engine.versoes) == 1
    assert repo.salvar_ato(primeira) == "ignorado"
    assert len(engine.atos) == 1 and len(engine.versoes) == 1
    alterada = coleta_ficticia("Art. 2º - texto fictício alterado; ICMS e Anexo IX.")
    assert repo.salvar_ato(alterada) == "atualizado"
    assert len(engine.versoes) == 2
    assert engine.versoes[0]["hash_conteudo"] == sha256(primeira.conteudo.texto_limpo.encode()).hexdigest()
    assert engine.versoes[1]["hash_conteudo"] == hash_conteudo(alterada.conteudo.texto_limpo)
    assert engine.atos[("DECRETO", "1234", 2025)]["url_texto_oficial"] == URL_CASA


def test_recoleta_com_mesmo_hash_corrige_erro_antigo_sem_nova_versao():
    engine = EngineMonitoramentoFalso()
    repo = RepositorioMonitoramento(engine)
    ato = ato_ficticio()
    conteudo = ConteudoOficial(
        URL_CASA, "<p>ICMS e Anexo IX.</p>", "ICMS e Anexo IX.",
        data_publicacao=date(2025, 3, 3), data_ato=date(2025, 3, 1),
    )
    coleta = AtoColetado(ato, conteudo, classificar_relevancia(conteudo.texto_limpo),
                         divergencia_data="SIM", advertencias=(AVISO_DIVERGENCIA,))
    assert repo.salvar_ato(coleta) == "novo"
    salvo = engine.atos[("DECRETO", "1234", 2025)]
    salvo["status"] = "ERRO"
    salvo["erro_coleta"] = ERRO_ANTIGO_DIVERGENCIA
    assert repo.salvar_ato(coleta) == "ignorado"
    salvo = engine.atos[("DECRETO", "1234", 2025)]
    assert salvo["status"] == "NOVO" and salvo["erro_coleta"] is None
    assert salvo["divergencia_data"] == "SIM"
    assert len(engine.versoes) == 1


def test_registro_de_execucao():
    engine = EngineMonitoramentoFalso()
    repo = RepositorioMonitoramento(engine)
    repo.registrar_execucao(ResumoExecucao(encontrada=3, nova=1, atualizada=1, ignorados=1), "Fonte oficial fictícia")
    assert len(engine.execucoes) == 1
    assert engine.execucoes[0]["quantidade_encontrada"] == 3


def test_execucao_normal_persiste_ato_e_resumo():
    engine = EngineMonitoramentoFalso()
    repo = RepositorioMonitoramento(engine)
    resumo, _, operacoes = executar(cliente_ficticio(), repositorio=repo, limite=1)
    assert resumo.nova == 1
    assert operacoes == ["novo"]
    assert len(engine.atos) == len(engine.versoes) == len(engine.execucoes) == 1
    assert set(metadata.tables) == {
        "atos_legislativos", "versoes_ato", "monitoramento_legislativo",
        "processamentos_extracao", "regras_extraidas",
        "evidencias_extracao", "regras_consolidadas", "relacoes_regras",
    }


def test_migracao_datas_preserva_registros_e_pode_repetir():
    class EngineLegadoFalso:
        def __init__(self):
            self.colunas = {"data_ato", "data_ato_documento", "data_publicacao"}
            self.linhas = [{
                "data_ato": date(2026, 9, 2),
                "data_ato_documento": date(2026, 9, 1),
                "data_publicacao": date(2026, 9, 3),
                "status": "ERRO", "relevancia": "ALTA",
                "erro_coleta": ERRO_ANTIGO_DIVERGENCIA,
                "hash_conteudo": "a" * 64,
            }]
            self.comandos = []

        @contextmanager
        def begin(self):
            engine = self

            class Conexao:
                def execute(self, comando, parametros=None):
                    sql = " ".join(str(comando).split())
                    engine.comandos.append(sql)
                    if sql.startswith("SELECT EXISTS"):
                        return ResultadoFalso(parametros["coluna"] in engine.colunas)
                    if "ADD COLUMN IF NOT EXISTS data_descoberta" in sql:
                        engine.colunas.add("data_descoberta")
                    elif "ADD COLUMN IF NOT EXISTS divergencia_data" in sql:
                        engine.colunas.add("divergencia_data")
                        for linha in engine.linhas:
                            linha["divergencia_data"] = "NAO"
                    elif "ADD COLUMN IF NOT EXISTS advertencia_data" in sql:
                        engine.colunas.add("advertencia_data")
                        for linha in engine.linhas:
                            linha["advertencia_data"] = None
                    elif "SET data_descoberta = data_ato" in sql:
                        for linha in engine.linhas:
                            linha["data_descoberta"] = linha["data_ato"]
                    elif "SET data_ato = data_ato_documento" in sql:
                        for linha in engine.linhas:
                            linha["data_ato"] = linha["data_ato_documento"]
                    elif "SET divergencia_data = CASE" in sql:
                        for linha in engine.linhas:
                            if linha["data_ato"] and linha["data_descoberta"]:
                                linha["divergencia_data"] = "SIM" if linha["data_ato"] != linha["data_descoberta"] else "NAO"
                    elif "SET advertencia_data = :aviso" in sql:
                        for linha in engine.linhas:
                            if linha["divergencia_data"] == "SIM" and not linha["advertencia_data"]:
                                linha["advertencia_data"] = parametros["aviso"]
                    elif "SET status = CASE" in sql:
                        for linha in engine.linhas:
                            if linha["status"] == "ERRO" and linha["erro_coleta"] == parametros["erro_antigo"]:
                                linha["status"] = "NOVO"
                                linha["erro_coleta"] = None
                    return ResultadoFalso(None)

            yield Conexao()

    engine = EngineLegadoFalso()
    migrar_datas_monitoramento(engine)
    migrar_datas_monitoramento(engine)
    assert len(engine.linhas) == 1
    linha = engine.linhas[0]
    assert (linha["data_ato"], linha["data_publicacao"], linha["data_descoberta"]) == (
        date(2026, 9, 1), date(2026, 9, 3), date(2026, 9, 2),
    )
    assert linha["divergencia_data"] == "SIM"
    assert linha["advertencia_data"] and linha["status"] == "NOVO"
    assert linha["erro_coleta"] is None
    assert not any("DELETE " in sql or "DROP " in sql for sql in engine.comandos)

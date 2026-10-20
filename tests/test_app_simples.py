"""Comportamento público da interface com repositório sintético em memória."""

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import src.dados
from src.dados import ErroFonteDados
from tests.test_consulta_simples import base_sintetica


class RepositorioSintetico:
    nome_fonte = "Dados sintéticos"

    def __init__(self, base):
        self.base = base

    def carregar_base(self):
        return self.base


def abrir(monkeypatch, base):
    monkeypatch.setattr(src.dados, "criar_repositorio", lambda **_: RepositorioSintetico(base))
    return AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()


def textos(elementos):
    return " ".join(element.value for element in elementos)


def abrir_ficha(app, indice=0):
    opcoes = [b for b in app.button if str(b.key).startswith("opcao_")]
    assert len(opcoes) > indice
    opcoes[indice].click().run()
    assert not app.exception
    return app


def test_tela_tem_apenas_ncm_e_consulta_com_aliquota_e_fundamento(monkeypatch):
    app = abrir(monkeypatch, base_sintetica())
    assert not app.exception
    assert [campo.label for campo in app.text_input] == ["NCM"]
    assert [botao.label for botao in app.button] == ["Consultar"]
    assert not app.selectbox and not app.metric and not app.dataframe

    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    saida = textos(app.markdown)
    assert "8,32%" in saida
    assert "Norma sintética" in saida
    assert "Artigo" in saida
    assert "https://example.invalid/sintetica" in saida
    assert "Data de referência" in textos(app.caption)
    assert "Operação interna" in textos(app.caption)
    assert "benefício" not in saida.lower()


def test_regra_unica_exibe_dados_cadastrados_sem_confirmar_mercadoria(monkeypatch):
    base = base_sintetica()
    base.aliquotas.loc[0, "descricao_regra"] = "Tratamento sintético"
    base.aliquotas.loc[0, "observacao"] = "Condição sintética cadastrada"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)

    saida = textos(app.markdown)
    assert not app.exception
    assert "8,32%" in saida
    assert "Tratamento sintético" in saida
    assert "01/01/2020" in saida and "31/12/2030" in saida
    assert "Condição sintética cadastrada" in saida
    assert "Tipo de correspondência: NCM exato" in saida
    assert "Código utilizado: 12345678" in saida
    assert "Verificações automáticas do cadastro atendidas" in saida
    assert "Documentação cadastral verificada" not in saida
    assert "NCM sozinho não confirma o enquadramento" in textos(app.info)
    assert app.metric[2].value == "Cadastro localizado"


def test_regra_por_prefixo_informa_alcance_da_correspondencia(monkeypatch):
    base = base_sintetica()
    base.aliquotas.loc[0, "chave_ncm"] = "1234"
    base.aliquotas.loc[0, "tipo_correspondencia"] = "PREFIXO"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)

    saida = textos(app.markdown)
    assert not app.exception
    assert "Tipo de correspondência: prefixo" in saida
    assert "Prefixo utilizado: 1234" in saida
    assert "8,32%" in saida


def test_multiplas_regras_vigentes_exibe_todas_sem_escolher(monkeypatch):
    base = base_sintetica()
    primeira = base.aliquotas.iloc[0].to_dict()
    base.aliquotas.loc[0, "descricao_regra"] = "Tratamento A"
    base.aliquotas.loc[0, "observacao"] = "Observação A"
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([
        {**primeira, "id_regra": "R_2", "aliquota_icms": "6.789", "descricao_regra": "Tratamento B",
         "observacao": "Observação B"},
        {**primeira, "id_regra": "R_PREFIXO", "chave_ncm": "1234", "tipo_correspondencia": "PREFIXO",
         "aliquota_icms": "5.432", "descricao_regra": "Tratamento por prefixo", "observacao": "Observação C"},
    ])], ignore_index=True)
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()

    assert "múltiplas regras" in textos(app.warning).lower()
    assert "não são necessariamente alternativas equivalentes" in textos(app.warning)
    opcoes = [b for b in app.button if str(b.key).startswith("opcao_")]
    assert len(opcoes) == 3
    assert "8,32%" not in textos(app.markdown)
    for indice, (percentual, descricao, observacao) in enumerate([
        ("8,32%", "Tratamento A", "Observação A"),
        ("6,79%", "Tratamento B", "Observação B"),
        ("5,43%", "Tratamento por prefixo", "Observação C"),
    ]):
        abrir_ficha(app, indice)
        saida = textos(app.markdown)
        assert percentual in saida and descricao in saida and observacao in saida
        assert saida.count("Fundamento legal cadastrado:") == 1
        assert saida.count("Vigência da regra:") == 1
        assert saida.count("Fonte cadastrada:") == 1
        assert "19,00%" not in saida
        if indice == 2:
            assert "Tipo de correspondência: prefixo" in saida
            assert "Prefixo utilizado: 1234" in saida
        else:
            assert "Tipo de correspondência: NCM exato" in saida
            assert "Código utilizado: 12345678" in saida
        next(b for b in app.button if b.label == "Voltar").click().run()


def test_regra_com_varias_pendencias_exibe_todas_sem_confirmacao(monkeypatch):
    base = base_sintetica()
    base.aliquotas.loc[0, "vigencia_inicio"] = "data inválida"
    base.aliquotas.loc[0, "id_legislacao"] = "L_INEXISTENTE"
    base.aliquotas.loc[0, "aliquota_icms"] = "1e100"
    base.aliquotas.loc[0, "exige_descricao"] = "SIM"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)

    saida = textos(app.markdown)
    assert not app.exception
    assert "Vigência da regra inconsistente" in saida
    assert "Fundamento legal inexistente ou inativo" in saida
    assert "Percentual inválido ou ausente" in saida
    assert "Características da mercadoria exigem verificação" in saida
    assert "Verificações automáticas do cadastro atendidas" not in saida
    assert "1e100" not in saida


def test_regras_fora_da_vigencia_nao_aparecem_no_resultado(monkeypatch):
    base = base_sintetica()
    passada = {**base.aliquotas.iloc[0].to_dict(), "id_regra": "R_PASSADA",
               "aliquota_icms": "6.789", "vigencia_fim": pd.Timestamp("2025-12-31")}
    futura = {**base.aliquotas.iloc[0].to_dict(), "id_regra": "R_FUTURA",
              "aliquota_icms": "5.432", "vigencia_inicio": pd.Timestamp("2030-01-01")}
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([passada, futura])], ignore_index=True)
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)

    saida = textos(app.markdown)
    assert "8,32%" in saida
    assert "6,79%" not in saida and "5,43%" not in saida


def test_fundamento_inativo_exibe_regra_como_pendente_sem_confirmar(monkeypatch):
    base = base_sintetica()
    base.legislacao.loc[0, "ativo"] = "NAO"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert not app.exception
    assert "Verificação fiscal necessária" in textos(app.warning)
    assert "8,32%" in textos(app.markdown)
    assert "Fundamento legal inexistente ou inativo" in textos(app.markdown)
    assert "Documentação cadastral verificada" not in textos(app.markdown)


def test_percentual_invalido_nao_e_exibido_como_aliquota(monkeypatch):
    base = base_sintetica()
    base.aliquotas.loc[0, "aliquota_icms"] = "1e100"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)

    assert "1e100" not in textos(app.markdown)
    assert "Percentual inválido" in textos(app.markdown)


def test_ncm_sem_regra_nao_transforma_modal_em_tratamento(monkeypatch):
    app = abrir(monkeypatch, base_sintetica(regras=[]))
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert not app.exception
    assert app.metric[0].value == "19,00%"
    assert "Referência geral" in textos(app.caption)
    assert "Tratamento específico de alíquota: nenhum encontrado" in textos(app.markdown)
    assert "referência não confirma o enquadramento" in textos(app.info)


def test_ncm_04029900_ausente_nao_mostra_percentuais(monkeypatch):
    app = abrir(monkeypatch, base_sintetica(regras=[]))
    app.text_input[0].set_value("04029900")
    app.button[0].click().run()

    assert not app.exception
    assert "NCM não encontrado" in textos(app.info)
    assert "12,00%" not in textos(app.markdown)
    assert "19,00%" not in textos(app.markdown)
    assert "Possíveis enquadramentos específicos" not in textos(app.markdown)
    assert "Possíveis enquadramentos específicos" not in textos(app.subheader)


def test_ncm_inativo_nao_mostra_percentuais(monkeypatch):
    app = abrir(monkeypatch, base_sintetica(ncm_ativo="NAO"))
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()

    assert "NCM não encontrado" in textos(app.info)
    assert "8,32%" not in textos(app.markdown)
    assert "19,00%" not in textos(app.markdown)


def test_hipotese_04029900_nao_cria_tratamento_ou_ex(monkeypatch):
    base = base_sintetica(regras=[])
    base.ncm.loc[0, "ncm"] = "04029900"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("04029900")
    app.button[0].click().run()
    abrir_ficha(app)

    assert "12,00%" not in textos(app.markdown)
    assert app.metric[0].value == "19,00%"
    assert "Referência geral" in textos(app.caption)
    assert "referência não confirma o enquadramento" in textos(app.info)
    assert "nenhum Ex foi presumido" in textos(app.info)


def test_consulta_publica_exige_postgres_mesmo_com_excel_configurado(monkeypatch):
    opcoes = []

    def repositorio(**kwargs):
        opcoes.append(kwargs)
        return RepositorioSintetico(base_sintetica())

    monkeypatch.setenv("DATA_SOURCE", "excel")
    monkeypatch.setattr(src.dados, "criar_repositorio", repositorio)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()

    assert not app.exception
    assert opcoes[0]["data_source"] == "postgres"


def test_falha_da_base_mostra_indisponibilidade_sem_confundir_com_ncm_ausente(monkeypatch):
    def falhar(**_):
        raise ErroFonteDados("detalhe técnico")

    monkeypatch.setattr(src.dados, "criar_repositorio", falhar)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()

    assert not app.exception
    assert "Consulta indisponível" in textos(app.error)
    assert "PostgreSQL" in textos(app.error)
    assert "detalhe técnico" not in textos(app.error)
    assert "NCM não encontrado" not in textos(app.info)


def test_ausencia_configuracao_mostra_erro_sem_planilha(monkeypatch):
    from src.dados import ErroConfiguracaoDados

    def falhar(**_):
        raise ErroConfiguracaoDados("detalhe privado da configuração")

    monkeypatch.setattr(src.dados, "criar_repositorio", falhar)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    assert not app.exception
    assert "PostgreSQL não configurada" in textos(app.error)
    assert "detalhe privado" not in textos(app.error)
    assert [campo.label for campo in app.text_input] == ["NCM"]
    assert [botao.label for botao in app.button] == ["Consultar"]

"""Comportamento público da interface com repositório sintético em memória."""

from pathlib import Path

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


def test_tela_tem_apenas_ncm_e_consulta_com_aliquota_e_fundamento(monkeypatch):
    app = abrir(monkeypatch, base_sintetica())
    assert not app.exception
    assert [campo.label for campo in app.text_input] == ["NCM"]
    assert [botao.label for botao in app.button] == ["Consultar"]
    assert not app.selectbox and not app.metric and not app.dataframe

    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    saida = textos(app.markdown)
    assert "8,32%" in saida
    assert "Norma sintética" in saida
    assert "Artigo" in saida
    assert "https://example.invalid/sintetica" in saida
    assert "Data de referência" in textos(app.caption)
    assert "Operação interna" in textos(app.caption)
    assert "benefício" not in saida.lower()


def test_fundamento_inativo_nao_exibe_percentual_como_resultado(monkeypatch):
    base = base_sintetica()
    base.legislacao.loc[0, "ativo"] = "NAO"
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    assert not app.exception
    assert "Verificação fiscal necessária" in textos(app.warning)
    assert "8,32%" not in textos(app.markdown)


def test_ncm_sem_aliquota_mostra_ausencia_sem_inventar_percentual(monkeypatch):
    app = abrir(monkeypatch, base_sintetica(regras=[]))
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    assert not app.exception
    assert "não encontrada" in textos(app.info).lower()
    assert "%" not in textos(app.markdown)


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
    assert "detalhe técnico" not in textos(app.error)
    assert "NCM não encontrado" not in textos(app.info)

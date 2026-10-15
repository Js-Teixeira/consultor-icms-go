"""Lista e ficha com cadastros fictícios; sem fonte fiscal ou conexão real."""

import pandas as pd

from tests.test_app_simples import abrir, textos
from tests.test_consulta_simples import base_sintetica
from tests.test_tratamentos_ncm import base_com_beneficios, beneficio_sintetico


def opcoes(app):
    return [botao for botao in app.button if str(botao.key).startswith("opcao_")]


def pesquisar(app, ncm="12345678"):
    app.text_input[0].set_value(ncm)
    next(b for b in app.button if b.label == "Consultar").click().run()
    assert not app.exception
    return app


def test_lista_ficha_e_voltar_preservam_ncm_sem_misturar_tratamentos(monkeypatch):
    base = base_sintetica()
    primeira = dict(base.aliquotas.iloc[0], descricao_regra="Mercadoria fictícia A")
    base.aliquotas = pd.DataFrame([primeira, dict(primeira, id_regra="R_2",
                                               descricao_regra="Mercadoria fictícia B", aliquota_icms="6.789")])
    app = pesquisar(abrir(monkeypatch, base))
    assert len(opcoes(app)) == 2
    assert "2 opções encontradas" in textos(app.caption)
    assert "Mercadoria fictícia A" in opcoes(app)[0].label
    assert "Mercadoria fictícia B" in opcoes(app)[1].label
    assert "8,32%" not in textos(app.markdown) and "6,79%" not in textos(app.markdown)
    opcoes(app)[1].click().run()
    assert not app.exception
    assert not opcoes(app)
    assert not app.text_input
    assert [b.label for b in app.button] == ["Voltar"]
    assert "1234.56.78 — Mercadoria fictícia B" in textos(app.subheader)
    assert len(app.get("column")) == 3
    assert "Mercadoria fictícia B" in textos(app.markdown)
    assert "6,79%" in textos(app.markdown) and "8,32%" not in textos(app.markdown)
    next(b for b in app.button if b.label == "Voltar").click().run()
    assert not app.exception
    assert app.text_input[0].value == "12345678"
    assert len(opcoes(app)) == 2
    assert "6,79%" not in textos(app.markdown)


def test_beneficio_nao_vira_desdobramento_de_classificacao(monkeypatch):
    base = base_com_beneficios(beneficio_sintetico(descricao_regra="Benefício fictício condicionado"))
    app = pesquisar(abrir(monkeypatch, base))
    assert len(opcoes(app)) == 1
    assert "Benefício fictício condicionado" not in opcoes(app)[0].label
    assert "Ex 01" not in opcoes(app)[0].label
    opcoes(app)[0].click().run()
    assert "Benefício fictício condicionado" in textos(app.markdown)
    assert "vínculo específico" in textos(app.info)
    assert "pendente" in textos(app.markdown)


def test_ncm_sem_tratamento_oferece_apenas_classificacao_cadastrada(monkeypatch):
    base = base_sintetica(regras=[])
    base.ncm.loc[0, "ncm"] = "04029900"
    base.ncm.loc[0, "descricao_oficial"] = "Descrição sintética do catálogo"
    app = pesquisar(abrir(monkeypatch, base), "04029900")
    assert len(opcoes(app)) == 1
    assert "Descrição sintética do catálogo" in opcoes(app)[0].label
    assert "Ex 01" not in opcoes(app)[0].label
    assert "19,00%" not in textos(app.markdown) and "12,00%" not in textos(app.markdown)
    opcoes(app)[0].click().run()
    assert not app.exception
    assert "Alíquota interna verificada: não disponível" in textos(app.markdown)
    assert "Vigência da classificação: não cadastrada" in textos(app.markdown)
    assert "Fundamento da classificação: não cadastrado" in textos(app.markdown)
    assert "19,00%" not in textos(app.markdown) and "12,00%" not in textos(app.markdown)


def test_fundamento_pendente_nao_confirma_aliquota_adicional_ou_soma(monkeypatch):
    base = base_sintetica()
    base.aliquotas.loc[0, "id_legislacao"] = "NAO_EXISTE"
    base.aliquotas.loc[0, "adicional_percentual"] = "2"
    base.aliquotas.loc[0, "exige_descricao"] = "SIM"
    app = pesquisar(abrir(monkeypatch, base))
    opcoes(app)[0].click().run()
    assert not app.exception
    saida = textos(app.markdown)
    assert "Alíquota interna verificada: não disponível" in saida
    assert "Fundamento legal inexistente ou inativo" in saida
    assert "Adicional: aplicação não comprovada" in saida
    assert "Carga total: não calculada" in saida
    assert "10,32%" not in saida


def test_nova_pesquisa_invalida_limpa_ficha_anterior(monkeypatch):
    app = pesquisar(abrir(monkeypatch, base_sintetica()))
    opcoes(app)[0].click().run()
    next(b for b in app.button if b.label == "Voltar").click().run()
    app.text_input[0].set_value("INVALIDO")
    next(b for b in app.button if b.label == "Consultar").click().run()
    assert not app.exception
    assert app.error
    assert not opcoes(app)
    assert "8,32%" not in textos(app.markdown)


def test_ncm_ausente_nao_cria_opcoes(monkeypatch):
    app = pesquisar(abrir(monkeypatch, base_sintetica()), "99999999")
    assert not opcoes(app)
    assert "NCM não encontrado" in textos(app.info)


def test_nova_consulta_valida_retorna_a_lista_com_o_novo_ncm(monkeypatch):
    base = base_sintetica()
    base.ncm = pd.concat([base.ncm, pd.DataFrame([
        {"ncm": "99887766", "descricao_oficial": "Outra classificação fictícia", "ativo": "SIM"},
    ])], ignore_index=True)
    app = pesquisar(abrir(monkeypatch, base))
    opcoes(app)[0].click().run()
    next(b for b in app.button if b.label == "Voltar").click().run()
    pesquisar(app, "99887766")
    assert len(opcoes(app)) == 1
    assert "Outra classificação fictícia" in opcoes(app)[0].label
    assert "8,32%" not in textos(app.markdown)
    opcoes(app)[0].click().run()
    next(b for b in app.button if b.label == "Voltar").click().run()
    assert app.text_input[0].value == "99887766"


def test_indisponibilidade_na_navegacao_nao_exibe_ficha_antiga(monkeypatch):
    import src.dados

    app = pesquisar(abrir(monkeypatch, base_sintetica()))
    opcoes(app)[0].click().run()

    def falhar(**_):
        raise src.dados.ErroFonteDados("Falha sintética")

    monkeypatch.setattr(src.dados, "criar_repositorio", falhar)
    app.run()
    assert not app.exception
    assert "Consulta indisponível" in textos(app.error)
    assert "8,32%" not in textos(app.markdown)
    assert not opcoes(app)


def test_voltar_preserva_ncm_formatado_apos_reexecucao_da_ficha(monkeypatch):
    app = pesquisar(abrir(monkeypatch, base_sintetica()), "1234.56.78")
    opcoes(app)[0].click().run()
    app.run()
    assert not app.text_input
    next(b for b in app.button if b.label == "Voltar").click().run()
    assert not app.exception
    assert app.text_input[0].value == "1234.56.78"
    assert [b.label for b in app.button if not str(b.key).startswith("opcao_")] == ["Consultar"]
    assert len(opcoes(app)) == 1

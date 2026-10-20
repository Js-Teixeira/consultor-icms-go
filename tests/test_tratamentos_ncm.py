"""Alternativas fiscais com dados inteiramente fictícios e repositório em memória."""

from datetime import date

import pandas as pd
import pytest

from src.busca import consultar, pendencias_validacao
from tests.test_app_simples import abrir, abrir_ficha, textos
from tests.test_consulta_simples import REFERENCIA, base_sintetica


def beneficio_sintetico(**campos):
    return {
        "id_beneficio": "B_REDUCAO", "chave_ncm": "12345678",
        "tipo_correspondencia": "EXATO", "tipo_beneficio": "REDUCAO_BASE_CALCULO",
        "descricao_regra": "Redução fictícia", "percentual_reducao_bc": "25",
        "carga_efetiva": "6.241", "credito_outorgado_percentual": None,
        "id_legislacao": "L_TESTE", "ativo": "SIM", "escopo_operacao": "INTERNA",
        "vigencia_inicio": date(2020, 1, 1), "vigencia_fim": date(2030, 12, 31),
        "condicoes": "Somente na operação fictícia descrita no cadastro",
        "exige_descricao": "SIM", **campos,
    }


def base_com_beneficios(*beneficios):
    base = base_sintetica()
    base.beneficios = pd.DataFrame(beneficios)
    return base


def test_duas_aliquotas_e_dois_beneficios_preservados_sem_selecao():
    base = base_com_beneficios(
        beneficio_sintetico(),
        beneficio_sintetico(id_beneficio="B_CREDITO", tipo_beneficio="CREDITO_OUTORGADO",
                            percentual_reducao_bc=None, carga_efetiva=None,
                            credito_outorgado_percentual="4.567"),
    )
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([
        {**base.aliquotas.iloc[0].to_dict(), "id_regra": "R_2", "aliquota_icms": "6.789"},
    ])], ignore_index=True)

    resultado = consultar(base, "12345678", REFERENCIA)

    assert len(resultado.possibilidades_aliquota) == 2
    assert {c.identificador for c in resultado.possibilidades_beneficio} == {"B_REDUCAO", "B_CREDITO"}
    assert resultado.regra_priorizada is None
    assert all(c.tipo_tratamento == "BENEFICIO" for c in resultado.possibilidades_beneficio)
    assert all("aliquota_icms" not in c.dados for c in resultado.possibilidades_beneficio)


def test_uma_aliquota_e_um_beneficio_tambem_nao_escolhem_enquadramento():
    resultado = consultar(base_com_beneficios(beneficio_sintetico()), "12345678", REFERENCIA)
    assert resultado.regra_priorizada is None
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"


def test_ncm_sem_beneficios_mantem_aliquota_atual():
    resultado = consultar(base_sintetica(), "12345678", REFERENCIA)
    assert resultado.possibilidades_beneficio == []
    assert resultado.regra_priorizada.identificador == "R_TESTE"


@pytest.mark.parametrize("campos", [
    {"ativo": "NAO"}, {"vigencia_fim": date(2025, 12, 31)},
    {"vigencia_inicio": date(2031, 1, 1), "vigencia_fim": None},
    {"escopo_operacao": "INTERESTADUAL"},
])
def test_beneficio_inativo_vencido_futuro_ou_interestadual_nao_e_alternativa(campos):
    resultado = consultar(base_com_beneficios(beneficio_sintetico(**campos)), "12345678", REFERENCIA)
    assert resultado.possibilidades_beneficio == []


@pytest.mark.parametrize("chave,tipo,esperado", [
    ("12345678", "EXATO", True), ("12", "PREFIXO", True),
    ("1234", "PREFIXO", True), ("123456", "PREFIXO", True),
    ("123", "PREFIXO", False), ("9988", "PREFIXO", False),
])
def test_beneficios_por_ncm_exato_ou_prefixo(chave, tipo, esperado):
    base = base_com_beneficios(beneficio_sintetico(chave_ncm=chave, tipo_correspondencia=tipo))
    assert bool(consultar(base, "12345678", REFERENCIA).possibilidades_beneficio) == esperado


@pytest.mark.parametrize("escopo", [None, "NAO_DEFINIDA", "INVALIDO"])
def test_escopo_desconhecido_aparece_somente_com_pendencia(escopo):
    resultado = consultar(base_com_beneficios(beneficio_sintetico(escopo_operacao=escopo)),
                          "12345678", REFERENCIA)
    pendencias = pendencias_validacao(resultado.possibilidades_beneficio[0])
    assert any("Escopo" in p for p in pendencias)
    assert resultado.regra_priorizada is None


def test_condicoes_cadastradas_nao_comprovam_aplicabilidade():
    resultado = consultar(base_com_beneficios(beneficio_sintetico(exige_descricao="NAO")),
                          "12345678", REFERENCIA)
    assert any("Condições" in p for p in pendencias_validacao(resultado.possibilidades_beneficio[0]))


def test_beneficio_sem_condicoes_ou_fundamento_exibe_ambas_pendencias():
    base = base_com_beneficios(beneficio_sintetico(condicoes=None, id_legislacao="INEXISTENTE"))
    candidato = consultar(base, "12345678", REFERENCIA).possibilidades_beneficio[0]
    pendencias = pendencias_validacao(candidato)
    assert any("Fundamento legal inexistente" in p for p in pendencias)
    assert any("Condições" in p for p in pendencias)


def test_vigencia_inconsistente_do_beneficio_fica_visivel_com_pendencia():
    base = base_com_beneficios(beneficio_sintetico(vigencia_inicio="data inválida"))
    candidato = consultar(base, "12345678", REFERENCIA).possibilidades_beneficio[0]
    assert any("Vigência da regra inconsistente" in p for p in pendencias_validacao(candidato))


def test_interface_separa_aliquotas_em_fichas_e_beneficios_por_natureza(monkeypatch):
    base = base_com_beneficios(
        beneficio_sintetico(),
        beneficio_sintetico(id_beneficio="B_CREDITO", tipo_beneficio="CREDITO_OUTORGADO",
                            descricao_regra="Crédito fictício", percentual_reducao_bc=None,
                            carga_efetiva=None, credito_outorgado_percentual="4.567"),
    )
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([
        {**base.aliquotas.iloc[0].to_dict(), "id_regra": "R_2", "aliquota_icms": "6.789"},
    ])], ignore_index=True)
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()

    assert not app.exception
    assert [c.label for c in app.text_input] == ["NCM"]
    assert len([b for b in app.button if str(b.key).startswith("opcao_")]) == 2
    assert "nenhuma foi escolhida automaticamente" in textos(app.warning)
    assert "8,32%" not in textos(app.markdown)
    abrir_ficha(app)
    saida = textos(app.markdown)
    for trecho in ("8,32%", "Redução da base de cálculo: 25,00%",
                   "Carga efetiva: 6,24%", "Crédito outorgado: 4,57%",
                   "Redução fictícia", "Crédito fictício", "Norma sintética",
                   "Somente na operação fictícia", "Condições cadastradas exigem validação fiscal"):
        assert trecho in saida
    assert sum(s.value.startswith("Benefício cadastrado:") for s in app.subheader) == 2
    assert "Benefícios fiscais" in textos(app.subheader) and "Alertas fiscais" in textos(app.subheader)
    assert app.metric[2].value == "Revisão fiscal"
    assert "6,79%" not in saida
    next(b for b in app.button if b.label == "Voltar").click().run()
    abrir_ficha(app, 1)
    assert "6,79%" in textos(app.markdown) and "8,32%" not in textos(app.markdown)
    assert "vínculo específico" in textos(app.info)


def test_interface_sem_beneficios_informa_ausencia(monkeypatch):
    app = abrir(monkeypatch, base_sintetica())
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert "nenhum benefício vigente identificado no cadastro" in textos(app.caption)


@pytest.mark.parametrize("tipo", ["ISENCAO", "DIFERIMENTO", "OUTRO_BENEFICIO"])
def test_beneficio_sem_percentual_nao_inventa_aliquota_zero(monkeypatch, tipo):
    base = base_com_beneficios(beneficio_sintetico(tipo_beneficio=tipo,
                                                percentual_reducao_bc=None, carga_efetiva=None))
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert not app.exception
    assert "B_REDUCAO" in textos(app.subheader)
    assert "0,00%" not in textos(app.markdown)


def test_beneficio_aparece_mesmo_sem_aliquota_cadastrada(monkeypatch):
    base = base_com_beneficios(beneficio_sintetico())
    base.aliquotas = pd.DataFrame()
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert not app.exception
    assert "B_REDUCAO" in textos(app.subheader)
    assert app.metric[0].value == "19,00%"
    assert "Referência geral" in textos(app.caption)
    assert "referência não confirma o enquadramento" in textos(app.info)


def test_referencias_codificadas_nao_entram_na_lista_de_beneficios():
    base = base_sintetica(regras=[])
    base.ncm.loc[0, "ncm"] = "04029900"
    resultado = consultar(base, "04029900", REFERENCIA)
    assert not resultado.possibilidades_beneficio
    assert resultado.aliquota_geral_referencia is not None
    assert resultado.hipoteses_especiais


def test_beneficios_exato_e_prefixo_coexistem_inclusive_com_escopo_ambas():
    base = base_com_beneficios(
        beneficio_sintetico(),
        beneficio_sintetico(id_beneficio="B_PREFIXO", chave_ncm="1234",
                            tipo_correspondencia="PREFIXO", escopo_operacao="AMBAS"),
    )
    resultado = consultar(base, "12345678", REFERENCIA)
    assert {c.identificador for c in resultado.possibilidades_beneficio} == {"B_REDUCAO", "B_PREFIXO"}
    assert resultado.regra_priorizada is None


@pytest.mark.parametrize("referencia,visivel", [
    (date(2019, 12, 31), False), (date(2020, 1, 1), True),
    (date(2030, 12, 31), True), (date(2031, 1, 1), False),
])
def test_limites_de_vigencia_do_beneficio_sao_inclusivos(referencia, visivel):
    resultado = consultar(base_com_beneficios(beneficio_sintetico()), "12345678", referencia)
    assert bool(resultado.possibilidades_beneficio) == visivel


def test_interface_exibe_pendencias_do_beneficio_junto_ao_tratamento(monkeypatch):
    base = base_com_beneficios(beneficio_sintetico(condicoes=None, id_legislacao="INEXISTENTE"))
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert not app.exception
    saida = textos(app.markdown)
    assert "Fundamento legal inexistente ou inativo" in saida
    assert "Condições de aplicação do benefício não cadastradas" in saida
    assert app.metric[2].value == "Revisão fiscal"
    assert "Alertas fiscais" in textos(app.subheader)


def test_interface_nao_mostra_beneficio_vencido_como_alternativa(monkeypatch):
    base = base_com_beneficios(beneficio_sintetico(vigencia_fim=date(2025, 12, 31)))
    app = abrir(monkeypatch, base)
    app.text_input[0].set_value("12345678")
    app.button[0].click().run()
    abrir_ficha(app)
    assert not app.exception
    assert "B_REDUCAO" not in textos(app.subheader)
    assert "25,00%" not in textos(app.markdown)
    assert "nenhum benefício vigente identificado no cadastro" in textos(app.caption)


def test_ncm_inativo_nao_recebe_beneficios_por_correspondencia():
    base = base_com_beneficios(beneficio_sintetico())
    base.ncm.loc[0, "ativo"] = "NAO"
    resultado = consultar(base, "12345678", REFERENCIA)
    assert resultado.situacao == "NCM_NAO_ENCONTRADO"
    assert not resultado.candidatos_beneficio and not resultado.possibilidades_beneficio

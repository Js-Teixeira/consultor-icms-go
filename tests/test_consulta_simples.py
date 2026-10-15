"""Contrato da consulta pública com dados inteiramente sintéticos."""

from datetime import date

import pandas as pd
import pytest

from src.busca import consultar, pendencia_validacao, pendencias_validacao
from src.modelos import BaseTributaria


REFERENCIA = date(2026, 9, 30)


def base_sintetica(*, regras=None, legislacao=None, ncm_ativo="SIM"):
    regra = {
        "id_regra": "R_TESTE", "chave_ncm": "12345678", "tipo_correspondencia": "EXATO",
        "aliquota_icms": "8.321", "id_legislacao": "L_TESTE", "ativo": "SIM",
        "vigencia_inicio": date(2020, 1, 1), "vigencia_fim": date(2030, 12, 31),
        "exige_descricao": "NAO",
    }
    fundamento = {
        "id_legislacao": "L_TESTE", "norma": "Norma sintética", "numero": "X",
        "ano": "2020", "artigo": "1", "url_fonte": "https://example.invalid/sintetica",
        "ativo": "SIM", "vigencia_inicio": date(2020, 1, 1),
        "vigencia_fim": date(2030, 12, 31), "data_verificacao": date(2026, 9, 1),
    }
    return BaseTributaria(
        ncm=pd.DataFrame([{"ncm": "12345678", "descricao_oficial": "Produto sintético", "ativo": ncm_ativo}]),
        aliquotas=pd.DataFrame([regra] if regras is None else regras),
        beneficios=pd.DataFrame(),
        legislacao=pd.DataFrame([fundamento] if legislacao is None else legislacao),
    )


def test_aliquota_unica_com_fundamento_cadastral_consistente():
    resultado = consultar(base_sintetica(), "1234.56.78", data_referencia=REFERENCIA)
    assert resultado.situacao == "ENCONTRADO"
    assert resultado.regra_priorizada.dados["aliquota_icms"] == "8.321"
    assert resultado.regra_priorizada.legislacao["artigo"] == "1"
    assert resultado.data_referencia == REFERENCIA


@pytest.mark.parametrize("alteracao", [
    {"id_legislacao": None},
    {"id_legislacao": "L_INEXISTENTE"},
], ids=["sem-id", "id-inexistente"])
def test_fundamento_ausente_exige_verificacao(alteracao):
    base = base_sintetica()
    base.aliquotas.loc[0, list(alteracao)[0]] = list(alteracao.values())[0]
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert resultado.candidatos_aliquota[0].problema_fundamento


@pytest.mark.parametrize("alteracao", [
    {"ativo": "NAO"},
    {"vigencia_fim": date(2025, 12, 31)},
    {"vigencia_inicio": date(2031, 1, 1), "vigencia_fim": date(2025, 12, 31)},
    {"url_fonte": ""},
    {"url_fonte": "https://[endereco-invalido"},
    {"artigo": ""},
], ids=["inativo", "fora-vigencia", "datas-inconsistentes", "sem-fonte", "fonte-invalida", "sem-dispositivo"])
def test_fundamento_nao_apto_exige_verificacao(alteracao):
    base = base_sintetica()
    for campo, valor in alteracao.items():
        base.legislacao.loc[0, campo] = valor
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert resultado.candidatos_aliquota[0].problema_fundamento


def test_regra_que_exige_descricao_nao_e_confirmada_por_ncm():
    base = base_sintetica()
    base.aliquotas.loc[0, "exige_descricao"] = "SIM"
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None


def test_regra_exata_problematica_nao_cai_para_prefixo():
    base = base_sintetica()
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([{
        **base.aliquotas.iloc[0].to_dict(), "id_regra": "R_PREFIXO", "chave_ncm": "1234",
        "tipo_correspondencia": "PREFIXO", "aliquota_icms": "6.789", "id_legislacao": "L_TESTE",
    }])], ignore_index=True)
    base.aliquotas.loc[0, "id_legislacao"] = "L_INEXISTENTE"
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert {c.identificador for c in resultado.candidatos_aliquota} == {"R_TESTE", "R_PREFIXO"}


def test_aliquotas_empatadas_exigem_verificacao():
    base = base_sintetica()
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([{
        **base.aliquotas.iloc[0].to_dict(), "id_regra": "R_2", "aliquota_icms": "6.789",
    }])], ignore_index=True)
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None


def test_regra_exata_e_prefixo_simultaneos_nao_sao_escolhidos_pelo_ncm():
    base = base_sintetica()
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([{
        **base.aliquotas.iloc[0].to_dict(), "id_regra": "R_PREFIXO", "chave_ncm": "1234",
        "tipo_correspondencia": "PREFIXO", "aliquota_icms": "6.789",
    }])], ignore_index=True)

    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)

    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert {c.identificador for c in resultado.possibilidades_aliquota} == {"R_TESTE", "R_PREFIXO"}


def test_vigencia_inconsistente_permanece_visivel_sem_selecao_automatica():
    base = base_sintetica()
    base.aliquotas = pd.concat([base.aliquotas, pd.DataFrame([{
        **base.aliquotas.iloc[0].to_dict(), "id_regra": "R_DATA_INVALIDA",
        "vigencia_inicio": "data inválida", "aliquota_icms": "6.789",
    }])], ignore_index=True)

    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)

    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert {c.identificador for c in resultado.possibilidades_aliquota} == {"R_TESTE", "R_DATA_INVALIDA"}


def test_pendencias_da_mesma_regra_sao_acumuladas_sem_quebrar_contrato_anterior():
    base = base_sintetica()
    base.aliquotas.loc[0, "vigencia_inicio"] = "data inválida"
    base.aliquotas.loc[0, "id_legislacao"] = "L_INEXISTENTE"
    base.aliquotas.loc[0, "aliquota_icms"] = "1e100"
    base.aliquotas.loc[0, "exige_descricao"] = "SIM"

    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    regra = resultado.possibilidades_aliquota[0]
    pendencias = pendencias_validacao(regra)

    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert len(pendencias) == 4
    assert "Vigência da regra inconsistente" in pendencias[0]
    assert "Fundamento legal inexistente ou inativo" in pendencias[1]
    assert "Percentual inválido ou ausente" in pendencias[2]
    assert "Características da mercadoria exigem verificação" in pendencias[3]
    assert pendencia_validacao(regra) == pendencias[0]


def test_fundamento_com_varias_falhas_exibe_cada_pendencia():
    base = base_sintetica()
    base.legislacao.loc[0, "data_verificacao"] = None
    base.legislacao.loc[0, "artigo"] = ""
    base.legislacao.loc[0, "url_fonte"] = ""

    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    regra = resultado.possibilidades_aliquota[0]
    pendencias = pendencias_validacao(regra)

    assert resultado.regra_priorizada is None
    assert any("Verificação do fundamento legal ausente" in p for p in pendencias)
    assert any("Dispositivo legal específico não cadastrado" in p for p in pendencias)
    assert any("Endereço da fonte ausente ou inválido" in p for p in pendencias)
    assert regra.problema_fundamento == pendencias[0]


@pytest.mark.parametrize("ncm", ["AB1234-CD56-78", "1234567", "１２３４５６７８"])
def test_ncm_invalido_e_rejeitado(ncm):
    with pytest.raises(ValueError, match="NCM inválido"):
        consultar(base_sintetica(), ncm, data_referencia=REFERENCIA)


def test_sem_regra_nao_e_confundida_com_pendencia():
    resultado = consultar(base_sintetica(regras=[]), "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "SEM_TRATAMENTO_CADASTRADO"
    assert resultado.regra_priorizada is None


def test_regra_fora_da_vigencia_nao_e_confirmada():
    base = base_sintetica()
    base.aliquotas.loc[0, "vigencia_fim"] = date(2025, 12, 31)
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "SEM_REGRA_VIGENTE"
    assert resultado.regra_priorizada is None


def test_percentual_fora_da_escala_nao_e_apresentado_como_aliquota():
    base = base_sintetica()
    base.aliquotas.loc[0, "aliquota_icms"] = "1e100"
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None


def test_vigencia_inicial_do_fundamento_ausente_exige_verificacao():
    base = base_sintetica()
    base.legislacao.loc[0, "vigencia_inicio"] = None
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None
    assert resultado.candidatos_aliquota[0].problema_fundamento == (
        "Início de vigência do fundamento legal não cadastrado."
    )


def test_vigencia_inicial_da_regra_ausente_exige_verificacao():
    base = base_sintetica()
    base.aliquotas.loc[0, "vigencia_inicio"] = None
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None


@pytest.mark.parametrize("verificacao", [None, date(2026, 10, 1)])
def test_fundamento_sem_verificacao_apta_exige_revisao(verificacao):
    base = base_sintetica()
    base.legislacao.loc[0, "data_verificacao"] = verificacao
    resultado = consultar(base, "12345678", data_referencia=REFERENCIA)
    assert resultado.situacao == "VERIFICACAO_NECESSARIA"
    assert resultado.regra_priorizada is None

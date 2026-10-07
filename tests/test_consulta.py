"""Cenários sintéticos: números abaixo exercitam o motor, sem representar tributos reais."""

from datetime import date

import pandas as pd
import pytest

from src.busca import consultar
from src.carregamento import CAMINHO_BASE, ErroBase, base_vazia, carregar_base
from src.modelos import BaseTributaria
from src.normalizacao import formatar_ncm, normalizar_ncm, normalizar_texto

HOJE = date(2026, 9, 30)


def regra(id_regra="R1", chave="12345678", tipo="EXATO", **campos):
    return {
        "id_regra": id_regra, "chave_ncm": chave, "tipo_correspondencia": tipo,
        "descricao_regra": "Produto de teste", "palavras_chave": "produto",
        "aliquota_icms": "VALOR_SINTETICO", "id_legislacao": "L1", "vigencia_inicio": None,
        "vigencia_fim": None, "ativo": "SIM", **campos,
    }


def beneficio(id_beneficio="B1", chave="12345678", tipo="EXATO", **campos):
    return {
        "id_beneficio": id_beneficio, "chave_ncm": chave,
        "tipo_correspondencia": tipo, "descricao_regra": "Produto de teste",
        "palavras_chave": "produto", "tipo_beneficio": "TIPO_SINTETICO",
        "carga_efetiva": "CARGA_SINTETICA", "id_legislacao": "L1", "vigencia_inicio": None,
        "vigencia_fim": None, "ativo": "SIM", **campos,
    }


def base(regras=None, beneficios=None, legislacao=None):
    if legislacao is None:
        legislacao = [{"id_legislacao": "L1", "norma": "Norma de teste", "numero": 1,
                       "ano": 2000, "url_fonte": "https://example.invalid", "ativo": "SIM"}]
    return BaseTributaria(
        ncm=pd.DataFrame([{"ncm": "12345678", "descricao_oficial": "Descrição de teste", "ativo": "SIM"}]),
        aliquotas=pd.DataFrame(regras if regras is not None else [regra()]),
        beneficios=pd.DataFrame(beneficios or []),
        legislacao=pd.DataFrame(legislacao),
    )


def consulta(b, ncm="12345678", descricao=""):
    return consultar(b, ncm, descricao, HOJE)


def test_ncm_com_pontos():
    assert normalizar_ncm("1234.56.78") == "12345678"
    assert formatar_ncm("12345678") == "1234.56.78"


def test_ncm_com_letras_remove_nao_numericos():
    assert normalizar_ncm("AB1234-CD56-78") == "12345678"


def test_ncm_com_menos_de_oito_digitos():
    with pytest.raises(ValueError, match="8 dígitos"):
        normalizar_ncm("1234.56.7")


def test_texto_preserva_original_na_consulta():
    assert normalizar_texto("  ÁGUA   Mineral ") == "agua mineral"
    assert consulta(base(), descricao="ÁGUA Mineral").descricao_original == "ÁGUA Mineral"


def test_exato_vence_prefixo():
    b = base([regra("P", "1234", "PREFIXO"), regra("E")])
    r = consulta(b)
    assert r.regra_priorizada.identificador == "E"
    assert {c.identificador for c in r.candidatos_aliquota} == {"E", "P"}


def test_prefixo_corresponde():
    r = consulta(base([regra("P", "1234", "PREFIXO")]))
    assert r.regra_priorizada.identificador == "P"


def test_prefixo_mais_especifico_vence():
    r = consulta(base([regra("P4", "1234", "PREFIXO"), regra("P6", "123456", "PREFIXO")]))
    assert r.regra_priorizada.identificador == "P6"


def test_prioridade_exato_prefixos_6_4_2():
    regras = [regra("P2", "12", "PREFIXO"), regra("P4", "1234", "PREFIXO"),
              regra("P6", "123456", "PREFIXO"), regra("E")]
    r = consulta(base(regras))
    assert [c.identificador for c in r.candidatos_aliquota] == ["E", "P6", "P4", "P2"]


@pytest.mark.parametrize("comprimento", [1, 3, 5, 7, 8])
def test_prefixo_de_comprimento_invalido_nao_corresponde(comprimento):
    r = consulta(base([regra("P", "12345678"[:comprimento], "PREFIXO")]))
    assert r.situacao == "SEM_TRATAMENTO_CADASTRADO"
    assert r.regra_priorizada is None
    assert not r.candidatos_aliquota


def test_consulta_sem_descricao_com_uma_regra():
    r = consulta(base())
    assert r.regra_priorizada.identificador == "R1"
    assert r.nivel_confianca == "ALTA"
    assert r.candidatos_aliquota[0].score_descricao is None


def test_consulta_com_descricao_desempata_sem_apagar_candidatos():
    b = base([regra("A", descricao_regra="Leite em pó", palavras_chave="leite"),
              regra("B", descricao_regra="Bateria automotiva", palavras_chave="bateria")])
    r = consulta(b, descricao="Leite em pó")
    assert r.regra_priorizada.identificador == "A"
    assert r.nivel_confianca == "MEDIA"
    assert len(r.candidatos_aliquota) == 2
    assert r.candidatos_aliquota[0].score_descricao > r.candidatos_aliquota[1].score_descricao


@pytest.mark.parametrize(("limite", "data"), [
    ("vigencia_fim", date(2025, 12, 31)),
    ("vigencia_inicio", date(2027, 1, 1)),
], ids=["vencida", "futura"])
def test_regra_fora_da_vigencia_e_descartada(limite, data):
    r = consulta(base([regra(**{limite: data})]))
    assert r.regra_priorizada is None
    assert r.candidatos_aliquota[0].vigencia == "FORA_DA_VIGENCIA"
    assert r.situacao == "SEM_REGRA_VIGENTE"


def test_fim_de_vigencia_vazio_sem_limite():
    r = consulta(base([regra(vigencia_inicio=date(2020, 1, 1), vigencia_fim=None)]))
    assert r.regra_priorizada.identificador == "R1"


def test_base_vazia_real():
    b = carregar_base(CAMINHO_BASE)
    assert base_vazia(b)
    assert consulta(b).situacao == "NCM_NAO_ENCONTRADO"


def test_multiplas_regras_plausiveis_exigem_revisao():
    r = consulta(base([regra("A"), regra("B")]))
    assert r.regra_priorizada is None
    assert r.nivel_confianca == "REVISAO_NECESSARIA"
    assert len(r.candidatos_aliquota) == 2


def test_beneficio_sem_legislacao_vinculada():
    r = consulta(base(beneficios=[beneficio(id_legislacao="INEXISTENTE")]))
    assert r.beneficios_priorizados[0].problema_fundamento
    assert r.nivel_confianca == "REVISAO_NECESSARIA"


def test_ncm_nao_encontrado():
    r = consulta(base(), ncm="99999999")
    assert r.situacao == "NCM_NAO_ENCONTRADO"
    assert r.regra_priorizada is None


def test_ncm_oficial_sem_tratamento_preserva_descricao_sem_inferir_tributos():
    r = consulta(base(regras=[regra(chave="87654321")], beneficios=[]))
    assert r.situacao == "SEM_TRATAMENTO_CADASTRADO"
    assert r.ncm_normalizado == "12345678"
    assert r.descricao_oficial == "Descrição de teste"
    assert r.regra_priorizada is None
    assert r.beneficios_encontrados == []
    assert r.candidatos_aliquota == []


def test_ncm_com_aliquota_sem_beneficio_permanece_encontrado():
    r = consulta(base())
    assert r.situacao == "ENCONTRADO"
    assert r.regra_priorizada.identificador == "R1"
    assert r.beneficios_encontrados == []


def test_ncm_com_aliquota_e_beneficio_permanece_encontrado():
    r = consulta(base(beneficios=[beneficio()]))
    assert r.situacao == "ENCONTRADO"
    assert r.regra_priorizada.identificador == "R1"
    assert [b.identificador for b in r.beneficios_encontrados] == ["B1"]


def test_datas_inconsistentes_exigem_revisao():
    b = base([regra("A"), regra("B", vigencia_inicio=date(2027, 1, 1),
                               vigencia_fim=date(2026, 1, 1))])
    r = consulta(b)
    assert r.regra_priorizada.identificador == "A"
    assert r.nivel_confianca == "REVISAO_NECESSARIA"


def test_regra_sem_valor_de_aliquota_exige_revisao():
    r = consulta(base([regra(aliquota_icms=None)]))
    assert r.nivel_confianca == "REVISAO_NECESSARIA"


def test_base_com_regras_inativas_e_vazia():
    assert consulta(base([regra(ativo="NAO")])).situacao == "SEM_TRATAMENTO_CADASTRADO"


def test_planilha_indisponivel(tmp_path):
    with pytest.raises(ErroBase, match="Planilha indisponível"):
        carregar_base(tmp_path / "inexistente.xlsx")


def test_colunas_obrigatorias_ausentes(tmp_path):
    caminho = tmp_path / "incompleta.xlsx"
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for aba, tabela in {
            "NCM": pd.DataFrame(columns=["ncm", "descricao_oficial", "ativo"]),
            "Aliquotas": pd.DataFrame(columns=["id_regra"]),
            "Beneficios": pd.DataFrame(columns=["id_beneficio"]),
            "Legislacao": pd.DataFrame(columns=["id_legislacao"]),
        }.items():
            tabela.to_excel(writer, sheet_name=aba, index=False)
    with pytest.raises(ErroBase, match="Colunas obrigatórias ausentes em Aliquotas"):
        carregar_base(caminho)

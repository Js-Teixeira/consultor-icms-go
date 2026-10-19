"""Dados sintéticos compartilhados e validações básicas da consulta."""


from src.normalizacao import normalizar_ncm


def beneficio(id_beneficio="B1", chave="12345678", tipo="EXATO", **campos):
    return {
        "id_beneficio": id_beneficio, "chave_ncm": chave,
        "tipo_correspondencia": tipo, "descricao_regra": "Produto sintético",
        "palavras_chave": "produto", "tipo_beneficio": "TIPO_SINTETICO",
        "carga_efetiva": "CARGA_SINTETICA", "id_legislacao": "L1",
        "vigencia_inicio": None, "vigencia_fim": None, "ativo": "SIM", **campos,
    }


def test_ncm_com_pontos_e_zero_inicial():
    assert normalizar_ncm("0123.45.67") == "01234567"

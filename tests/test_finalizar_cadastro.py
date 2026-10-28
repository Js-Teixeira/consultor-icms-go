from copy import deepcopy

import pytest


def lote_teste():
    return {
        'lote': 'FINAL_20261027',
        'referencia': '2026-10-27',
        'natureza': 'CANDIDATOS_CONDICIONAIS',
        'legislacao': [{
            'id_legislacao': 'LEG_TESTE', 'norma': 'Norma de teste',
            'numero': '1', 'ano': '2020', 'artigo': '8', 'inciso': 'XXXIII',
            'texto_relevante': 'Texto sintético para teste de carga.',
            'url_fonte': 'https://appasp.economia.go.gov.br/legislacao/arquivos/Rcte/Anexos/ANEXO_09_Beneficio_Fiscal.htm',
            'vigencia_inicio': '2021-03-31', 'vigencia_fim': None,
            'data_verificacao': '2026-10-27', 'ativo': 'SIM',
        }],
        'aliquotas': [],
        'beneficios': [{
            'id_beneficio': 'BEN_TESTE', 'chave_ncm': '12345678',
            'tipo_correspondencia': 'EXATO', 'descricao_regra': 'Possibilidade condicionada de benefício de teste',
            'tipo_beneficio': 'CARGA_EFETIVA', 'carga_efetiva': 7,
            'percentual_reducao_bc': None, 'credito_outorgado_percentual': None,
            'condicoes': 'Conferir identidade do produto e requisitos da operação.',
            'id_legislacao': 'LEG_TESTE', 'vigencia_inicio': '2026-10-27',
            'vigencia_fim': None, 'ativo': 'SIM', 'exige_descricao': 'SIM',
            'aplicacao': 'ALTERNATIVO', 'escopo_operacao': 'INTERNA', 'cbenef': None,
            'regra_consolidada_id': None, 'evidencia_ncm_id': None,
        }],
        'revisoes': {'aliquotas': [], 'beneficios': []},
    }


def test_aceita_meta_de_carga_efetiva_sem_inventar_reducao_fixa():
    from scripts.finalizar_cadastro import validar_lote
    lote = lote_teste()
    original = deepcopy(lote)
    validar_lote(lote, {'12345678'})
    assert lote == original


@pytest.mark.parametrize('mudanca', [
    {'carga_efetiva': 101}, {'carga_efetiva': None}, {'exige_descricao': 'NAO'},
    {'escopo_operacao': None}, {'condicoes': ''}, {'id_legislacao': 'AUSENTE'},
    {'chave_ncm': '87654321'}, {'tipo_correspondencia': 'PREFIXO'},
    {'regra_consolidada_id': 123}, {'carga_efetiva': float('nan')},
])
def test_bloqueia_registro_sem_condicoes_escopo_fonte_ou_ncm(mudanca):
    from scripts.finalizar_cadastro import validar_lote
    lote = lote_teste()
    lote['beneficios'][0].update(mudanca)
    with pytest.raises(ValueError):
        validar_lote(lote, {'12345678'})


def test_bloqueia_fonte_externa_e_verificacao_futura():
    from scripts.finalizar_cadastro import validar_lote
    for mudanca in ({'url_fonte': 'https://example.invalid'}, {'data_verificacao': '2026-10-28'}):
        lote = lote_teste()
        lote['legislacao'][0].update(mudanca)
        with pytest.raises(ValueError):
            validar_lote(lote, {'12345678'})


def test_isenção_nao_inventa_percentual_de_aliquota():
    from scripts.finalizar_cadastro import validar_lote
    lote = lote_teste()
    lote['beneficios'][0].update(tipo_beneficio='ISENCAO', carga_efetiva=None)
    validar_lote(lote, {'12345678'})
    lote['beneficios'][0]['carga_efetiva'] = 0
    with pytest.raises(ValueError):
        validar_lote(lote, {'12345678'})


def test_revisao_preserva_chave_e_nao_muda_ncm_do_historico():
    from scripts.finalizar_cadastro import validar_lote
    lote = lote_teste()
    antigo = lote['beneficios'].pop()
    novo = deepcopy(antigo)
    novo['chave_ncm'] = '87654321'
    lote['revisoes']['beneficios'] = [{'antes': antigo, 'depois': novo}]
    with pytest.raises(ValueError):
        validar_lote(lote, {'12345678', '87654321'})


def test_sql_exige_estado_anterior_ou_novo_e_nao_exclui_registros():
    from scripts.finalizar_cadastro import gerar_sql
    sql = gerar_sql(lote_teste(), {'12345678'})
    assert sql.startswith('DO $finalizacao$')
    assert 'IS DISTINCT FROM' in sql
    assert 'LOCK TABLE' in sql
    assert 'ON CONFLICT' in sql
    assert 'DELETE ' not in sql and 'TRUNCATE ' not in sql and 'DROP ' not in sql

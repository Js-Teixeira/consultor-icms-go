from copy import deepcopy
from datetime import date

import pytest


def anterior():
    from src.dados.schema import TABELAS
    r = {c.name: None for c in TABELAS['Aliquotas'].columns}
    r.update(id_regra='TESTE', chave_ncm='12345678', tipo_correspondencia='EXATO',
             aliquota_icms=12, descricao_regra='Hipótese anterior', observacao='Histórico sintético',
             id_legislacao='LEI_TESTE', vigencia_inicio='2020-01-01', ativo='SIM', exige_descricao='SIM')
    return r


def test_suspende_numero_sem_inventar_modal_e_preserva_versao_anterior():
    from scripts.suspender_percentual import preparar_suspensao
    a = anterior()
    copia = deepcopy(a)
    revisao = preparar_suspensao([a], {'12345678': 'Identidade do produto não demonstrada.'}, date(2026, 10, 28))[0]
    assert a == copia == revisao['antes']
    depois = revisao['depois']
    assert depois['aliquota_icms'] is None
    assert depois['descricao_regra'].startswith('ALÍQUOTA ESPECÍFICA NÃO COMPROVADA')
    assert '12% histórico' in depois['observacao']
    assert 'Histórico sintético' in depois['observacao']
    assert 'Identidade do produto não demonstrada.' in depois['observacao']
    for campo in ('id_regra', 'chave_ncm', 'id_legislacao', 'vigencia_inicio', 'vigencia_fim', 'ativo'):
        assert depois[campo] == a[campo]


@pytest.mark.parametrize('mudanca', [{'aliquota_icms': 19}, {'tipo_correspondencia': 'PREFIXO'},
                                  {'ativo': 'NAO'}, {'chave_ncm': '1234'}])
def test_rejeita_ampliacao_da_correcao_aprovada(mudanca):
    from scripts.suspender_percentual import preparar_suspensao
    a = {**anterior(), **mudanca}
    with pytest.raises(ValueError):
        preparar_suspensao([a], {'12345678': 'Motivo'}, date(2026, 10, 28))


def test_motivo_vazio_ou_ncm_sem_decisao_aborta():
    from scripts.suspender_percentual import preparar_suspensao
    for motivos in ({}, {'12345678': ''}, {'12345678': 'Motivo', '87654321': 'Extra'}):
        with pytest.raises(ValueError):
            preparar_suspensao([anterior()], motivos, date(2026, 10, 28))


def test_sql_preserva_guardas_e_escapa_conteudo_sem_excluir_registros():
    from scripts.suspender_percentual import preparar_suspensao, gerar_sql_suspensao
    revisoes = preparar_suspensao([anterior()], {'12345678': "Produto d'água"}, date(2026, 10, 28))
    sql = gerar_sql_suspensao(revisoes, 'e8be9b594dd4dd3f7a73211dae70954a')
    assert "d''água" in sql
    assert 'IS DISTINCT FROM' in sql and 'LOCK TABLE' in sql
    assert 'aliquota_icms=NULL' in sql
    assert 'DELETE ' not in sql and 'INSERT ' not in sql
    alteradas = deepcopy(revisoes)
    alteradas[0]['depois']['id_legislacao'] = 'OUTRA'
    with pytest.raises(ValueError):
        gerar_sql_suspensao(alteradas, 'e8be9b594dd4dd3f7a73211dae70954a')

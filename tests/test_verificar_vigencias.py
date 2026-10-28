from datetime import date

import pandas as pd
import pytest

from src.modelos import BaseTributaria


def base_com(*registros):
    return BaseTributaria(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(registros), pd.DataFrame())


def beneficio(id, fim, **campos):
    return {'id_beneficio': id, 'chave_ncm': '12345678', 'ativo': 'SIM',
            'vigencia_inicio': '2020-01-01', 'vigencia_fim': fim, **campos}


def test_limite_inclusivo_e_vencido_sem_omitir_data_corrente():
    from scripts.verificar_vigencias import auditar_vigencias
    base = base_com(beneficio('HOJE', '2026-10-28'), beneficio('LIMITE', '2026-12-12'),
                   beneficio('DISTANTE', '2026-12-13'), beneficio('ANTERIOR', '2026-10-27'))
    r = auditar_vigencias(base, date(2026, 10, 28), 45)
    assert {x['id']: x['situacao'] for x in r['ocorrencias']} == {
        'ANTERIOR': 'VENCIDO', 'HOJE': 'A_VENCER', 'LIMITE': 'A_VENCER'}
    assert next(x for x in r['ocorrencias'] if x['id'] == 'HOJE')['dias_restantes'] == 0


def test_inativo_e_fim_vazio_nao_sao_alerta_de_vencimento():
    from scripts.verificar_vigencias import auditar_vigencias
    r = auditar_vigencias(base_com(beneficio('INATIVO', '2026-10-27', ativo='NAO'),
                                  beneficio('SEM_PRAZO', None)), date(2026, 10, 28))
    assert r['ocorrencias'] == []


@pytest.mark.parametrize('campos', [
    {'vigencia_fim': 'data_invalida'}, {'vigencia_inicio': '2027-01-01', 'vigencia_fim': '2026-12-31'},
    {'vigencia_inicio': 'invalido', 'vigencia_fim': None},
])
def test_data_inconsistente_e_apontada_mesmo_fora_do_horizonte(campos):
    from scripts.verificar_vigencias import auditar_vigencias
    r = auditar_vigencias(base_com(beneficio('RUIM', None, **campos)), date(2026, 10, 28))
    assert r['ocorrencias'][0]['situacao'] == 'DATA_INCONSISTENTE'


def test_fontes_legais_tambem_entram_sem_repetir_como_beneficio():
    from scripts.verificar_vigencias import auditar_vigencias
    base = base_com()
    base.legislacao = pd.DataFrame([{'id_legislacao': 'LEI', 'ativo': 'SIM', 'vigencia_fim': '2026-10-29'}])
    r = auditar_vigencias(base, date(2026, 10, 28))
    assert r['ocorrencias'][0]['tabela'] == 'legislacao'
    assert r['ocorrencias'][0]['id'] == 'LEI'
    assert r['ocorrencias'][0]['ncm'] is None


@pytest.mark.parametrize('dias', [-1, True, '45'])
def test_rejeita_horizonte_invalido(dias):
    from scripts.verificar_vigencias import auditar_vigencias
    with pytest.raises(ValueError):
        auditar_vigencias(base_com(), date(2026, 10, 28), dias)

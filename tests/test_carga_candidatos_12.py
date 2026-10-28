"""Carga explícita aprovada não pode confirmar alíquota nem sobrescrever cadastros."""

from datetime import date

import pandas as pd
import pytest

from scripts.carga_candidatos_12 import preparar_carga, gerar_sql_carga
from src.busca import consultar, pendencias_validacao
from src.modelos import BaseTributaria


def proposta(**alteracoes):
    return {
        'proposta_id': 'TESTE', 'ncm': '12345678', 'familia_id': 'FAMILIA_TESTE',
        'descricao_legal': 'Produto sintético', 'aliquota_proposta_condicionada': '12',
        'aliquota_confirmada': '', 'status': 'PENDENTE_REVISAO_FISCAL',
        'acao': 'REVISAR_NOVA_REGRA', 'alinea': 'a',
        'fonte': 'https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm',
        'trecho_legal': 'Trecho sintético para teste', 'condicoes': 'Comprovar condição de teste.',
        'vigencia_redacao_inicio': '2021-01-01', 'data_referencia': '2026-10-26',
        **alteracoes,
    }


def test_candidato_exato_tem_condicao_visivel_e_inicio_na_carga():
    carga = preparar_carga([proposta()], {'12345678'}, date(2026, 10, 26))
    regra = carga['aliquotas'][0]
    assert regra['exige_descricao'] == 'SIM'
    assert regra['tipo_correspondencia'] == 'EXATO'
    assert regra['vigencia_inicio'] == '2026-10-26'
    assert regra['descricao_regra'].startswith('Possibilidade condicionada de 12%')
    assert 'Comprovar condição de teste.' in regra['observacao']
    assert regra['regra_consolidada_id'] is None and regra['evidencia_ncm_id'] is None


def test_candidato_nunca_e_priorizado_pelo_motor_nem_no_app_atual():
    carga = preparar_carga([proposta()], {'12345678'}, date(2026, 10, 26))
    base = BaseTributaria(ncm=pd.DataFrame([{'ncm':'12345678', 'ativo':'SIM', 'descricao_oficial':'Sintético'}]),
                         aliquotas=pd.DataFrame(carga['aliquotas']), beneficios=pd.DataFrame(),
                         legislacao=pd.DataFrame(carga['legislacao']))
    resultado = consultar(base, '12345678', date(2026, 10, 26))
    assert resultado.regra_priorizada is None
    assert resultado.situacao == 'VERIFICACAO_NECESSARIA'
    assert len(resultado.possibilidades_aliquota) == 1
    assert pendencias_validacao(resultado.possibilidades_aliquota[0])


@pytest.mark.parametrize('alteracoes', [
    {'ncm':'87654321'}, {'status':'CONFIRMADO'}, {'aliquota_confirmada':'12'},
    {'aliquota_proposta_condicionada':'19'}, {'condicoes':''}, {'fonte':'https://example.invalid'},
    {'data_referencia':'2026-10-25'}, {'alinea':'e'}, {'alinea':''}, {'alinea':None},
    {'alinea':'ab'}, {'familia_id':'X;SELECT'},
])
def test_aborta_carga_incompativel_com_aprovacao(alteracoes):
    with pytest.raises(ValueError):
        preparar_carga([proposta(**alteracoes)], {'12345678'}, date(2026, 10, 26))


def test_preserva_vinculos_existentes_e_nao_recria_os_14():
    carga = preparar_carga([proposta(acao='REVISAR_VINCULO_EXISTENTE')],
                          {'12345678'}, date(2026, 10, 26))
    assert carga['aliquotas'] == carga['legislacao'] == []


def test_duas_familias_do_mesmo_ncm_sao_preservadas():
    carga = preparar_carga([proposta(), proposta(familia_id='OUTRA')],
                          {'12345678'}, date(2026, 10, 26))
    assert len(carga['aliquotas']) == 2
    assert len(carga['legislacao']) == 1


def test_duplicidade_divergente_nao_e_silenciada():
    with pytest.raises(ValueError, match='duplicad'):
        preparar_carga([proposta(), proposta(condicoes='Outro conteúdo')],
                      {'12345678'}, date(2026, 10, 26))


def test_sql_e_atomico_com_guarda_de_conflito_sem_sobrescrever():
    sql = gerar_sql_carga(preparar_carga([proposta(condicoes="Condição d'água.")],
                                       {'12345678'}, date(2026, 10, 26)))
    assert sql.startswith('DO $carga12$')
    assert 'LOCK TABLE public.ncm IN SHARE MODE' in sql
    assert 'ON CONFLICT (id_regra) DO NOTHING' in sql
    assert 'RAISE EXCEPTION' in sql
    assert 'DO UPDATE' not in sql and 'DELETE FROM' not in sql
    assert "d''água" in sql


def test_sql_rejeita_delimitador_do_bloco_no_texto_livre():
    carga = preparar_carga([proposta(condicoes='Texto contendo $carga12$ deve ser rejeitado.')],
                           {'12345678'}, date(2026, 10, 26))
    with pytest.raises(ValueError, match='Delimitador'):
        gerar_sql_carga(carga)

"""Propostas não podem transformar aproximação de NCM em alíquota confirmada."""

from datetime import date
from pathlib import Path

import pytest

from src.planejamento_cobertura import carregar_familias, planejar_cobertura

CATALOGO = Path(__file__).resolve().parents[1] / 'revisao' / 'familias_12_cte_go.json'


def planejar(*codigos, referencia=date(2026, 10, 26), aliquotas=()):
    return planejar_cobertura(
        [{'ncm': c, 'descricao_oficial': 'Descrição de teste', 'ativo': 'SIM'} for c in codigos],
        list(aliquotas), carregar_familias(CATALOGO), referencia,
    )


@pytest.mark.parametrize('codigo,familia', [
    ('04069090', 'QUEIJO'), ('04032000', 'IOGURTE'), ('10063019', 'ARROZ'),
    ('07133329', 'FEIJAO'), ('15079019', 'OLEO_VEGETAL'), ('11062000', 'FARINHA_MANDIOCA'),
    ('22090000', 'VINAGRE'), ('25010020', 'SAL_IODADO'), ('96190000', 'ABSORVENTE'),
    ('34013000', 'SABONETE'), ('28289011', 'AGUA_SANITARIA'), ('36050000', 'FOSFORO'),
    ('19059090', 'PAO_FRANCES'), ('27160000', 'ENERGIA_RURAL'), ('07020000', 'HORTIFRUTICOLA'),
    ('03021400', 'CARNE_PEIXE'), ('02071400', 'CARNE_GADO_AVE'), ('01051110', 'AVE_VIVA'),
    ('04012090', 'LEITE'), ('04072100', 'OVO'), ('17011400', 'RAPADURA'),
    ('07136010', 'FEIJAO'), ('07136090', 'FEIJAO'),
])
def test_correspondencias_sao_condicionais(codigo, familia):
    # O vínculo é sempre uma proposta condicionada, mesmo para descrição inequívoca.
    linhas, propostas = planejar(codigo)
    assert familia in {p['familia_id'] for p in propostas}
    assert all(p['status'] == 'PENDENTE_REVISAO_FISCAL' for p in propostas)
    assert all(p['aliquota_proposta_condicionada'] == '12' for p in propostas)
    assert linhas[0]['aliquota_confirmada'] == ''


@pytest.mark.parametrize('codigo', ['15092000', '15101000', '15153000', '15159010',
                                    '15159021', '15156000', '04029900', '04021010',
                                    '03061710', '19024000', '48182000', '33062000',
                                    '34012090', '11081400', '22030000', '02109100',
                                    '02109200', '02109300', '03054100', '03055100',
                                    '08011100', '08062000', '08041020', '08042020'])
def test_nao_estende_12_a_produto_irmao_ou_dispositivo_invalido(codigo):
    linhas, propostas = planejar(codigo)
    assert not propostas
    assert linhas[0]['aliquota_confirmada'] == ''
    assert linhas[0]['situacao'] == 'SEM_CORRESPONDENCIA_NESTE_ESCOPO'


def test_inventario_inclui_cada_ncm_uma_vez_sem_presumir_19():
    linhas, _ = planejar('04069090', '84713012', '48181000')
    assert {l['ncm'] for l in linhas} == {'04069090', '84713012', '48181000'}
    assert len(linhas) == 3
    assert all(l['aliquota_confirmada'] == '' for l in linhas)
    assert all(l['referencia_geral_condicionada'] == '19' for l in linhas)


def test_duplicidade_de_ncm_aborta_sem_ocultar_linha():
    with pytest.raises(ValueError, match='duplicado'):
        planejar('04069090', '04069090')


def test_nao_gera_proposta_fora_da_vigencia_documentada():
    linhas, propostas = planejar('04069090', referencia=date(2020, 12, 31))
    assert not propostas
    assert linhas[0]['referencia_geral_condicionada'] == ''


def test_mantem_cadastro_existente_e_multiplas_familias_sem_escolha():
    regras = [{'id_regra': 'TESTE', 'chave_ncm': '17011400', 'tipo_correspondencia': 'EXATO',
               'ativo': 'SIM', 'aliquota_icms': 12, 'vigencia_inicio': '2021-01-01',
               'vigencia_fim': None}]
    linhas, propostas = planejar('17011400', aliquotas=regras)
    assert linhas[0]['cadastros_existentes'] == 'TESTE'
    assert {'ACUCAR', 'RAPADURA'} <= {p['familia_id'] for p in propostas}
    assert all(p['acao'] == 'REVISAR_VINCULO_EXISTENTE' for p in propostas)
    assert regras[0]['aliquota_icms'] == 12


def test_regra_inativa_ou_vencida_nao_comprova_cobertura_atual():
    regras = [dict(id_regra='VENCIDA', chave_ncm='04069090', tipo_correspondencia='EXATO',
                   ativo='SIM', vigencia_inicio='2000-01-01', vigencia_fim='2020-12-31'),
              dict(id_regra='INATIVA', chave_ncm='04069090', tipo_correspondencia='EXATO',
                   ativo='NAO', vigencia_inicio='2000-01-01', vigencia_fim=None)]
    linhas, propostas = planejar('04069090', aliquotas=regras)
    assert linhas[0]['cadastros_existentes'] == ''
    assert propostas[0]['acao'] == 'REVISAR_NOVA_REGRA'


def test_catalogo_cobre_todas_as_alineas_atuais_sem_revogadas():
    familias = carregar_familias(CATALOGO)
    assert {f['alinea'] for f in familias} == set('abcdfh')
    assert all(f['condicoes'] and f['trecho_legal'] and f['fonte'] for f in familias)


def test_inativo_nao_e_incluido_e_ncm_invalido_aborta():
    familias = carregar_familias(CATALOGO)
    linhas, propostas = planejar_cobertura([{'ncm': '04069090', 'ativo': 'NAO'}], [], familias,
                                          date(2026, 10, 26))
    assert linhas == propostas == []
    with pytest.raises(ValueError, match='inválido'):
        planejar('0406abcd')


def test_cli_gera_relatorio_completo_sem_percentual_confirmado(tmp_path):
    import json
    from scripts.planejar_cobertura_12 import gerar_relatorios

    snapshot = dict(ncm=[dict(ncm='04069090', ativo='SIM'), dict(ncm='84713012', ativo='SIM')],
                    aliquotas=[], beneficios=[], legislacao=[])
    destino = tmp_path / 'resultado'
    resumo = gerar_relatorios(snapshot, carregar_familias(CATALOGO), date(2026, 10, 26),
                             destino, evidencias={'fonte_teste': True})
    assert resumo['ncms_examinados'] == 2
    assert resumo['ncms_com_candidato_12'] == 1
    assert resumo['ncms_sem_correspondencia_no_escopo'] == 1
    assert resumo['ncms_com_aliquota_confirmada'] == 0
    assert resumo['gravacoes_postgresql'] == 0
    assert '04069090' in (destino / 'todos_ncms.csv').read_text(encoding='utf-8-sig')
    assert '84713012' in (destino / 'todos_ncms.csv').read_text(encoding='utf-8-sig')
    assert json.loads((destino / 'resumo.json').read_text())['evidencias'] == {'fonte_teste': True}


def test_nova_proposta_nunca_e_ativada_ou_equiparada_a_cadastro_operacional():
    _, propostas = planejar('04069090')
    assert all('ativo' not in p and 'id_regra' not in p for p in propostas)
    assert all(p['acao'] != 'PUBLICAR' for p in propostas)


def test_cafe_soluvel_puro_entra_como_possibilidade_sem_confundir_beneficio():
    linhas, propostas = planejar('21011110')
    assert len(propostas) == 1
    proposta = propostas[0]
    assert proposta['familia_id'] == 'CAFE_SOLUVEL'
    assert proposta['aliquota_proposta_condicionada'] == '12'
    assert proposta['status'] == 'PENDENTE_REVISAO_FISCAL'
    assert linhas[0]['aliquota_confirmada'] == ''
    assert '225/2022' in proposta['condicoes']
    assert 'não confirma' in proposta['condicoes']


@pytest.mark.parametrize('codigo', ['21011190', '21011200'])
def test_cafe_soluvel_nao_estende_12_a_outros_extratos_ou_preparacoes(codigo):
    _, propostas = planejar(codigo)
    assert not propostas

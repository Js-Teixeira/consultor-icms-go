"""Retira um percentual não demonstrado, preservando identidade e evidência anterior."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re

from src.dados.schema import TABELAS

COLUNAS = {c.name for c in TABELAS['Aliquotas'].columns}
EDITAVEIS = {'aliquota_icms', 'descricao_regra', 'observacao', 'exige_descricao'}
TITULO = 'ALÍQUOTA ESPECÍFICA NÃO COMPROVADA'


def _anterior_valido(r: dict) -> bool:
    try:
        doze = Decimal(str(r.get('aliquota_icms'))) == 12
    except (InvalidOperation, ValueError):
        doze = False
    return (set(r) == COLUNAS and doze and bool(r.get('id_regra'))
            and bool(re.fullmatch(r'[0-9]{8}', r.get('chave_ncm', '')))
            and r.get('tipo_correspondencia') == 'EXATO' and r.get('ativo') == 'SIM')


def preparar_suspensao(anteriores: list[dict], motivos: dict[str, str], referencia: date) -> list[dict]:
    if (not anteriores or set(motivos) != {r.get('chave_ncm') for r in anteriores}
            or any(not isinstance(m, str) or not m.strip() for m in motivos.values())
            or any(not _anterior_valido(r) for r in anteriores)):
        raise ValueError('Revisão sem decisão explícita ou fora dos vínculos condicionais de 12%.')
    if len({r['id_regra'] for r in anteriores}) != len(anteriores):
        raise ValueError('Identificador de revisão duplicado.')
    resultado = []
    for r in anteriores:
        novo = deepcopy(r)
        novo.update(aliquota_icms=None, descricao_regra=TITULO+' — conferir produto e operação',
                    exige_descricao='SIM')
        novo['observacao'] = (
            f'REVISÃO {referencia.isoformat()}: percentual específico não comprovado para o NCM genérico. '
            '12% histórico preservado nesta observação e na evidência anterior, sem homologação. '
            'O campo numérico fica vazio; isso não afirma alíquota zero nem confirma 19%. '
            + motivos[r['chave_ncm']].strip() + ' Não aplicar automaticamente. Cadastro anterior: '
            + (r.get('observacao') or 'sem observação.'))
        resultado.append({'antes': deepcopy(r), 'depois': novo})
    return resultado


def gerar_sql_suspensao(revisoes: list[dict], hash_ncm: str) -> str:
    if not revisoes or not re.fullmatch(r'[a-f0-9]{32}', hash_ncm):
        raise ValueError('Revisão ou hash NCM ausente/inválido.')
    ids = set()
    for revisao in revisoes:
        a, d = revisao['antes'], revisao['depois']
        if (not _anterior_valido(a) or set(d) != COLUNAS or a['id_regra'] in ids
                or any(a[c] != d[c] for c in COLUNAS-EDITAVEIS)
                or d['aliquota_icms'] is not None or d['exige_descricao'] != 'SIM'
                or not d['descricao_regra'].startswith(TITULO)
                or not d.get('observacao') or '12% histórico' not in d['observacao']):
            raise ValueError('Revisão alteraria identidade, fundamento ou percentual fora do autorizado.')
        ids.add(a['id_regra'])
    literal = json.dumps(revisoes, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if '$suspender$' in literal:
        raise ValueError('Delimitador incompatível no conteúdo.')
    literal = literal.replace("'", "''")
    return f"""DO $suspender$
DECLARE revisoes jsonb := '{literal}'::jsonb;
BEGIN
    LOCK TABLE public.ncm IN SHARE MODE;
    LOCK TABLE public.aliquotas IN SHARE ROW EXCLUSIVE MODE;
    IF (SELECT md5(string_agg(ncm||'|'||coalesce(descricao_oficial,'')||'|'||coalesce(ativo,''),E'\\n' ORDER BY ncm)) FROM public.ncm)
       IS DISTINCT FROM '{hash_ncm}'
    THEN RAISE EXCEPTION 'Catálogo NCM mudou; revisão cancelada'; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(revisoes) p
        LEFT JOIN public.aliquotas t ON t.id_regra=p->'antes'->>'id_regra'
        WHERE t.id_regra IS NULL OR
              (to_jsonb(t) IS DISTINCT FROM p->'antes' AND to_jsonb(t) IS DISTINCT FROM p->'depois'))
    THEN RAISE EXCEPTION 'Conflito na revisão; nenhum percentual foi alterado'; END IF;
    UPDATE public.aliquotas t SET aliquota_icms=NULL,
        descricao_regra=p->'depois'->>'descricao_regra',
        observacao=p->'depois'->>'observacao', exige_descricao='SIM'
    FROM jsonb_array_elements(revisoes) p
    WHERE t.id_regra=p->'antes'->>'id_regra' AND to_jsonb(t) IS DISTINCT FROM p->'depois';
END
$suspender$;"""

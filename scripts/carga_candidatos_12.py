"""Prepara carga aprovada e SQL atômico; não abre conexão nem aplica automaticamente."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

FONTE = 'https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm'


def preparar_carga(propostas: list[dict], ncms_ativos: set[str], referencia: date) -> dict[str, Any]:
    """Converte apenas propostas de NOVOS códigos em possibilidades condicionais.

    A autorização é para cadastro condicional, nunca aprovação do enquadramento.
    A função não consulta, não conecta e não modifica o banco.
    """
    leis, regras, vistos = {}, [], set()
    lote = referencia.strftime('%Y%m%d')
    for p in propostas:
        if p.get('acao') == 'REVISAR_VINCULO_EXISTENTE':
            continue
        codigo, familia = p.get('ncm', ''), p.get('familia_id', '')
        if (p.get('acao') != 'REVISAR_NOVA_REGRA'
                or p.get('status') != 'PENDENTE_REVISAO_FISCAL'
                or p.get('aliquota_confirmada') or p.get('aliquota_proposta_condicionada') != '12'
                or p.get('data_referencia') != referencia.isoformat()
                or codigo not in ncms_ativos or not re.fullmatch(r'[0-9]{8}', codigo)
                or not re.fullmatch(r'[A-Z_]+', familia) or p.get('alinea') not in {'a','b','c','d','f','h'}
                or not p.get('condicoes') or not p.get('trecho_legal') or not p.get('descricao_legal')
                or p.get('fonte') != FONTE):
            raise ValueError('Proposta incompatível com a carga condicional aprovada.')
        inicio = date.fromisoformat(p['vigencia_redacao_inicio'])
        if inicio > referencia:
            raise ValueError('Redação legal futura.')
        identificador = f'CAND12_{lote}_{familia}_{codigo}'
        if identificador in vistos:
            raise ValueError('Proposta duplicada no lote.')
        vistos.add(identificador)
        id_lei = f"LEG_CAND12_{lote}_{p['alinea'].upper()}"
        lei = {
            'id_legislacao': id_lei,
            'norma': 'Lei nº 11.651/1991 - Código Tributário do Estado de Goiás',
            'numero': '11.651', 'ano': '1991', 'anexo': None, 'artigo': '27',
            'paragrafo': None, 'inciso': 'II', 'alinea': p['alinea'], 'item': None,
            'resumo': 'Referência legal para possibilidades condicionais de 12%; não confirma vínculo NCM/produto.',
            'texto_relevante': p['trecho_legal'], 'url_fonte': FONTE,
            'vigencia_inicio': inicio.isoformat(), 'vigencia_fim': None,
            'data_verificacao': referencia.isoformat(), 'ativo': 'SIM',
        }
        if id_lei in leis and leis[id_lei] != lei:
            raise ValueError('Fundamentos divergentes na mesma alínea.')
        leis[id_lei] = lei
        regras.append({
            'id_regra': identificador, 'chave_ncm': codigo, 'tipo_correspondencia': 'EXATO',
            'descricao_regra': f"Possibilidade condicionada de 12% — {p['descricao_legal']}",
            'palavras_chave': p['descricao_legal'], 'aliquota_icms': 12,
            'adicional_percentual': None, 'id_legislacao': id_lei,
            'regra_consolidada_id': None, 'evidencia_ncm_id': None,
            'vigencia_inicio': referencia.isoformat(), 'vigencia_fim': None,
            'observacao': ('CANDIDATO CONDICIONAL. Cadastro autorizado como possibilidade, sem confirmação '
                           'de enquadramento fiscal por NCM. ' + p['condicoes'] +
                           f" Início do cadastro: {referencia.isoformat()}; redação legal desde {inicio.isoformat()}. "
                           f"Vínculo técnico por nomenclatura; proposta {p['proposta_id']}. "
                           'Conferir benefícios, ST, adicionais e demais condições da operação. '
                           f'Lote CAND12_{lote}.'),
            'ativo': 'SIM', 'exige_descricao': 'SIM',
        })
    return {'lote': f'CAND12_{lote}', 'legislacao': list(leis.values()), 'aliquotas': regras}


def gerar_sql_carga(carga: dict) -> str:
    """Um único bloco transacional, apenas INSERT, sem sobrescrever conflitos.

    Reexecução é idempotente somente se todos os registros coincidentes são
    idênticos. Divergência de conteúdo, código não ativo ou outro cadastro no
    NCM alvo aborta o bloco inteiro antes de qualquer inserção.
    """
    literal = json.dumps(carga, ensure_ascii=False, separators=(',', ':'))
    if '$carga12$' in literal:
        raise ValueError('Delimitador incompatível no conteúdo da carga.')
    literal = literal.replace("'", "''")
    return """DO $carga12$
DECLARE
    carga jsonb := '""" + literal + """'::jsonb;
BEGIN
    LOCK TABLE public.ncm IN SHARE MODE;
    LOCK TABLE public.legislacao, public.aliquotas IN SHARE ROW EXCLUSIVE MODE;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(carga->'aliquotas') p
        LEFT JOIN public.ncm n ON n.ncm = p->>'chave_ncm' AND upper(trim(n.ativo))='SIM'
        WHERE n.ncm IS NULL OR p->>'exige_descricao' <> 'SIM'
           OR p->>'tipo_correspondencia' <> 'EXATO' OR p->>'ativo' <> 'SIM'
           OR (p->>'aliquota_icms')::numeric <> 12
    ) THEN RAISE EXCEPTION 'Carga incompatível: NCM ou condição não autorizada'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(carga->'legislacao') p
        JOIN public.legislacao l ON l.id_legislacao=p->>'id_legislacao'
        WHERE NOT to_jsonb(l) @> p
    ) THEN RAISE EXCEPTION 'Conflito no fundamento; nenhum registro foi sobrescrito'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(carga->'aliquotas') p
        JOIN public.aliquotas a ON a.id_regra=p->>'id_regra'
        WHERE NOT to_jsonb(a) @> p
    ) THEN RAISE EXCEPTION 'Conflito na regra; nenhum registro foi sobrescrito'; END IF;
    IF EXISTS (
        SELECT 1 FROM public.aliquotas a
        WHERE a.chave_ncm IN (SELECT p->>'chave_ncm' FROM jsonb_array_elements(carga->'aliquotas') p)
          AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(carga->'aliquotas') p
                          WHERE p->>'id_regra'=a.id_regra)
    ) THEN RAISE EXCEPTION 'NCM alvo já possui outro cadastro; revisar mudança concorrente'; END IF;
    INSERT INTO public.legislacao
        SELECT * FROM jsonb_populate_recordset(NULL::public.legislacao, carga->'legislacao')
        ON CONFLICT (id_legislacao) DO NOTHING;
    INSERT INTO public.aliquotas
        SELECT * FROM jsonb_populate_recordset(NULL::public.aliquotas, carga->'aliquotas')
        ON CONFLICT (id_regra) DO NOTHING;
END
$carga12$;"""

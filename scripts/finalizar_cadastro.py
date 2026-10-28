"""Valida e prepara uma carga condicional explícita; não abre conexão."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from src.dados.schema import TABELAS

TABELAS_CARGA = {'legislacao': TABELAS['Legislacao'],
                 'aliquotas': TABELAS['Aliquotas'], 'beneficios': TABELAS['Beneficios']}


def _percentual(valor):
    try:
        numero = Decimal(str(valor))
        return numero.is_finite() and 0 <= numero <= 100
    except (InvalidOperation, ValueError):
        return False


def validar_lote(lote: dict, ncms_ativos: set[str]) -> None:
    """Rejeita campos extras, vínculos ausentes, confirmação e alterações de chave."""
    if lote.get('natureza') != 'CANDIDATOS_CONDICIONAIS':
        raise ValueError('Carga não autorizada como candidatos condicionais.')
    referencia = date.fromisoformat(lote['referencia'])
    leis = set(lote.get('legislacao_existente', []))
    leis.update(r['id_legislacao'] for r in lote['legislacao'])
    for nome, tabela in TABELAS_CARGA.items():
        colunas = {c.name for c in tabela.columns}
        pk = next(iter(tabela.primary_key.columns)).name
        registros = list(lote[nome])
        vistos = set()
        for alteracao in lote.get('revisoes', {}).get(nome, []):
            antes, depois = alteracao['antes'], alteracao['depois']
            imutaveis = [pk, 'chave_ncm', 'tipo_correspondencia']
            if nome == 'aliquotas':
                imutaveis += ['aliquota_icms', 'id_legislacao', 'vigencia_inicio', 'vigencia_fim', 'ativo']
            if any(antes.get(c) != depois.get(c) for c in imutaveis):
                raise ValueError('Revisão tenta alterar chave, NCM ou percentual histórico.')
            registros.append(depois)
        for r in registros:
            if set(r) - colunas or not r.get(pk) or r[pk] in vistos:
                raise ValueError('Campos ou identificador incompatíveis/duplicados.')
            vistos.add(r[pk])
            if r.get('ativo') != 'SIM':
                raise ValueError('Esta carga só cadastra candidatos ativos, sem exclusões.')
            inicio = date.fromisoformat(r['vigencia_inicio'])
            fim = date.fromisoformat(r['vigencia_fim']) if r.get('vigencia_fim') else date.max
            if not inicio <= referencia <= fim:
                raise ValueError('Vigência não pertinente à data da carga.')
            if nome == 'legislacao':
                host = urlparse(r.get('url_fonte', '')).hostname
                if host not in {'appasp.economia.go.gov.br', 'legisla.casacivil.go.gov.br'}:
                    raise ValueError('Fonte legal não oficial de Goiás.')
                if not all(r.get(c) for c in ['norma', 'numero', 'ano', 'texto_relevante', 'artigo']):
                    raise ValueError('Identificação ou evidência legal incompleta.')
                verificada = date.fromisoformat(r['data_verificacao'])
                if verificada > referencia:
                    raise ValueError('Verificação futura.')
                continue
            if (not re.fullmatch(r'[0-9]{8}', r.get('chave_ncm', ''))
                    or r['chave_ncm'] not in ncms_ativos
                    or r.get('tipo_correspondencia') != 'EXATO'
                    or r.get('exige_descricao') != 'SIM'
                    or r.get('id_legislacao') not in leis
                    or not r.get('descricao_regra')
                    or r.get('regra_consolidada_id') is not None
                    or r.get('evidencia_ncm_id') is not None):
                raise ValueError('Candidato sem NCM, condição ou fundamento válido.')
            if nome == 'aliquotas':
                if Decimal(str(r.get('aliquota_icms'))) != 12 or not r.get('observacao'):
                    raise ValueError('Alíquota ou condição incompatível.')
                continue
            if (r.get('escopo_operacao') not in {'INTERNA', 'AMBAS'}
                    or not r.get('condicoes') or r.get('aplicacao') != 'ALTERNATIVO'):
                raise ValueError('Condições ou escopo de benefício ausentes.')
            tipo = r.get('tipo_beneficio')
            campo = {'CARGA_EFETIVA': 'carga_efetiva',
                     'REDUCAO_BASE_CALCULO': 'percentual_reducao_bc',
                     'CREDITO_OUTORGADO': 'credito_outorgado_percentual'}.get(tipo)
            campos = ['carga_efetiva', 'percentual_reducao_bc', 'credito_outorgado_percentual']
            if tipo == 'ISENCAO':
                if any(r.get(c) is not None for c in campos):
                    raise ValueError('Isenção não deve inventar percentual.')
            elif not campo or not _percentual(r.get(campo)):
                raise ValueError('Tipo ou percentual do benefício inválido.')
            elif any(r.get(c) is not None for c in campos if c != campo):
                raise ValueError('Não misturar carga, redução e crédito em uma hipótese.')


def gerar_sql(lote: dict, ncms_ativos: set[str]) -> str:
    """SQL transacional idempotente; revisões exigem estado anterior OU novo exato."""
    validar_lote(lote, ncms_ativos)
    literal = json.dumps(lote, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if '$finalizacao$' in literal:
        raise ValueError('Delimitador incompatível no conteúdo.')
    literal = literal.replace("'", "''")
    partes = [f"""DO $finalizacao$
DECLARE carga jsonb := '{literal}'::jsonb;
BEGIN
    LOCK TABLE public.ncm IN SHARE MODE;
    LOCK TABLE public.legislacao, public.aliquotas, public.beneficios IN SHARE ROW EXCLUSIVE MODE;
    IF EXISTS (
        SELECT 1 FROM (
            SELECT p->>'chave_ncm' AS codigo FROM jsonb_array_elements(carga->'aliquotas') p
            UNION ALL SELECT p->>'chave_ncm' FROM jsonb_array_elements(carga->'beneficios') p
            UNION ALL SELECT p->'depois'->>'chave_ncm' FROM jsonb_array_elements(carga->'revisoes'->'aliquotas') p
            UNION ALL SELECT p->'depois'->>'chave_ncm' FROM jsonb_array_elements(carga->'revisoes'->'beneficios') p
        ) a LEFT JOIN public.ncm n ON n.ncm=a.codigo AND upper(trim(n.ativo))='SIM'
        WHERE n.ncm IS NULL
    ) THEN RAISE EXCEPTION 'NCM ausente ou inativo; carga cancelada'; END IF;
    IF carga->>'hash_ncm' IS NOT NULL AND
       (SELECT md5(string_agg(ncm||'|'||coalesce(descricao_oficial,'')||'|'||coalesce(ativo,''),E'\\n' ORDER BY ncm)) FROM public.ncm)
       IS DISTINCT FROM carga->>'hash_ncm'
    THEN RAISE EXCEPTION 'Catálogo NCM mudou; revisar a classificação'; END IF;
    IF EXISTS (
        SELECT 1 FROM (
            SELECT p->>'id_legislacao' AS id FROM jsonb_array_elements(carga->'aliquotas') p
            UNION ALL SELECT p->>'id_legislacao' FROM jsonb_array_elements(carga->'beneficios') p
            UNION ALL SELECT p->'depois'->>'id_legislacao' FROM jsonb_array_elements(carga->'revisoes'->'aliquotas') p
            UNION ALL SELECT p->'depois'->>'id_legislacao' FROM jsonb_array_elements(carga->'revisoes'->'beneficios') p
        ) a LEFT JOIN public.legislacao l ON l.id_legislacao=a.id AND upper(trim(l.ativo))='SIM'
        WHERE l.id_legislacao IS NULL AND NOT EXISTS
            (SELECT 1 FROM jsonb_array_elements(carga->'legislacao') p
             WHERE p->>'id_legislacao'=a.id AND p->>'ativo'='SIM')
    ) THEN RAISE EXCEPTION 'Fundamento ausente ou inativo; carga cancelada'; END IF;
"""]
    for nome, tabela in TABELAS_CARGA.items():
        pk = next(iter(tabela.primary_key.columns)).name
        partes.append(f"""
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(carga->'{nome}') p
        JOIN public.{nome} t ON t.{pk}=p->>'{pk}'
        WHERE NOT to_jsonb(t) @> p)
    THEN RAISE EXCEPTION 'Conflito na inserção em {nome}; carga cancelada'; END IF;
""")
        if nome != 'legislacao':
            partes.append(f"""
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(carga->'revisoes'->'{nome}') p
        LEFT JOIN public.{nome} t ON t.{pk}=p->'antes'->>'{pk}'
        WHERE t.{pk} IS NULL OR (to_jsonb(t) IS DISTINCT FROM p->'antes'
                              AND to_jsonb(t) IS DISTINCT FROM p->'depois'))
    THEN RAISE EXCEPTION 'Conflito na revisão de {nome}; carga cancelada'; END IF;
""")
    partes.append("""
    IF EXISTS (SELECT 1 FROM public.aliquotas t
        JOIN jsonb_array_elements(carga->'aliquotas') p ON t.chave_ncm=p->>'chave_ncm'
        WHERE t.id_regra <> p->>'id_regra')
    THEN RAISE EXCEPTION 'Outro cadastro surgiu no NCM alvo; revisar antes'; END IF;
""")
    for nome, tabela in TABELAS_CARGA.items():
        pk = next(iter(tabela.primary_key.columns)).name
        partes.append(f"""
    INSERT INTO public.{nome}
        SELECT * FROM jsonb_populate_recordset(NULL::public.{nome},carga->'{nome}')
        ON CONFLICT ({pk}) DO NOTHING;
""")
        if nome != 'legislacao':
            colunas = [c.name for c in tabela.columns if c.name != pk]
            partes.append(f"""
    UPDATE public.{nome} t SET ({','.join(colunas)}) =
        (SELECT {','.join('r.'+c for c in colunas)}
         FROM jsonb_populate_record(NULL::public.{nome},p->'depois') r)
    FROM jsonb_array_elements(carga->'revisoes'->'{nome}') p
    WHERE t.{pk}=p->'antes'->>'{pk}' AND to_jsonb(t) IS DISTINCT FROM p->'depois';
""")
    partes.append('END\n$finalizacao$;')
    return ''.join(partes)

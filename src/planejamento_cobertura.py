"""Planeja a revisão de todos os NCMs sem publicar regras tributárias."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


def carregar_familias(caminho: Path) -> list[dict[str, Any]]:
    documento = json.loads(caminho.read_text(encoding='utf-8'))
    if documento.get('natureza') != 'PROPOSTA_TECNICA_SEM_APROVACAO_FISCAL':
        raise ValueError('O catálogo deve declarar sua natureza de proposta técnica.')
    familias = documento['familias']
    ids = set()
    for familia in familias:
        if familia['id'] in ids:
            raise ValueError('Família duplicada.')
        ids.add(familia['id'])
        for campo in ('condicoes', 'fonte', 'trecho_legal', 'vigencia_inicio', 'produto'):
            if not familia.get(campo):
                raise ValueError(f'Família sem {campo}.')
        date.fromisoformat(familia['vigencia_inicio'])
        for chave in familia['prefixos'] + familia['excluir']:
            if not re.fullmatch(r'[0-9]{2,8}', chave):
                raise ValueError('Prefixo NCM inválido.')
    return familias


def _vigente(registro: dict, referencia: date) -> bool:
    try:
        inicio = date.fromisoformat(str(registro['vigencia_inicio'])[:10])
        fim = (date.fromisoformat(str(registro['vigencia_fim'])[:10])
               if registro.get('vigencia_fim') else date.max)
    except (ValueError, KeyError, TypeError):
        return False
    return inicio <= referencia <= fim


def _corresponde(codigo: str, regra: dict) -> bool:
    chave = str(regra.get('chave_ncm', '')).strip()
    tipo = str(regra.get('tipo_correspondencia', '')).upper()
    return ((tipo == 'EXATO' and chave == codigo) or
            (tipo == 'PREFIXO' and len(chave) in {2, 4, 6} and chave.isdigit()
             and codigo.startswith(chave)))


def planejar_cobertura(ncms: list[dict], aliquotas: list[dict], familias: list[dict],
                       referencia: date) -> tuple[list[dict], list[dict]]:
    """Uma linha por NCM ativo e zero ou mais propostas condicionadas por linha.

    Não confirma alíquotas, não escreve no banco, não cria regras para códigos
    ausentes e não transforma ausência de correspondência em enquadramento a 19%.
    A existência de cadastro é contabilizada sem atestar fundamento/enquadramento.
    """
    linhas, propostas = [], []
    vistos = set()
    ativas = [r for r in aliquotas if str(r.get('ativo', '')).strip().upper() == 'SIM'
              and _vigente(r, referencia)]
    familias_atuais = [f for f in familias if _vigente(f, referencia)]
    for registro in sorted(ncms, key=lambda r: str(r.get('ncm', ''))):
        if str(registro.get('ativo', '')).strip().upper() != 'SIM':
            continue
        codigo = str(registro.get('ncm', '')).strip()
        if not re.fullmatch(r'[0-9]{8}', codigo):
            raise ValueError(f'NCM inválido: {codigo!r}.')
        if codigo in vistos:
            raise ValueError(f'NCM duplicado: {codigo}.')
        vistos.add(codigo)
        existentes = [r for r in ativas if _corresponde(codigo, r)]
        correspondentes = [f for f in familias_atuais
                           if any(codigo.startswith(p) for p in f['prefixos'])
                           and not any(codigo.startswith(p) for p in f['excluir'])]
        ids_existentes = ';'.join(str(r['id_regra']) for r in existentes)
        for familia in correspondentes:
            propostas.append({
                'proposta_id': f"CTE27II_{familia['id']}_{codigo}",
                'ncm': codigo, 'descricao_oficial': registro.get('descricao_oficial', ''),
                'familia_id': familia['id'], 'descricao_legal': familia['produto'],
                'aliquota_proposta_condicionada': '12', 'aliquota_confirmada': '',
                'status': 'PENDENTE_REVISAO_FISCAL',
                'acao': 'REVISAR_VINCULO_EXISTENTE' if existentes else 'REVISAR_NOVA_REGRA',
                'cadastros_existentes': ids_existentes,
                'fundamento': f"Lei nº 11.651/1991, art. 27, II, {familia['alinea']}",
                'alinea': familia['alinea'], 'fonte': familia['fonte'],
                'trecho_legal': familia['trecho_legal'], 'condicoes': familia['condicoes'],
                'vigencia_redacao_inicio': familia['vigencia_inicio'],
                'vigencia_ncm': 'CONFERIR_NA_FONTE_NCM',
                'metodo_vinculo': 'PROPOSTA_TECNICA_POR_NOMENCLATURA',
                'data_referencia': referencia.isoformat(),
            })
        situacao = ('CADASTRO_EXISTENTE_PARA_REVISAO' if existentes else
                    'CANDIDATO_12_CONDICIONADO' if correspondentes else
                    'SEM_CORRESPONDENCIA_NESTE_ESCOPO')
        linhas.append({
            'ncm': codigo, 'descricao_oficial': registro.get('descricao_oficial', ''),
            'situacao': situacao, 'aliquota_confirmada': '',
            'referencia_geral_condicionada': '19' if referencia >= date(2024, 4, 1) else '',
            'cadastros_existentes': ids_existentes,
            'familias_candidatas_12': ';'.join(f['id'] for f in correspondentes),
            'quantidade_propostas': len(correspondentes), 'data_referencia': referencia.isoformat(),
            'pendencia': ('Conferir produto, operação, vigência, fundamento, benefícios, ST, '
                          'adicionais e regimes próprios. Ausência nesta triagem não confirma 19%.'),
        })
    return linhas, propostas

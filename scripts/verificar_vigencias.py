"""Audita prazos de cadastros ativos; não renova nem publica regras fiscais."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.busca import _data, texto
from src.modelos import BaseTributaria


def auditar_vigencias(base: BaseTributaria, referencia: date | None = None,
                     antecedencia: int = 45) -> dict:
    if type(antecedencia) is not int or not 0 <= antecedencia <= 366:
        raise ValueError('A antecedência deve ser um inteiro entre 0 e 366 dias.')
    referencia = referencia or datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    ocorrencias = []
    for nome, chave in [('aliquotas', 'id_regra'), ('beneficios', 'id_beneficio'),
                        ('legislacao', 'id_legislacao')]:
        for r in getattr(base, nome).to_dict('records'):
            if texto(r.get('ativo')).upper() != 'SIM':
                continue
            try:
                inicio, fim = _data(r.get('vigencia_inicio')), _data(r.get('vigencia_fim'))
                if inicio and fim and inicio > fim:
                    raise ValueError('Início posterior ao fim')
            except ValueError:
                situacao, dias = 'DATA_INCONSISTENTE', None
            else:
                if fim is None:
                    continue
                dias = (fim-referencia).days
                if dias > antecedencia:
                    continue
                situacao = 'VENCIDO' if dias < 0 else 'A_VENCER'
            ocorrencias.append({'tabela': nome, 'id': texto(r.get(chave)),
                                'ncm': texto(r.get('chave_ncm')) or None,
                                'vigencia_fim': texto(r.get('vigencia_fim')) or None,
                                'dias_restantes': dias, 'situacao': situacao})
    ocorrencias.sort(key=lambda r: (r['dias_restantes'] is not None,
                                   r['dias_restantes'] or 0, r['tabela'], r['id']))
    return {'data_referencia': referencia.isoformat(), 'antecedencia_dias': antecedencia,
            'somente_leitura': True, 'ocorrencias': ocorrencias}


def main() -> int:
    from scripts.auditar_integridade import carregar_postgres_somente_leitura
    from src.dados import criar_repositorio
    from src.dados import ErroConfiguracaoDados
    from sqlalchemy.exc import SQLAlchemyError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dias', type=int, default=45)
    parser.add_argument('--referencia', type=date.fromisoformat)
    args = parser.parse_args()
    if not 0 <= args.dias <= 366:
        parser.error('--dias deve estar entre 0 e 366.')
    try:
        repo = criar_repositorio(data_source='postgres')
        base, _ = carregar_postgres_somente_leitura(repo)
        relatorio = auditar_vigencias(base, args.referencia, args.dias)
    except (ErroConfiguracaoDados, SQLAlchemyError, RuntimeError):
        print('Não foi possível concluir a leitura das vigências no PostgreSQL.')
        return 1
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

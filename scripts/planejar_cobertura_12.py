"""Relatório integral do catálogo e propostas de 12%, sem gravação no PostgreSQL.

Uso: python -m scripts.planejar_cobertura_12 --snapshot arquivo.json
     --ncm-oficial nomenclatura.json --cte-html CTE.htm
     --referencia AAAA-MM-DD --saida diretorio
O snapshot é evidência de auditoria, nunca fonte alternativa da consulta pública.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select

from scripts.sincronizar_ncm_oficial import URL_CLASSIF, extrair_ncms
from src.dados import criar_repositorio
from src.dados.schema import TABELAS
from src.planejamento_cobertura import carregar_familias, planejar_cobertura

CATALOGO = Path(__file__).resolve().parents[1] / 'revisao' / 'familias_12_cte_go.json'
FONTE_CTE = 'https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm'


def _csv(caminho: Path, linhas: list[dict], campos_vazios: tuple[str, ...]) -> None:
    with caminho.open('w', encoding='utf-8-sig', newline='') as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]) if linhas else campos_vazios,
                                  delimiter=';')
        escritor.writeheader()
        escritor.writerows(linhas)


def gerar_relatorios(snapshot: dict, familias: list[dict], referencia: date,
                     destino: Path, *, evidencias: dict) -> dict:
    linhas, propostas = planejar_cobertura(snapshot['ncm'], snapshot['aliquotas'], familias, referencia)
    ids_propostos = {p['ncm'] for p in propostas}
    novas = {p['ncm'] for p in propostas if p['acao'] == 'REVISAR_NOVA_REGRA'}
    por_familia = Counter(p['familia_id'] for p in propostas)
    resumo = dict(
        natureza='PROPOSTA_TECNICA_SEM_APROVACAO_FISCAL', data_referencia=referencia.isoformat(),
        ncms_examinados=len(linhas), familias_legais=len(familias),
        familias_sem_correspondencia=[f['id'] for f in familias if f['id'] not in por_familia],
        ncms_com_candidato_12=len(ids_propostos), ncms_novos_candidatos_12=len(novas),
        propostas_ncm_familia=len(propostas), propostas_por_familia=dict(sorted(por_familia.items())),
        ncms_com_cadastro_existente=sum(bool(l['cadastros_existentes']) for l in linhas),
        ncms_sem_correspondencia_no_escopo=sum(l['situacao'] == 'SEM_CORRESPONDENCIA_NESTE_ESCOPO'
                                             for l in linhas),
        ncms_com_aliquota_confirmada=0, gravacoes_postgresql=0, evidencias=evidencias,
        limites=[
            'Todos os NCMs ativos do catálogo fornecido foram examinados; não é cobertura fiscal definitiva.',
            'Vínculos por prefixo são propostas técnicas de revisão, não listas NCM publicadas pela lei.',
            'O escopo desta rodada é art. 27, II, alíneas a, b, c, d, f e h do CTE/GO.',
            'Ausência neste escopo não comprova alíquota de 19% nem inexistência de benefício.',
            'Não foram esgotados benefícios, ST, adicionais, monofasia ou outras alíquotas.',
            'Nenhuma proposta foi publicada ou incorporada à consulta pública.',
        ],
    )
    destino.mkdir(parents=True, exist_ok=True)
    _csv(destino / 'todos_ncms.csv', linhas, ('ncm', 'situacao', 'aliquota_confirmada'))
    _csv(destino / 'propostas_12.csv', propostas, ('ncm', 'familia_id', 'status'))
    _csv(destino / 'pendentes_outros_tratamentos.csv',
         [l for l in linhas if l['situacao'] == 'SEM_CORRESPONDENCIA_NESTE_ESCOPO'], ('ncm', 'situacao'))
    (destino / 'propostas_12.json').write_text(json.dumps(propostas, ensure_ascii=False, indent=2), encoding='utf-8')
    (destino / 'resumo.json').write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding='utf-8')
    texto = [
        '# Cobertura NCM para revisão fiscal', '',
        f'Data de referência: {referencia:%d/%m/%Y}.', '',
        '**Nenhum enquadramento novo confirmado ou publicado.**', '',
        f'- NCMs examinados: {len(linhas)}.',
        f'- NCMs com correspondência candidata aos 12%: {len(ids_propostos)}.',
        f'- Novos NCMs candidatos, sem cadastro atual de alíquota: {len(novas)}.',
        f'- Propostas de vínculo NCM/família: {len(propostas)} (podem se sobrepor).',
        f"- NCMs sem correspondência neste escopo: {resumo['ncms_sem_correspondencia_no_escopo']}.", '',
        '## Como revisar', '',
        '1. Abrir todos_ncms.csv para conferir o inventário completo. Importar NCM como texto no Excel.',
        '2. Revisar propostas_12.csv por família, produto real, condição e trecho legal.',
        '3. Resolver ambiguidades e confrontar benefícios, isenções, ST e regimes próprios antes de aprovar carga.',
        '4. Tratar pendentes_outros_tratamentos.csv nas próximas regras; não preencher essas linhas com 19% confirmado.', '',
        '## Famílias e quantidade de vínculos', '', '| Família | NCMs candidatos |', '|---|---:|',
        *[f"| {f['produto']} ({f['id']}) | {por_familia[f['id']]} |" for f in familias], '',
        '## Limitações', '', *['- ' + limite for limite in resumo['limites']], '',
        '## Evidências', '', 'Metadados, hashes SHA-256 e comparação com Classif em resumo.json.',
        f'CTE/GO: {FONTE_CTE}', f'NCM/Classif: {URL_CLASSIF}', '',
    ]
    (destino / 'LEIA_ME.md').write_text('\n'.join(texto), encoding='utf-8')
    return resumo


def _normalizar_texto(texto: str) -> str:
    return re.sub(r'\s+', ' ', texto).strip()


def conferir_evidencias(snapshot: dict, familias: list[dict], oficial: Path, cte: Path,
                       referencia: date, catalogo: Path) -> dict:
    documento = json.loads(oficial.read_text(encoding='utf-8'))
    if documento.get('Data_Ultima_Atualizacao_NCM') != f'Vigente em {referencia:%d/%m/%Y}':
        raise ValueError('Data da tabela oficial difere da referência; não confirmar vigência histórica.')
    ncms_oficiais, _ = extrair_ncms(documento)
    banco = {r['ncm']: r for r in snapshot['ncm'] if r.get('ativo') == 'SIM'}
    faltantes = sorted(set(ncms_oficiais) - set(banco))
    extras = sorted(set(banco) - set(ncms_oficiais))
    if faltantes or extras:
        raise ValueError(f'Catálogo diverge do Classif: {len(faltantes)} ausentes, {len(extras)} extras. '
                         'Conferir cadastro antes de gerar propostas.')
    html = BeautifulSoup(cte.read_bytes(), 'html.parser')
    texto_cte = _normalizar_texto(html.get_text(' ', strip=True))
    for familia in familias:
        if _normalizar_texto(familia['trecho_legal']) not in texto_cte:
            raise ValueError(f"Trecho legal da família {familia['id']} não localizado no documento.")
    return dict(
        fonte_cte=FONTE_CTE, fonte_ncm=URL_CLASSIF,
        data_fonte_ncm=documento['Data_Ultima_Atualizacao_NCM'], ato_ncm=documento.get('Ato'),
        sha256_cte=hashlib.sha256(cte.read_bytes()).hexdigest(),
        sha256_ncm_oficial=hashlib.sha256(oficial.read_bytes()).hexdigest(),
        sha256_catalogo_propostas=hashlib.sha256(catalogo.read_bytes()).hexdigest(),
        ncms_oficiais=len(ncms_oficiais), ncms_neon=len(banco),
        ncms_ausentes_no_neon=faltantes, ncms_extras_no_neon=extras,
        descricoes_divergentes=sum(banco[n]['descricao_oficial'] != r['descricao_oficial']
                                   for n, r in ncms_oficiais.items()),
        observacao='Download oficial e snapshot da rodada; presença do trecho não substitui revisão de vigência e alterações.',
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    fonte = parser.add_mutually_exclusive_group(required=True)
    fonte.add_argument('--snapshot', type=Path)
    fonte.add_argument('--postgres', action='store_true')
    parser.add_argument('--ncm-oficial', type=Path, required=True)
    parser.add_argument('--cte-html', type=Path, required=True)
    parser.add_argument('--referencia', type=date.fromisoformat, required=True)
    parser.add_argument('--saida', type=Path, required=True)
    parser.add_argument('--catalogo', type=Path, default=CATALOGO)
    args = parser.parse_args()
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
        origem = 'SNAPSHOT_DE_AUDITORIA'
    else:
        repositorio = criar_repositorio(data_source='postgres')
        with repositorio.engine.connect() as conexao:
            conexao.exec_driver_sql('SET TRANSACTION READ ONLY')
            nomes = {'NCM': 'ncm', 'Aliquotas': 'aliquotas', 'Beneficios': 'beneficios',
                     'Legislacao': 'legislacao'}
            snapshot = {nomes[nome]: [dict(r) for r in conexao.execute(select(tabela)).mappings()]
                        for nome, tabela in TABELAS.items()}
        origem = 'POSTGRESQL_SOMENTE_LEITURA'
    familias = carregar_familias(args.catalogo)
    evidencias = conferir_evidencias(snapshot, familias, args.ncm_oficial, args.cte_html,
                                     args.referencia, args.catalogo)
    evidencias['origem_cadastro'] = origem
    if args.snapshot:
        evidencias['sha256_snapshot'] = hashlib.sha256(args.snapshot.read_bytes()).hexdigest()
    resumo = gerar_relatorios(snapshot, familias, args.referencia, args.saida, evidencias=evidencias)
    print(json.dumps({k: v for k, v in resumo.items() if k not in {'evidencias', 'limites', 'propostas_por_familia'}},
                     ensure_ascii=False, indent=2))
    print('SIMULAÇÃO: nenhuma escrita no PostgreSQL, nenhuma alíquota confirmada.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

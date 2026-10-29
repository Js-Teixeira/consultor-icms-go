"""Auditoria reproduzível do lote; não abre conexão nem altera dados fiscais."""
import json
import pathlib
import re
import sys
from collections import Counter

PASTA = pathlib.Path(__file__).resolve().parent
REPO = PASTA.parents[1]
sys.path.insert(0,str(REPO))
from scripts.finalizar_cadastro import validar_lote

def ler(p):
    return json.loads(p.read_text())

def validar(ncms_ativos):
    lote = ler(PASTA/'lote_consolidado.json')
    rastros = ler(PASTA/'rastreabilidade.json')
    inventario = ler(PASTA/'inventario_final.json')['linhas']
    assert len(inventario)==len({r['id_pendencia'] for r in inventario})==91
    validar_lote(lote,ncms_ativos)
    assert lote['aliquotas']==lote['revisoes']['aliquotas']==[]
    novos = lote['beneficios']
    revisoes = lote['revisoes']['beneficios']
    registros = {r['id_beneficio']:r for r in novos+[r['depois'] for r in revisoes]}
    assert len(novos)==46 and len(revisoes)==14 and len(registros)==60
    assert len(rastros)==60 and sum(len(r['rotas']) for r in rastros)==107
    assert len({(r['template_id'],r['ncm']) for r in rastros})==60
    for rev in revisoes:
        a,b = rev['antes'],rev['depois']
        assert {k:v for k,v in a.items() if k not in {'condicoes','observacao'}}=={k:v for k,v in b.items() if k not in {'condicoes','observacao'}}
        assert b['condicoes'].startswith('Cumprir UMA das alternativas de enquadramento abaixo, sem cumulação automática:\nALTERNATIVA A — enquadramentos anteriores preservados: ')
        assert b['condicoes'].split('ALTERNATIVA A — enquadramentos anteriores preservados: ',1)[1].split('\nALTERNATIVA B',1)[0]==a['condicoes']
        assert b['observacao'].startswith(a['observacao']+'\n')
    positivos=set()
    for r in rastros:
        b=registros[r['id_beneficio']]
        assert b['chave_ncm']==r['ncm']
        condicoes=b['condicoes'].split('\nALTERNATIVA B — rotas adicionais de 29/10/2026: ',1)[-1]
        for rota in r['rotas']:
            positivos.add(rota['id_pendencia'])
            assert rota['id_pendencia'] in condicoes
            especificas=rota['condicoes_especificas']
            especificas=especificas if isinstance(especificas,list) else [especificas]
            assert all(c in condicoes for c in especificas)
            for campo in ['atributos_classificatorios_obrigatorios','limites_da_rota','limite_classificatorio','alerta_especifico','residuo_excluido']:
                if rota.get(campo):assert str(rota[campo]) in condicoes
            assert rota['evidencias_federais']
    assert len(positivos)==80
    assert {r['id_pendencia'] for r in inventario if r['beneficios']}==positivos
    parciais_fonte=set()
    for grupo in ['quimicos','medicamentos','equipamentos']:
        conclusoes=ler(PASTA/grupo/'conclusoes.json')
        if isinstance(conclusoes,dict):conclusoes=conclusoes['conclusoes']
        for c in conclusoes:
            if c['id_pendencia'] not in positivos:continue
            if (c.get('residuo_nao_resolvido') or c.get('subescopos_ainda_pendentes')
                    or (grupo=='equipamentos' and re.search(r'\bparcial\b',str(c.get('limites','')),re.I))):
                parciais_fonte.add(c['id_pendencia'])
    parciais_inventario={r['id_pendencia'] for r in inventario if r['situacao']=='CANDIDATO_CONDICIONAL_PARCIAL'}
    assert parciais_inventario==parciais_fonte,('Parcialidade documental omitida',sorted(parciais_fonte-parciais_inventario))
    assert all(r['residuo'] for r in inventario if r['id_pendencia'] in parciais_fonte)
    assert all(not r['homologacao_fiscal'] for r in inventario)
    assert all(not r['beneficios'] for r in inventario if r['situacao']=='PENDENTE_SEM_VINCULO_OPERACIONAL')
    assert Counter(r['tipo_beneficio'] for r in novos)=={'ISENCAO':18,'CARGA_EFETIVA':28}
    partes=[]
    for p in sorted(PASTA.glob('carga_*.sql')):
        sql=p.read_text()
        literal=sql.split("DECLARE carga jsonb := '",1)[1].split("'::jsonb;\nBEGIN",1)[0]
        parte=json.loads(literal.replace("''","'"))
        validar_lote(parte,ncms_ativos)
        partes.append(parte)
    assert len(partes)==2
    assert [r for p in partes for r in p['beneficios']]==novos
    assert [r for p in partes for r in p['revisoes']['beneficios']]==revisoes
    assert [r for p in partes for r in p['legislacao']]==lote['legislacao']
    assert all(p['aliquotas']==p['revisoes']['aliquotas']==[] for p in partes)
    return {'resultado':'PASSOU','ids_investigados':91,'ids_com_vinculo_condicional':80,
            'sem_vinculo':11,'ids_parciais':len(parciais_fonte),'novos':46,'complementos':14,'rotas':107,
            'campos_anteriores_preservados':True,'condicoes_anteriores_preservadas':True,
            'rotas_e_restricoes_presentes':True,'sql_igual_ao_lote':True,
            'aliquotas_nominais_inalteradas':True,'homologacao_fiscal':False}

if __name__=='__main__':
    # Catálogo obtido por fonte operacional/exportação pública; código de oito dígitos não basta para enquadramento.
    catalogo=ler(pathlib.Path(sys.argv[1]))
    if isinstance(catalogo,dict):catalogo=catalogo['ncm']
    ativos={r['ncm'] for r in catalogo if r['ativo']=='SIM'}
    resultado=validar(ativos)
    (PASTA/'validacao_lote.json').write_text(json.dumps(resultado,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(resultado,ensure_ascii=False))

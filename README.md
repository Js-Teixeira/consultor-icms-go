# Consultor de ICMS Goiás por NCM

Projeto em Python + Streamlit para consultar o tratamento tributário de mercadorias em Goiás a partir do **NCM**.

## Escopo do projeto

O núcleo da aplicação é:

```text
NCM informado
  ↓
regra exata ou por prefixo
  ↓
alíquota interna de ICMS em Goiás
  ↓
benefícios/tratamentos vinculados ao NCM
  ↓
base legal + vigência + condições
```

A descrição do produto é opcional e serve apenas para desempatar/refinar regras já encontradas pelo NCM. O sistema **não infere NCM pela descrição**.

Entram na consulta somente tratamentos ligados de forma objetiva a NCM, posição ou subposição, como alíquota, isenção, redução de base de cálculo, diferimento, substituição tributária ou crédito outorgado quando houver vínculo explícito com a classificação fiscal.

Benefícios genéricos de programa, empresa, contribuinte ou estabelecimento sem NCM explícito **não entram na consulta pública nem na consolidação NCM**. Menções procedimentais a NCM são preservadas para auditoria, mas não são publicadas como benefício ou alíquota.

## Estrutura

```text
app.py                         # consulta pública por NCM
admin.py                       # painel interno de leitura/revisão
base/base_tributaria_go.xlsx   # base Excel de apoio/importação
src/                           # motor público de consulta
src/dados/                     # Excel/PostgreSQL
scripts/                       # criação/importação do banco
updater/                       # coleta e extração legislativa
  executor.py                  # Fase 1 - coleta
  foco_ncm.py                  # prioridade de atos com NCM
  extrator.py                  # Fase 2 - extração conservadora
  consolidador.py              # Fase 3 - consolidação NCM para revisão
tests/                         # testes automatizados
```

Arquivos de `dry-run`, caches, virtualenv e credenciais não fazem parte do projeto versionado.

## Ambiente

Python 3.12 ou superior.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Para desenvolvimento/testes:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Banco de dados

A produção usa PostgreSQL. A URL deve usar o driver psycopg:

```text
postgresql+psycopg://...
```

Configure localmente, sem salvar a senha no repositório:

```bash
export DATA_SOURCE=postgres
export DATABASE_URL='postgresql+psycopg://...'
```

Crie/verifique o schema e as migrações aditivas:

```bash
python -m scripts.criar_banco
```

O script não cria o servidor PostgreSQL. Ele somente cria/verifica tabelas e aplica migrações aditivas previstas pelo projeto.

## Base fiscal principal

O motor público lê somente estas quatro tabelas:

- `ncm`
- `aliquotas`
- `beneficios`
- `legislacao`

A planilha de apoio deve conter as abas `NCM`, `Aliquotas`, `Beneficios` e `Legislacao`. Abas extras são ignoradas pelo carregador.

Para importar a planilha para PostgreSQL:

```bash
python -m scripts.importar_excel_postgres
```

Por padrão registros existentes não são sobrescritos. Atualização explícita:

```bash
python -m scripts.importar_excel_postgres --confirmar-atualizacao
```

### Amostra de validação fiscal

`base/validacao_ncm.csv` contém 37 registros validados: 14 NCMs, 14 alíquotas, 4 benefícios e 5 fundamentos legais, sem rascunhos. Use uma linha por registro e os nomes de coluna do schema atual. A linha `LEGISLACAO` reúne norma, dispositivos, `texto_relevante` (trecho curto) e `url_fonte`; as regras apontam para ela por `id_legislacao`. Não duplique a legislação nas linhas das regras.

O CSV exige NCM como texto de oito dígitos, `EXATO` ou `PREFIXO`, `SIM` ou `NAO` para `ativo` e `exige_descricao`, datas `AAAA-MM-DD`, URL HTTPS oficial `.gov.br` e percentuais em **pontos percentuais** (`12` significa `12,00%`). Para benefícios alternativos, informe `grupo_beneficio` e `aplicacao=ALTERNATIVO`; `condicoes` mantém as exigências legais que a consulta não consegue comprovar. Não inclua o NCM fictício `99999999` na carga: ele é um caso negativo de teste.

Valide o plano antes de gravar:

```bash
python -m scripts.importar_validacao_ncm --dry-run
```

Importe após a revisão fiscal:

```bash
python -m scripts.importar_validacao_ncm
```

Registros iguais são ignorados. Se um ID existente tiver valores diferentes, a carga aborta; após revisar a alteração, execute `python -m scripts.importar_validacao_ncm --dry-run --confirmar-atualizacao` e depois `python -m scripts.importar_validacao_ncm --confirmar-atualizacao`. A carga valida o arquivo inteiro, verifica vínculos com NCM e fundamento, e grava apenas nas quatro tabelas fiscais dentro de uma transação. Nenhuma tabela de monitoramento é alterada.

## Executar a consulta

```bash
python -m streamlit run app.py
```

A aplicação prioriza regra `EXATO` de 8 dígitos e depois `PREFIXO` cadastrado de 6, 4 ou 2 dígitos. A vigência é verificada internamente. Quando a descrição for necessária para diferenciar tratamentos, a confiança é reduzida até haver correspondência suficiente. Um NCM presente no cadastro oficial sem regra fiscal de Goiás recebe `SEM_TRATAMENTO_CADASTRADO`, preservando sua descrição oficial sem inferir alíquota ou benefício.

## Auditoria de integridade

```bash
python -m scripts.auditar_integridade
```

O auditor apenas lê e relata; não corrige dados nem altera o banco. Para auditar o CSV local sem acessar PostgreSQL, use `python -m scripts.auditar_integridade --arquivo-csv base/validacao_ncm.csv`. A opção `--json` mostra as ocorrências estruturadas. `ERRO` retorna código diferente de zero e poderá bloquear um CI futuro; `ALERTA` pede revisão humana; `INFO` indica lacuna ou pendência. As tabelas `aliquotas` e `beneficios` possuem vínculos opcionais `regra_consolidada_id` e `evidencia_ncm_id`; regras antigas curadas manualmente podem permanecer com esses campos vazios.

## Regressões fiscais

Casos fiscais já validados em `base/validacao_ncm.csv` têm expectativas fixas em `tests/fixtures/regressoes_fiscais_go.json`. Os testes conferem o CSV local; `python -m scripts.verificar_prontidao_producao` também compara alíquotas, benefícios e fundamentos congelados com as quatro tabelas fiscais do PostgreSQL, somente por leitura. A descrição oficial sincronizada do banco pode diferir da descrição resumida do CSV. Novas mudanças fiscais exigem revisão humana do caso e do snapshot.

## Sincronização da NCM oficial

A rotina usa o JSON público vigente do [Classif/Siscomex](https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json). Ela compara os códigos finais com o PostgreSQL e altera somente a tabela `ncm`; regras fiscais de Goiás são tratadas separadamente.

```bash
python -m scripts.sincronizar_ncm_oficial --dry-run
python -m scripts.sincronizar_ncm_oficial
```

O primeiro comando baixa e compara a fonte oficial sem gravar. O segundo aplica inserções e atualizações de descrições em uma transação.

## Fase 1 - coleta legislativa com foco NCM

A coleta usa as fontes oficiais já implementadas da Secretaria da Economia de Goiás e, quando disponível, o texto oficial da Casa Civil.

O modo recomendado para este projeto é:

```bash
python -m updater.executor \
  --ano 2026 \
  --foco-ncm \
  --max-paginas 10 \
  --limite 20 \
  --dry-run
```

`--foco-ncm` lê o conteúdo antes de ordenar os atos. Ele apenas prioriza documentos com indícios de NCM e ICMS; não presume vigência nem enquadramento fiscal.

`--max-paginas` permite percorrer páginas anteriores da fonte oficial. Isso é importante porque uma regra vigente pode ter sido criada antes do ano corrente.

O monitoramento fica isolado das tabelas fiscais principais.

## Fase 2 - extração por NCM

A Fase 2 trabalha sobre os atos já coletados:

```bash
python -m updater.extrator \
  --ano 2026 \
  --relevancia ALTA \
  --limite 50 \
  --dry-run
```

Regras de segurança:

- detecta NCM no texto completo antes dos filtros fiscais;
- normaliza NCM sem inferir código por descrição;
- preserva NCM encontrado em dispositivo procedimental;
- só marca `elegivel_consulta_ncm = SIM` quando há regra material e NCM/posição/subposição explícitos;
- mercadoria descrita sem NCM pode ficar pendente de vínculo, mas não entra na consulta;
- benefício genérico sem NCM fica fora da consolidação;
- `dry-run` não grava extrações.

A versão atual do extrator é registrada em cada processamento para preservar rastreabilidade.

## Fase 3 - consolidação para revisão

A consolidação é intermediária e **não publica** na base fiscal principal.

```bash
python -m updater.consolidador \
  --ano 2026 \
  --limite 50 \
  --dry-run
```

A Fase 3 recebe somente regras que atendam simultaneamente aos filtros NCM do extrator. Regras genéricas de programa/contribuinte/estabelecimento sem NCM não são carregadas para consolidação.

Não execute a consolidação normal antes de revisar o resultado da Fase 2.

## Painel interno

O `admin.py` é uma ferramenta de desenvolvimento/revisão, não uma autenticação de produção.

```bash
export ADMIN_TOOLS=true
python -m streamlit run admin.py
```

Ele mostra regras NCM pendentes e consolidações intermediárias em modo leitura. Antes de expor qualquer painel administrativo na internet é necessário adicionar autenticação real.

## O que não faz parte do núcleo

O projeto não tem como objetivo manter um cadastro geral de:

- PRODUZIR, PROGOIÁS, FOMENTAR ou outros programas sem vínculo NCM;
- benefícios por empresa ou grupo econômico sem NCM;
- regras exclusivas de contribuinte/estabelecimento sem NCM;
- procedimentos fiscais sem tratamento material consultável;
- pauta de preços como se fosse alíquota ou benefício.

Esses conteúdos podem aparecer durante a leitura legislativa apenas para que o extrator consiga **descartá-los com segurança**.

## Segurança e versionamento

Nunca versionar:

- `.venv/`
- `.env`
- `.streamlit/secrets.toml`
- senhas/URLs completas de banco
- saídas locais `extrator_*.txt` e `coleta_*.txt`

Para produção pública, use usuário PostgreSQL de menor privilégio para a aplicação. Não use credencial de proprietário do banco no Streamlit público.

## Rastreabilidade e prontidão

`aliquotas` e `beneficios` aceitam `regra_consolidada_id` e `evidencia_ncm_id` opcionais, preenchidos apenas após revisão humana. Os vínculos são validados por ID na importação e auditados sem inferir origem por NCM igual. Regras manuais antigas podem manter os dois campos vazios. A migração aditiva está em `scripts/migrar_rastreabilidade_fiscal.py`; execute-a somente em operação administrativa autorizada.

Confira os bloqueadores de produção com `python -m scripts.verificar_prontidao_producao`. Consulte [DEPLOY_STREAMLIT.md](DEPLOY_STREAMLIT.md) para as configurações de publicação.

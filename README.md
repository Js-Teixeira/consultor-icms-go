# Consultor de alíquota interna de ICMS — Goiás

Aplicação Streamlit para consultar a alíquota interna de ICMS cadastrada para um NCM e seu fundamento legal específico. O usuário informa somente o NCM e clica em **Consultar**.

O resultado usa a data corrente de Goiás como referência e informa que a operação é interna. A interface apresenta as regras correspondentes, com descrição, percentual cadastrado, fundamento, vigências, condições e pendências de validação. Quando há múltiplas regras, nenhuma é escolhida automaticamente. A referência geral e as hipóteses condicionais mantêm seus avisos de aplicabilidade. O cadastro não substitui revisão fiscal da legislação e das condições de aplicação.

## Estrutura

- `app.py`: interface pública, limitada a NCM, alíquota interna e fundamento legal.
- `src/busca.py`, `src/modelos.py`, `src/normalizacao.py`, `src/formatacao.py`: decisão e apresentação da consulta.
- `src/dados/`: PostgreSQL como única fonte operacional. `src/carregamento.py` e `src/dados/excel_repository.py` preservam a leitura histórica de Excel, fora da seleção operacional.
- `admin.py`: painel interno de revisão legislativa, separado da aplicação pública.
- `updater/` e `scripts/`: atualização, importação, auditoria, rastreabilidade e verificações administrativas. Esses componentes preservam o esquema e o histórico fiscal, inclusive registros de benefícios que não aparecem na consulta pública.
- `tests/`: testes automatizados da consulta e da manutenção.
- `base/`: arquivos locais controlados; podem diferir da base de produção.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Configure `DATABASE_URL` com segurança no ambiente ou nos secrets locais do Streamlit, no formato `postgresql+psycopg://...`. Não versione credenciais. A aplicação pública deve usar usuário somente leitura. `DATA_SOURCE`, quando informado, deve ser `postgres`; se a conexão estiver ausente, inválida ou indisponível, a operação falha sem recorrer a Excel.

A auditoria padrão também exige PostgreSQL. Os modos explícitos `--arquivo-excel` e `--arquivo-csv` permanecem para diagnóstico histórico e não alimentam automaticamente a consulta pública.

Para executar os testes:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Em produção, configure a fonte PostgreSQL com credencial somente de leitura. Consulte `DEPLOY_STREAMLIT.md`. Não publique `admin.py` como aplicação pública.

Antes de remover definitivamente o suporte a arquivos, será necessário revisar o importador histórico `scripts/importar_excel_postgres.py`, o leitor `src/carregamento.py`, `ExcelRepository`, os modos locais de auditoria e seus testes. A prontidão de produção ainda usa CSV de validação e cache JSON oficial; esses artefatos também precisam ser separados da verificação operacional ou ter suas evidências persistidas no PostgreSQL. Os testes atuais usam dados sintéticos e não exigem PostgreSQL real.

## Propostas fiscais (etapa 2)

`regras_consolidadas.status_validacao` contém `PENDENTE`, `VALIDADA` ou `DESCARTADA`, mas **não comprova autorização para publicação**: o esquema não registra identidade/autorização do revisor, justificativa e data de uma decisão fiscal auditável. `planejar_revisao` devolve somente `APROVACAO_SIMULADA` ou `REJEICAO_SIMULADA` em memória, sem mudar esse estado. Uma rejeição já persistida permanece bloqueada; nenhum comando desta etapa grava decisões ou cadastros.

`python -m scripts.simular_publicacao_fiscal` faz apenas `SELECT` e separa candidatos **para revisão humana**, duplicados no lote, cadastros inalterados e propostas bloqueadas. As linhas projetadas são explicitamente inativas (`ativo=NAO`, sem `data_verificacao`) e não autorizam publicação. A leitura cruza ato, versão, extração e proposta, preserva e verifica a cadeia histórica e compara fundamento, NCM, condições, percentual e vigência com as evidências. Datas em linguagem natural, condições oriundas de complementos sem cadeia comprovada e sobreposições que exigem interpretação fiscal ficam bloqueadas.

O cadastro atual de atos guarda coleta, versão e hash, mas não uma **confirmação explícita de autenticidade da fonte**. Por isso, a leitura do PostgreSQL marca `fonte_verificada=False` e bloqueia preventivamente a prontidão, mesmo quando a URL parece oficial. Para habilitar um fluxo real, será preciso definir e autorizar persistência auditável da verificação da fonte e da decisão fiscal, vincular revisores autorizados e criar um publicador separado com nova revisão de segurança. Nenhuma migração ou publicação é executada nesta etapa. Os testes usam propostas identificadas como sintéticas; suas projeções servem apenas para verificar a lógica.

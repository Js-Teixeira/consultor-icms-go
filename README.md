# Consultor de alíquota interna de ICMS — Goiás

Aplicação Streamlit para consultar o tratamento de ICMS cadastrado para um NCM e seu fundamento legal. A pesquisa é realizada pelo NCM; os resultados apresentam tratamentos encontrados, percentuais cadastrados, vigências, condições e pendências.

A correspondência de um NCM não comprova, isoladamente, a aplicabilidade de um benefício fiscal. Quando há mais de uma regra, a aplicação não escolhe automaticamente uma delas. O resultado não substitui a análise da legislação vigente e das condições concretas da operação.

## Componentes

- `app.py`: interface pública de consulta.
- `src/`: consulta, apresentação, normalização e validações.
- `src/dados/`: acesso operacional ao PostgreSQL. Leitores de Excel permanecem apenas para operações históricas.
- `admin.py`: painel administrativo separado da aplicação pública.
- `updater/`: coleta, extração e consolidação de candidatos jurídicos.
- `scripts/`: importação, auditoria e ferramentas administrativas.
- `tests/`: testes automatizados.
- `base/`: dados e arquivos auxiliares históricos, distintos da base operacional.

## Dados e segurança fiscal

A consulta pública utiliza PostgreSQL como fonte operacional e não recorre automaticamente ao Excel se a conexão estiver indisponível. A credencial da aplicação pública é destinada a operações somente de leitura.

As propostas resultantes da extração legislativa não são publicadas automaticamente. A existência de registros de extração, consolidação ou simulação não comprova aprovação fiscal, autenticidade jurídica da fonte ou autorização para alterar cadastros.

O histórico e as evidências preservam a distinção entre regras encontradas, hipóteses condicionadas e tratamentos fiscalmente confirmados.

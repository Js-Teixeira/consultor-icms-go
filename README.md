# Consultor ICMS GO

O Consultor ICMS GO ajuda a pesquisar tratamentos de ICMS cadastrados para mercadorias em Goiás. Basta informar o NCM para consultar as regras encontradas, seus percentuais, fundamentos legais, condições e datas de vigência.

A consulta é voltada a **operações internas em Goiás** e usa a data de referência apresentada na tela.

## O que a consulta apresenta

- O NCM pesquisado e os tratamentos correspondentes cadastrados.
- Alíquotas e benefícios, com os percentuais identificados separadamente.
- Referências legais, condições de aplicação e eventuais pendências.
- Uma indicação quando não há cadastro ou quando mais de uma regra exige análise.

Quando não há uma regra específica, o sistema pode mostrar a alíquota geral **como referência**, não como enquadramento confirmado. Algumas hipóteses especiais também podem aparecer com ressalvas.

## De onde vêm os dados

A aplicação pública consulta **PostgreSQL (Neon)**. O Excel não é utilizado como fonte operacional, nem como alternativa em caso de falha de conexão.

Os registros de legislação e os tratamentos fiscais são consultados, mas **não são alterados pela tela pública**. O monitoramento de atos e a extração de possíveis regras ficam separados da consulta e não publicam benefícios automaticamente.

## Organização do projeto

- `app.py` — tela pública de consulta.
- `src/` — pesquisa por NCM, validações, formatação e acesso ao PostgreSQL.
- `admin.py` — painel administrativo separado da aplicação pública.
- `updater/` — coleta de atos e preparação de regras para análise.
- `scripts/` — auditoria, sincronização e outras rotinas administrativas.
- `tests/` — verificações automatizadas feitas com dados isolados.
- `base/validacao_ncm.csv` — referência auxiliar para testes e cargas administrativas; não alimenta a consulta pública.

## Atenção ao uso fiscal

**Encontrar um NCM não significa que a alíquota ou o benefício se aplica automaticamente à mercadoria.** Operação, descrição do produto, vigência, fundamento e demais requisitos legais precisam ser conferidos.

Quando houver regras conflitantes, dados incompletos ou condições não verificadas, o consultor informa a pendência em vez de escolher uma regra por conta própria. A consulta é um apoio à análise fiscal, não substitui a legislação nem a revisão do responsável.

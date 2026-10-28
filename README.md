# Consultor ICMS GO

O Consultor ICMS GO ajuda a pesquisar tratamentos de ICMS cadastrados para mercadorias em Goiás. Basta informar o NCM para ver as opções de tratamento cadastradas e abrir a ficha de cada uma, com fundamentos, condições e pendências.

A consulta é voltada a **operações internas em Goiás** e usa a data de referência apresentada na tela.

## O que a consulta apresenta

- As opções encontradas para o NCM e uma ficha separada para cada tratamento.
- Alíquotas e benefícios, com os percentuais identificados separadamente.
- Referências legais, condições de aplicação e eventuais pendências.
- Uma indicação quando não há cadastro ou quando mais de uma regra exige análise.

A ficha não confirma a alíquota aplicável apenas pela correspondência do NCM. O cadastro não comprova, por si só, desdobramentos Ex da TIPI, adicionais ou a carga tributária total.

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

O estado atual, seus testes e limites estão em [Conclusão das pendências de 28/10/2026](docs/conclusao_pendencias_20261028.md). A [conferência da carga inicial](docs/finalizacao_20261028.md) preserva a etapa anterior.

O acompanhamento semanal de fontes e o comando de leitura de vencimentos estão em [Rotina de atualização](docs/rotina_atualizacao.md). A análise dos oito vínculos sem percentual demonstrado e as versões anteriores/posteriores estão em [Revisão dos oito códigos](revisao/suspensao_oito_20261028.json).

Para examinar o catálogo completo e preparar candidatos aos 12% sem alterar o banco, veja [Revisão integral do catálogo](docs/cobertura_12.md). O lote gerado depende de revisão fiscal e não alimenta automaticamente a consulta pública.

**Encontrar um NCM não significa que a alíquota ou o benefício se aplica automaticamente à mercadoria.** Operação, descrição do produto, vigência, fundamento e demais requisitos legais precisam ser conferidos.

Quando houver regras conflitantes, dados incompletos ou condições não verificadas, o consultor informa a pendência em vez de escolher uma regra por conta própria. A consulta é um apoio à análise fiscal, não substitui a legislação nem a revisão do responsável.

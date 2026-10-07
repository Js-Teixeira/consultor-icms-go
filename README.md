# Consultor de ICMS Goiás por NCM

Aplicação desenvolvida em Python e Streamlit para consultar o tratamento tributário de mercadorias no estado de Goiás a partir do NCM.

O projeto surgiu da necessidade de tornar consultas fiscais mais rápidas e organizadas, reunindo em um único lugar a descrição oficial do NCM, alíquota de ICMS, benefícios aplicáveis, condições e fundamentação legal.

## O que a aplicação consulta

O usuário informa o NCM da mercadoria e, opcionalmente, uma descrição do produto.

A consulta pode apresentar:

- descrição oficial do NCM;
- alíquota interna de ICMS em Goiás;
- benefícios ou tratamentos vinculados ao NCM;
- redução de base de cálculo ou carga tributária, quando aplicável;
- condições para utilização do tratamento;
- fundamento legal;
- fonte oficial.

A descrição do produto é utilizada apenas para ajudar na diferenciação entre regras já relacionadas ao NCM. O sistema não tenta descobrir ou sugerir um NCM apenas pela descrição.

## Escopo

O foco do projeto é a consulta tributária por classificação fiscal.

São consideradas regras ligadas objetivamente a NCM, posição ou subposição.

Benefícios relacionados exclusivamente a empresa, contribuinte, estabelecimento ou programas de incentivo sem vínculo direto com NCM não são apresentados como resultado da consulta pública.

## Tecnologias

- Python
- Streamlit
- PostgreSQL
- SQLAlchemy
- Psycopg
- Pandas
- RapidFuzz
- Pytest

## Estrutura do projeto

~~~
app.py          Aplicação pública de consulta
admin.py        Ferramenta interna de revisão
src/            Motor da consulta
src/dados/      Camada de acesso aos dados
updater/        Coleta e análise legislativa
scripts/        Rotinas administrativas
tests/          Testes automatizados
base/           Base fiscal controlada
~~~

## Banco de dados

Em produção, a aplicação utiliza PostgreSQL.

O ambiente público utiliza uma credencial somente de leitura e acessa apenas as informações necessárias para a consulta.

Credenciais e senhas não são armazenadas no repositório.

## Executando localmente

Crie o ambiente virtual:

~~~
python -m venv .venv
source .venv/bin/activate
~~~

Instale as dependências:

~~~
python -m pip install -r requirements.txt
~~~

Execute a aplicação:

~~~
python -m streamlit run app.py
~~~

## Desenvolvimento e testes

As dependências utilizadas apenas durante desenvolvimento e testes ficam separadas:

~~~
python -m pip install -r requirements-dev.txt
python -m pytest -q
~~~

O projeto possui testes para o mecanismo de consulta, regras de correspondência por NCM, benefícios fiscais, integração com banco de dados, sincronização da NCM oficial e rotinas de atualização legislativa.

## NCM oficial

Os códigos e descrições de NCM são sincronizados a partir da fonte pública do Classif/Siscomex.

A existência de um NCM na tabela oficial não significa que já exista uma regra tributária de Goiás cadastrada para ele.

Quando o NCM é válido, mas ainda não existe tratamento fiscal cadastrado na base, a aplicação informa essa situação sem criar ou presumir alíquota, benefício ou fundamento legal.

## Atualização das regras fiscais

As rotinas de atualização legislativa são separadas da consulta pública.

O fluxo foi estruturado para localizar dispositivos relacionados a NCM, extrair informações relevantes e manter os resultados em revisão antes de qualquer publicação na base fiscal utilizada pelos usuários.

Nenhuma regra fiscal é publicada automaticamente apenas porque um NCM foi encontrado em um documento.

## Segurança

Arquivos e informações locais não fazem parte do repositório público, incluindo:

- ambiente virtual;
- arquivos `.env`;
- `secrets.toml`;
- senhas e URLs completas do banco;
- caches e arquivos temporários.

A aplicação publicada utiliza um usuário PostgreSQL limitado a operações de leitura.

## Deploy

As instruções específicas de publicação estão disponíveis em:

[DEPLOY_STREAMLIT.md](DEPLOY_STREAMLIT.md)

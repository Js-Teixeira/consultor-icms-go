# Consultor de alíquota interna de ICMS — Goiás

Aplicação Streamlit para consultar a alíquota interna de ICMS cadastrada para um NCM e seu fundamento legal específico. O usuário informa somente o NCM e clica em **Consultar**.

O resultado usa a data corrente de Goiás como referência e informa que a operação é interna. Uma alíquota só é apresentada quando existe uma regra única e vigente para o NCM, sem exigência de descrição, com percentual válido e vínculo a fundamento cadastrado, ativo, vigente, com início de vigência, data de verificação, dispositivo e fonte. Em qualquer caso sem decisão segura, a aplicação informa **Verificação fiscal necessária** ou que a alíquota não foi encontrada. O cadastro não substitui revisão fiscal da legislação e das condições de aplicação.

## Estrutura

- `app.py`: interface pública, limitada a NCM, alíquota interna e fundamento legal.
- `src/busca.py`, `src/modelos.py`, `src/normalizacao.py`, `src/formatacao.py`: decisão e apresentação da consulta.
- `src/dados/`, `src/carregamento.py`: leitura de Excel ou PostgreSQL.
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

Para executar os testes:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Em produção, configure a fonte PostgreSQL com credencial somente de leitura. Consulte `DEPLOY_STREAMLIT.md`. Não publique `admin.py` como aplicação pública.

# AGENTS.md — Consultor de ICMS de Goiás

## Objetivo e escopo
Este repositório é um sistema de consulta de NCM, alíquotas de ICMS e possíveis benefícios fiscais, com foco no estado de Goiás. O software auxilia a análise fiscal: não substitui revisão humana, legislação vigente nem dados oficiais verificados.

## Arquitetura do projeto
- `app.py`: interface principal Streamlit.
- `admin.py`: rotinas administrativas; verifique o controle de acesso antes de expor funcionalidades.
- `src/`: busca, normalização, regras de apresentação, confiança, rastreabilidade e validações.
- `src/dados/`: acesso operacional somente ao PostgreSQL.
- `updater/`: rotinas de atualização e extração de informações legislativas.
- `scripts/`: importação, sincronização, verificações e utilitários.
- `tests/`: testes automatizados.
- `base/`: fixtures e caches auxiliares; o PostgreSQL é a fonte operacional.

Antes de mudar código, confirme a estrutura real do repositório e leia os módulos relevantes. Não assuma que o ambiente local e a produção compartilham a mesma base de dados.

## Regras fiscais obrigatórias
1. Nunca invente NCM, percentual, CST, CFOP, benefício, código de benefício, dispositivo legal, vigência, link ou interpretação normativa.
2. Diferencie claramente informação **confirmada**, **potencialmente aplicável**, **pendente de verificação** e **não encontrada**. Não descreva como confirmado o que exige validação fiscal.
3. Para qualquer fundamento legal, exija ou solicite fonte verificável, dispositivo (artigo/inciso/anexo quando pertinente), jurisdição, vigência e condições de aplicação. Não deduza automaticamente a legislação vigente apenas de cache local ou descrição de NCM.
4. Não trate coincidência de NCM como prova suficiente de direito a benefício. Verifique operação, finalidade, destinatário, origem/destino, regime, vigência e demais condições legais quando relevantes.
5. Se uma alíquota estiver vinculada a fundamento inexistente, inativo, inconsistente ou não verificado, não a apresente como alíquota fiscal confirmada. Exiba aviso junto ao resultado.
6. Preserve o histórico das regras e a rastreabilidade entre resultado, origem dos dados e versão/data de referência. Não apague registros históricos para simular validade atual.
7. Valide entradas, inclusive NCM de 8 dígitos numéricos, e deixe explícitos o tipo de operação e a data de referência da consulta.
8. Propostas de alteração de regras tributárias exigem justificativa, testes e aprovação do responsável fiscal antes de implantação.

## Dados, privacidade e segurança
- Não altere, limpe, substitua ou importe dados em `base/`, CSV, caches fiscais ou PostgreSQL sem autorização explícita.
- Não execute migração, comando SQL com escrita, sincronização remota ou atualização legislativa automática sem autorização.
- Nunca exponha `.env`, `secrets.toml`, `DATABASE_URL`, tokens, credenciais ou dados pessoais/fiscais reais em prompts, logs, commits ou serviços externos.
- Para testes e exemplos, prefira dados sintéticos e anonimizados.
- Antes de usar integrações externas (GitHub, CodeRabbit, APIs, serviços MCP), informe quais informações poderão ser transmitidas e peça autorização quando houver dados sensíveis.
- Não publique o painel administrativo sem verificar autenticação, autorização e configuração de implantação.

## Padrões de desenvolvimento
- Preserve a arquitetura e as APIs existentes sempre que possível; prefira alterações pequenas, reversíveis e focadas.
- Separe apresentação, consulta, acesso a dados e atualização de legislação.
- Para correções de comportamento, acrescente primeiro um teste que reproduza o problema, quando viável.
- Cubra cenários positivos, inválidos, ambíguos, sem dados, datas fora da vigência e fundamento legal ausente.
- Não instale dependências, renomeie módulos, mude esquema de dados ou faça refatoração ampla sem explicar e obter autorização.
- Quando apropriado e autorizado, execute os testes com `.venv/bin/python -m pytest`. Informe exatamente quais testes rodaram e seus resultados; nunca alegue execução não realizada.
- Não faça `git commit`, `git push`, `git reset --hard`, mudanças de branch ou publicação sem solicitação explícita.

## Pontos para revalidar antes de novas funcionalidades
Um diagnóstico local anterior identificou riscos que devem ser conferidos novamente, não assumidos como conclusões permanentes:
- Um percentual podia ser priorizado e exibido mesmo com fundamento legal problemático.
- A normalização aceitava caracteres não numéricos misturados ao NCM.
- A interface podia usar a data atual do servidor e um rótulo de alíquota interna em contexto interestadual.
- A indicação de aplicabilidade de benefício pode exigir critérios legais adicionais.

## Fluxo de trabalho com Codex
1. Antes de implementar, descreva em poucas linhas: objetivo, arquivos envolvidos, riscos fiscais e estratégia de teste.
2. Se faltar informação legislativa, operacional ou de dados, pergunte em vez de presumir.
3. Quando o usuário pedir apenas análise, faça somente leitura e não altere arquivos.
4. Quando houver autorização para editar, limite as alterações ao escopo aprovado e mostre o diff relevante.
5. Ao concluir, informe arquivos alterados, testes executados/não executados, limitações e itens que dependem de validação fiscal humana.

As instruções explícitas da tarefa atual e regras de segurança superiores prevalecem sobre este arquivo.

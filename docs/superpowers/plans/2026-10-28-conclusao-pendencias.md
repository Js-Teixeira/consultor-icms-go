# Conclusão das pendências do Consultor NCM

> Execução contínua autorizada pelo usuário. Aplicar superpowers:executing-plans; pesquisa fiscal em duas frentes independentes, uma revisão final do conjunto.

**Objetivo:** resolver o que for demonstrável nos oito vínculos de 12%, revisar correspondências e regras por operação, versionar scripts/testes e ativar acompanhamento legislativo.

**Arquitetura:** preservar aplicação e esquema PostgreSQL; alteração fiscal apenas condicional, com fonte e ensaio Neon. Automação semanal de leitura e alertas, sem publicar alíquotas sozinha. Versionamento em branch e PR, sem presumir autorização para merge.

**Tecnologias:** Python3.12, pytest, PostgreSQL/Neon, conector GitHub, automação ChatGPT.

## Restrições e decisões

- A autorização atual cobre os quatro itens apresentados e permite commit/push/versionamento. Não inclui inventar enquadramento ou remover histórico.
- A fonte operacional continua PostgreSQL. Não introduzir dependências nem esquema novo.
- Manter os alertas quando a lei depender da identidade do produto; concluir análise não equivale a homologar produto genérico.
- Não ampliar benefício universal para10.516NCMs quando depender de operação/TARE.
- Checkout já isolado em consultor-cobertura. Preservar o checkout original preparado pelo ambiente.

## Tarefas e verificações

- [x] Pesquisa dos oito códigos: conclusão por código, fonte primária e proposta explícita; revisar como hipótese, suspender apresentação numérica não demonstrada ou manter alerta fundamentado, preservando evidência anterior. Nenhuma19%definitiva por exclusão.
- [x] Revisão de235pendências e298operações: separar correlação oficial de expansão literal de prefixos e de requisitos não indexáveis porNCM. Incorporar apenas propostas sustentadas, com teste em branch isolada, reexecução e leitura posterior.
- [x] Utilitário de vigências somente leitura: `scripts/verificar_vigencias.py`, `tests/test_verificar_vigencias.py`. Casos: limite45dias inclusivo, data corrente inclusiva, expirado, inativo, fimvazio, data inválida, início posterior ao fim; nunca omitir inconsistência silenciosamente.
- [x] Ativar acompanhamento semanal: segunda-feira de manhã, America/Sao_Paulo, leitura de fontes e Neon consultor_readonly; alertar mudanças e prazos45dias; sem escrita fiscal autônoma. Criado e habilitado28Out.
- [x] Suíte completa598/598; checagens independentes executadas; dois achados corrigidos por regressão e ensaio; diffs e credenciais conferidos.
- [x] Parecer conclusivo independente retomado: pronto no escopo técnico; sem homologação fiscal. OP293 conferido pelo executor na mesma linha do quadro.
- [ ] Publicar branch/commit e PR com documentação de cobertura real, rotina e pendências remanescentes. Conferir arquivos e checks remotos; sem merge automático.

## Foco da revisão

Oito pendentes ainda exibindo12semprova; regra de benefício confundida com nominal; prefixos5/7com exceções ou códigos antigos convertidos por semelhança; fontehistórica/futura usada comoatual; datas inválidas escondidas em alerta; conectorGitHubbaseatual e nenhum segredo/arquivo local incidental incluído.

## Ledger

Pre-flight: módulo de carga já existente é consumido pelos novos dados; preservar a interface e os guards. Utilitário de vigência consome BaseTributaria, sem interferir na consulta pública. Automação e documentação não escrevem alíquotas.

Decisão: manter execução sem nova rodada de perguntas, conforme pedidos reiterados do usuário para seguir e terminar. Escolher revisão semanal, com alerta45dias, como rotina inicial ajustável.

Conclusão do ensaio e aplicação28/10: dois lotes aplicados em transação na produção; leitura consultor_readonly idêntica ao ensaio.634registros de alíquota (626de12em622NCM e8NULL),1797benefícios/1526NCM,63fontes. Catálogo10516 inalterado.
Final: fixed colisão de $carga12$ — test_sql_rejeita_delimitador_do_bloco_no_texto_livre RED→GREEN; suite598/598.
Final: fixed condição metodológica obsoleta nos radiofármacos — verificação de condição RED→GREEN;2novos e1legado saneados, sem alterar identidade legal ou percentuais; suite598/598.
Final: limite de revisão independente — o revisor confirmou testes597anterioresàcorreção,24paresMDIC,298caputs,235pendências e20impedimentostemporais; limite de uso impediu emitir parecer final. O autor concluiu a validação após as correções, sem atribuir aprovação final ao revisor.
Ruling: oitoNULLemvezdemodal19 — vínculo genérico12nãodemonstrado; mantémhistórico e impedereconhecerpercentualindevido — custo:8consultas mostramRevisar até comprovação do produto/operação.
Ruling: manter17art30nocatálogotécnico — appnão recebe fatosDIFAL/importação/TARE — custo:essas hipótesesnãoaparecemcomo benefício geralporNCM.
Ruling: PRsemmergeautomático — versionamentoautorizado nãohomologaoperaçãofiscal e parecerconclusivopendente — custo:códigoficaembranchtécnicadisponívelpararevisão.

Atualização: usuário autorizou continuar os itens remanescentes, incluindo revisão/integração. O revisor retomou e concluiu pronto no escopo técnico. O executor confirmou A12XIV nas células14312/14313/14314 e corrigiu índice da data; integração com head esperado e CI verde.

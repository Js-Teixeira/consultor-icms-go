# Revisão integral do catálogo para os 12%

**Atualização em 28/10/2026:** a revisão posterior dos 10.516 códigos e a carga condicional foram concluídas. A produção contém 634 regras para 630 NCMs com vínculo de 12%: 622 hipóteses compatíveis/condicionais e oito vínculos históricos explicitamente pendentes. Foram completados os quatro benefícios antigos e acrescentados 1.773, totalizando 1.777 registros condicionais para 1.507 NCMs. Café solúvel está entre os 23 novos vínculos carregados. As contagens das seções abaixo documentam etapas anteriores. Veja [conferência final](finalizacao_20261028.md).

O planejador percorre todos os NCMs ativos. Os 14 cadastros anteriores não limitam a geração de candidatos. Não integra automaticamente suas propostas à consulta pública.

## Executar

```bash
python -m scripts.planejar_cobertura_12 --postgres \
  --ncm-oficial /caminho/nomenclatura.json --cte-html /caminho/CTE.htm \
  --referencia 2026-10-26 --saida /caminho/resultado
```

`--snapshot /caminho/snapshot.json` permite reproduzir a auditoria a partir das quatro tabelas capturadas. É um modo explícito de auditoria, não alternativa ao PostgreSQL na aplicação pública. Não há opção de publicação ou aplicação automática.

## Resultado da seleção inicial de 26/10/2026

- 10.516 NCMs examinados; códigos e descrições iguais ao Classif baixado na rodada.
- 34 famílias de produtos, cobrindo as alíneas a, b, c, d, f e h do art. 27, II, do CTE/GO.
- 607 NCMs com correspondência candidata; 593 sem cadastro atual de alíquota e 14 já cadastrados.
- 612 vínculos NCM/família, pois açúcar/rapadura e sabão/sabonete podem se sobrepor.
- 9.909 NCMs sem correspondência neste escopo. Isso não confirma alíquota modal, ausência de benefício nem exclusão definitiva dos 12%.
- Esta seleção inicial não alterou o Neon. A carga condicional posteriormente aprovada e a revisão complementar estão descritas abaixo.

## Situação após a carga e revisão complementar

A carga aprovada de 597 regras para 593 novos NCMs foi aplicada no Neon. Somada aos 14 códigos anteriores, a produção tem 611 regras de 12% para 607 NCMs distintos. Os novos registros são possibilidades condicionais, com exigência de conferir a descrição; não são enquadramentos fiscais confirmados. Os quatro benefícios anteriores foram preservados.

A revisão complementar encontrou café solúvel, NCM 21011110, fora da seleção inicial. O catálogo de revisão passou à versão 2, com 35 famílias, incluindo proposta específica para café solúvel puro. Essa proposta adicional ainda não foi carregada em produção. O planejador atualizado tem 608 códigos candidatos, incluindo os 607 já cadastrados; isso também não demonstra cobertura normativa integral.

[Revisão complementar e pendências](revisao_12_20261026.md) descreve o fundamento, os limites e o vínculo adicional preparado para aprovação. A existência de pendências impede afirmar que todos os produtos sujeitos a 12% estão cadastrados. A referência geral de 19% para os demais códigos não comprova a inexistência de exceção.

## Como interpretar

`propostas_12.csv` é um lote de revisão, não arquivo de importação operacional. Cada linha contém condição, dispositivo e trecho legal. Os vínculos NCM/família são propostas técnicas por nomenclatura: o texto do art. 27, II, descreve mercadorias e não fornece essa lista completa de códigos.

`todos_ncms.csv` contém o inventário completo, uma linha por NCM ativo. A coluna de alíquota confirmada permanece vazia; a referência geral é apresentada em coluna distinta e não significa conclusão fiscal. `pendentes_outros_tratamentos.csv` mantém o restante visível para análise das demais normas.

Não foram esgotados benefícios, isenções, substituição tributária, adicionais, monofasia, outras alíquotas ou possíveis classificações de produtos fora das famílias propostas. A presença literal do trecho no HTML não comprova, por algoritmo, que aquela redação permanece vigente.

O Portal DIFAL/SVRS foi conferido como apoio. As linhas de 12% de Goiás também usam descrições sem NCM e incluem registros históricos. A listagem consultada ainda mostra gás doméstico revogado e cerveja de mandioca, cuja alínea está declarada inconstitucional no CTE. Esses registros não foram promovidos ao catálogo. O CTE é a fonte legal desta rodada.

Antes de carregar no cadastro operacional, revisar as propostas, os casos de classificação ambígua e demais tratamentos da operação. A aprovação deve indicar que os registros são candidatos condicionais ou quais vínculos foram fiscalmente confirmados; não se deve aprovar 607 alíquotas definitivas por NCM.

## Validação

Suíte executada na cópia isolada após a revisão complementar: 566 testes aprovados, sendo 59 do planejador e 18 da preparação da carga. O ambiente de execução usa proxy SOCKS; a suíte foi executada com as variáveis de proxy removidas apenas para o processo de testes, sem alterar dependências do projeto ou os testes existentes.

Revisão independente identificou omissão de feijão-guando e inclusão de tâmaras/figos exclusivamente secos em hortifrutícolas. As duas situações foram verificadas contra o Classif, corrigidas e cobertas por testes.

Base Git examinada: `33d6d26be65280128b32f267d095ca60260fb047`. Sem commit, push, merge ou publicação de código. A carga condicional aprovada anterior está em produção; a inclusão complementar permanece proposta.

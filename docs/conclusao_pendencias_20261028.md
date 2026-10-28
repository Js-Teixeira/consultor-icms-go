# Conclusão das pendências de cadastro

Esta rodada foi autorizada para revisar os oito vínculos duvidosos, revisar benefícios por operação/regime, versionar os scripts e configurar acompanhamento legislativo. Ela mantém o objetivo de orientar a consulta, sem homologar uma operação fiscal a partir de um código isolado.

## Oito vínculos de 12%

A pesquisa concluiu que não foi demonstrado o vínculo genérico de 12% para os oito códigos. A correção aplicada substituiu o percentual corrente por NULL, conservando identificação, fundamento, vigências, observação anterior e cópia antes/depois. Não define outra alíquota nem declara revogação legal. A interface existente mostra Revisar quando não há percentual específico válido no registro.

| NCM | Ponto que impede confirmação genérica |
|---|---|
|04079000|Ovo com casca conservado/cozido exige definição do alcance legal para a apresentação efetiva.|
|04081100|Gema seca não foi especificamente equiparada ao produto legal ovo por fonte goiana encontrada.|
|04081900|Outras apresentações de gema não comprovam a identidade do produto previsto na regra.|
|04089100|Ovo sem casca seco exige exame de apresentação, ingredientes e alcance.|
|04089900|A informação de 12% sobre ovo líquido no relatório do Parecer 105/2023 é relato do consulente; a conclusão trata de transferência de crédito.|
|11031300|A classificação diferencia grumos/sêmolas de farinha/fubá; não estender a regra por semelhança.|
|19022000|A exclusão expressa das massas recheadas no benefício de 7% não decide sua alíquota nominal.|
|25010011|Sal marinho a granel, sem agregados, não comprova iodação ou compatibilidade do subitem; admissão do iodado na posição 25.01 não resolve o subitem.|

O relatório e as fontes primárias estão em `revisao/suspensao_oito_20261028.json`. Os scripts de preparação são reversíveis por evidência e bloqueiam mudança concorrente; não apagam registros nem alteram datas para simular revogação. A aprovação de um produto concreto continua exigindo seus dados reais.

## Atualização e versionamento

O monitoramento semanal está habilitado, com leitura de fontes oficiais e alerta de vencimentos em 45 dias. O comando `python -m scripts.verificar_vigencias --dias 45` oferece conferência independente do agendamento. Datas inconsistentes aparecem como alerta.

Os scripts, testes, propostas históricas e documentação desta sequência compõem a branch `feature/conclusao-ncm-20261028`. Propostas antigas permanecem evidência histórica: não devem ser executadas como se fossem a próxima carga de produção. Os guards rejeitam conteúdo ou cadastros divergentes.

## Revisão de benefícios por contexto

A correspondência técnica por NCM continua sujeita à descrição legal, apresentação, destinatário, regime e operação. Foram aplicados 20 novos candidatos, 5 complementos de correspondência e uma correção de nota metodológica antiga. Diferença de alíquota, importação e benefício com TARE não foram inseridos como se valessem em toda saída interna.

As 235 pendências de correspondência foram examinadas e tiveram encaminhamento registrado. Restam 175 sem solução conclusiva nesta rodada:130 exigem cadeia oficial completa, 32 têm múltiplos sucessores oficiais e 13 dependem de contexto ou vigência. Não foram convertidas em vínculos por semelhança. As 298 operações têm inventário próprio de fatos e requisitos;278 são atuais condicionais, 17 têm prazo exaurido e 3 têm outros impedimentos. As 17 hipóteses do art. 30 dependentes de DIFAL/importação/TARE permanecem em catálogo técnico fora da consulta interna por NCM.

## Validação e estado atual

Produção lida com `consultor_readonly` após os dois lotes em uma transação:10.516 NCMs;634 regras nominais, sendo 626 registros de 12% em 622 NCMs e 8 sem percentual;1.797 benefícios em 1.526 NCMs;63 fundamentos. Os hashes integrais das tabelas coincidem com o ensaio. O catálogo NCM permaneceu inalterado.

O motor foi exercitado nos 10.516 NCMs:622 retornam hipóteses nominais de 12%, 9.886 recebem referência geral de 19% e 8 exigem revisão sem percentual comprovado. Os 1.797 benefícios mantêm as condições e não são aplicados automaticamente. Seis amostras da interface abriram sem erro, incluindo os dois casos sem percentual, solar, biogás, informática e peças de aviões.757 benefícios com prazo 31/12/2026 aparecem no alerta de 45 dias a partir de 16/11/2026.

A suíte final passou com 598 testes e 38 avisos de depreciação. A revisão independente executou checagens e encontrou dois problemas concretos: colisão de delimitador em um gerador antigo e condição metodológica obsoleta nos radiofármacos. Ambos foram corrigidos, com regressões observadas falhando antes e passando depois, além de ensaio e reexecução idêntica no Neon. O parecer conclusivo do revisor foi interrompido por limite de uso; não é apresentado como revisão final aprovada. A publicação fica em PR para revisão, sem merge automático.

As fontes, o inventário e as versões antes/depois estão em `revisao/`. Nenhum desses registros homologa a tributação de produto ou operação concreta. O resumo verificável está em `revisao/resultado_conclusao_20261028.json`.

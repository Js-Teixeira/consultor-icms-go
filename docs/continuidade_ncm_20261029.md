# Continuidade das correlações de NCM

Implantação verificada em 29/10/2026. Pesquisa documental com referência em 28/10/2026; catálogo de códigos ativos reconferido na RFB em 29/10/2026.

Foram incorporados 424 novos candidatos condicionais e complementados nove benefícios existentes. As condições anteriores foram preservadas como alternativas, inclusive Flúor-18 e Etanercepte. Duas propostas desta rodada receberam rotas adicionais dentro do mesmo registro, sem duplicação. Não houve alteração de alíquotas nominais, aplicação automática de benefício, esquema ou código do aplicativo.

| Medida | Antes | Produção verificada |
| --- | ---: | ---: |
| NCMs ativos | 10.516 | 10.516 |
| Benefícios condicionais | 1.797 | 2.221 |
| NCMs com algum benefício cadastrado | 1.526 | 1.863 |
| Fontes legislativas | 63 | 69 |
| Regras nominais | 634 | 634 |

Os 10.516 códigos ativos coincidem exatamente com o catálogo RFB vigente em 29/10/2026, sem ausentes ou excedentes. A consulta mantém 622 NCMs com hipótese nominal de 12%, 9.886 com referência geral de 19% e oito com percentual específico a revisar. Esses estados não homologam produto, operação ou direito fiscal.

## Conteúdo incorporado

- Medicamentos, fármacos, soros e radiofármacos vinculados à identidade e apresentação da linha legal, com separação de fármaco e medicamento.
- Máquinas e equipamentos com função, tecnologia, capacidade, precisão, material e finalidade preservados. Destinos residuais ou códigos reutilizados não foram estendidos à cesta inteira.
- 322 reduções de base de cálculo de 10,52% para produtos farmacêuticos e 26 de 11,15% para perfumaria/higiene, limitadas às operações e condições do art. 8º, XXV. Os percentuais não são alíquotas nominais nem cargas efetivas.
- Vacinas restritas à finalidade SARS-CoV-2, antirretrovirais e operação específica da Hemobrás, conforme descrição e condições legais.
- Fraldas descartáveis produzidas em Goiás, saída interna e carga resultante de 9%, somente como candidato restrito em 96190000. As cinco propostas iniciais em códigos de vestuário foram descartadas: a NESH atual exclui fraldas de 61.11/62.09 e as inclui em 96.19. A fonte anexada foi corrigida após revisão independente.

## Resultado da revisão dos 175 itens

| Situação documental | Itens |
| --- | ---: |
| Candidato condicional sustentado, inclusive vínculo já existente | 73 |
| Prazo encerrado | 2 |
| Catálogo técnico fora de saída interna ordinária | 5 |
| Parcialmente resolvido, com correlações residuais | 2 |
| Identidade ou cadeia documental ainda insuficiente | 91 |
| Parametrização numérica ainda ambígua | 1 |
| Descrição legal conflitante | 1 |
| Total | 175 |

São 80 encaminhamentos documentais concluídos, dois parciais e 93 pendências específicas. Não significa que todos os benefícios possíveis estejam vinculados ou que os candidatos estejam fiscalmente homologados.

As 91 linhas têm decisões individuais e documentos necessários registrados. Permanecem, por exemplo, químicos sem subitem nominal inequívoco, biológicos sem distinção de mistura/dose e equipamentos sem especificações suficientes. O item OUTROS_026 mantém conflito entre unidade óptica e leitora de código de barras. O art. 8º, LIV permanece sem percentuais operacionais de 60%/35% por divergência de parametrização. Hemobrás e art. 8º, XXV conservam parcelas históricas ainda sem vínculo demonstrado.

As tabelas primárias Mercosur de 2002↔2007 e 2007↔2012 foram documentadas. A pesquisa ALADI obteve NALADISA e tabelas regionais, mas não demonstrou uma cadeia NCM 2012→2017 com ano e orientação comprovados. Nenhuma equivalência NALADISA/NCM foi presumida.

## Verificação e implantação

O lote foi validado no esquema existente e aplicado em cópia isolada da produção. A reexecução integral dos 11 sublotes não modificou o estado; uma inserção conflitante foi rejeitada com rollback. As duas propostas complementadas dentro da rodada foram comparadas com suas condições no ensaio anterior, que permaneceram integralmente preservadas.

Após a aplicação em produção, a leitura com `consultor_readonly` confirmou as mesmas contagens e hashes integrais de benefícios, legislação e alíquotas do ensaio. O hash das alíquotas permaneceu idêntico ao anterior.

Verificações executadas: 598 testes aprovados, 38 avisos de depreciação; consulta de todos os 10.516 NCMs; validação dos 2.221 benefícios; amostras de interface para reduções, fraldas, Hemobrás, radiofármacos e o estado Revisar; alerta de 45 dias para os 1.141 benefícios com término em 31/12/2026. As revisões independentes examinaram os dados e fontes; a execução de testes e banco foi feita separadamente pelo implementador.

Evidências e lotes ficam em [revisao/continuidade_20261028](../revisao/continuidade_20261028). Os JSONs dos sublotes podem ser validados e convertidos em SQL por `scripts.finalizar_cadastro.validar_lote` e `gerar_sql`, fornecendo o conjunto de NCMs ativos. Cada revisão exige estado anterior ou novo exato; divergências interrompem a carga. Os lotes não contêm credenciais.

Os oito percentuais nominais ainda a revisar e os benefícios condicionais exigem a classificação e os fatos da mercadoria/operação concreta. O sistema permanece uma referência para análise fiscal.

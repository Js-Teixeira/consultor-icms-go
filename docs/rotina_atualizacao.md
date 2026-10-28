# Rotina de revisão legislativa e vencimentos

Desde 28/10/2026 há uma tarefa habilitada no ChatGPT para revisar semanalmente, às segundas-feiras de manhã, no fuso America/Sao_Paulo. A primeira revisão está programada para 02/11/2026. Alertas consideram mudanças oficiais e prazos nos 45 dias seguintes; sem novidade relevante, a tarefa não envia notificação.

A rotina consulta fontes oficiais e o Neon pelo papel consultor_readonly. Não altera percentuais ou regras automaticamente. Falha de conexão ou de fonte deve ser informada, nunca tratada como confirmação de atualização.

## Fontes e comparação

- CTE/GO, especialmente art. 27: https://appasp.economia.go.gov.br/legislacao/arquivos/Cte/CTE.htm
- RCTE/GO, Anexo IX: https://appasp.economia.go.gov.br/legislacao/arquivos/Rcte/Anexos/ANEXO_09_Beneficio_Fiscal.htm
- IN 1.518/2022 e alterações, tabela cBenef, nos arquivos oficiais da Economia/GO.
- Classif/Siscomex e tabelas oficiais de correlação NCM. Mudança de código exige correspondência oficial e identidade do bem, preservando descrições, Ex e condições.
- Pareceres oficiais pertinentes ao alcance do produto, operação e regime.

Verificar a redação vigente e sua data de efeitos. Texto revogado no HTML compilado, relato do consulente ou mera presença de um termo não homologam percentual. Separar o histórico, a regra atual e atos futuros.

## Conferência manual de prazos

Com a conexão PostgreSQL já configurada para leitura:

```bash
python -m scripts.verificar_vigencias --dias 45
```

É possível reproduzir uma data de referência:

```bash
python -m scripts.verificar_vigencias --dias 45 --referencia 2026-11-16
```

O comando usa transação de leitura e informa registros ativos vencidos, a vencer e datas inconsistentes. Fim de vigência no dia da consulta permanece inclusivo. Campo fim vazio não representa revogação ou validade eterna: significa prazo não cadastrado. O relatório não estende prazos nem altera o cadastro.

Em 28/10/2026 a base tem 746 benefícios com fim em 31/12/2026. A revisão deve procurar prorrogação ou nova disciplina antes dessa data; a consulta já retira os candidatos vencidos após o limite cadastrado.

## Procedimento ao detectar uma mudança

1. Preservar a evidência anterior e a fonte oficial atual, com dispositivo e efeitos.
2. Identificar NCM/produto, operação, destinatário, regime, TARE, cBenef e demais requisitos afetados.
3. Preparar alteração explícita, sem combinar benefícios ou transformar carga efetiva em nominal.
4. Testar em branch Neon, verificar conflito e reexecução, obter a validação fiscal pertinente.
5. Aplicar o lote autorizado e ler novamente com o papel de consulta. Documentar versão e cobertura real no GitHub.

O acompanhamento não substitui decisão fiscal sobre produtos ou operações concretos. Essa decisão exige os dados reais que o NCM, sozinho, não contém.

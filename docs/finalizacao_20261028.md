# Conferência da carga condicional de 28/10/2026

**Registro histórico da carga inicial.** O complemento posterior acrescentou 20 benefícios, revisou 5 correspondências e uma nota metodológica, e retirou o percentual de 8 vínculos não comprovados. O estado atual é 1.797 benefícios em 1.526 NCMs, 626 regras de 12% em 622 NCMs, 8 registros sem percentual e 598 testes passando. Veja [conclusão atual](conclusao_pendencias_20261028.md); as contagens abaixo são da etapa anterior.

Produção Neon conferida com papel de leitura após a aplicação: 10.516 NCMs, 634 regras nominais, 1.777 benefícios e 63 fontes. Os hashes integrais das três tabelas tributárias coincidem com os da branch validada; o catálogo NCM permaneceu inalterado.

São 630 NCMs com vínculo de 12%: 622 hipóteses compatíveis ou condicionais na auditoria e oito vínculos históricos com interpretação pendente. Os oito são 04079000, 04081100, 04081900, 04089100, 04089900, 11031300, 19022000 e 25010011. As consultas não os priorizam automaticamente. O benefício de sal iodado/25010011 também declara explicitamente a pendência e a orientação de não aplicar os 7% antes de esclarecer a classificação.

Os benefícios abrangem 1.507 NCMs: 801 registros de carga efetiva, 850 de isenção, dois de redução de base e 124 de crédito outorgado. São candidatos sujeitos a descrição, operação, destinatário, vigência e condições legais. Não há combinação automática, nem confirmação de direito pelo NCM. Operações genéricas ou não indexáveis por mercadoria permanecem no inventário de pendências.

Os 9.886 códigos sem regra nominal específica recebem referência geral de 19%, sem homologação fiscal individual. Exercitar o motor nos 10.516 NCMs confirmou regra ou referência em todos eles; código inexistente ficou sem percentual.

Validação: 581 testes passaram, com 38 avisos de depreciação; 1.777 benefícios foram conferidos pelo motor e nove amostras da interface abriram sem exceções. Os 746 registros com término em 31/12/2026 deixam de aparecer em 01/01/2027. Houve revisão independente, correção de um alerta de classificação, rejeição de conflito real e repetição idempotente em branch isolada.

O limite de tamanho do servidor exigiu 18 sublotes. Cada sublote usa o mesmo gerador e preserva bloqueios e guards; existe atomicidade por sublote, sem atomicidade global entre sessões. Todos foram aplicados com sucesso e conferidos em produção. Não houve alteração de esquema, exclusão, commit, push ou publicação de código. As versões anteriores dos registros revisados estão preservadas na evidência da carga.

Módulo de carga: `scripts/finalizar_cadastro.py`; testes: `tests/test_finalizar_cadastro.py`. Fontes verificadas em 27/10/2026, aplicação em 28/10/2026. Qualquer homologação de produto ou operação concreta continua dependente do responsável fiscal.

# Finalização do cadastro condicional

O usuário pediu finalizar a consulta pública após a análise integral dos 10.516 NCMs e do diagnóstico de apenas quatro benefícios. Sua autorização cobre a execução contínua dos cadastros condicionais necessários; não representa confirmação fiscal de cada hipótese. Não publicar código nem alterar esquema.

Objetivo: incorporar os 23 novos vínculos condicionais de 12% já revisados; tornar explícita a pendência dos oito vínculos anteriores; cadastrar benefícios com fontes atuais, condições, datas e escopo, incluindo mercadorias fora da alíquota nominal de 12%. O site continua sujeito à validação do produto e da operação.

Arquivos: `scripts/finalizar_cadastro.py`, `tests/test_finalizar_cadastro.py`, catálogos e documentação em `revisao/`; evidências e carga em diretório separado. Aplicação e motor preservados se os testes de apresentação confirmarem o comportamento existente.

- [x] Conferir fontes atuais e preparar os catálogos de cesta básica, agro/alimentos e benefícios com NCM explícito. Separar regimes não indexáveis por produto e redações históricas.
- [x] Criar e testar validador/SQL atômico com campos permitidos, NCM ativo, fonte/data/escopo/condições, bloqueio de percentuais indevidos e de conflitos, e preservação dos registros anteriores em evidência.
- [x] Preparar a carga a partir dos catálogos e da cópia atual do banco. Os 23 vínculos novos nunca serão confirmados automaticamente. Os oito antigos terão alerta de alcance pendente, sem ocultar seu histórico.
- [x] Ensaiar em branch Neon derivada da produção, validar idempotência e rejeição de alteração concorrente. Verificar motor para todo o catálogo e interface em amostras representativas.
- [x] Revisão independente do lote e do SQL. Corrigir achados importantes; executar a suíte completa.
- [x] Aplicar a mesma carga validada em produção autorizada, ler com `consultor_readonly` e conferir as contagens/conteúdo. Não excluir tabelas ou registros.
- [x] Entregar resumo verificável com cobertura real, fontes, limitações remanescentes e arquivo de conferência.

Decisões: usar o PostgreSQL e o modelo de candidatos já existente. Carga efetiva prevista em norma fica em `carga_efetiva`, sem inventar redução de base fixa para nominais variáveis. Isenção não vira alíquota nominal zero. Benefícios dependentes de importação/DIFAL, TARE ou apuração que não caibam no escopo interno por mercadoria serão inventariados sem falso vínculo universal com os 10.516 NCMs. A falta de fonte/vigência impede publicação da hipótese correspondente, mas não suspende o restante sustentado.

Riscos/checagens: histórico versus redação atual; requisitos específicos por produto; somatório indevido de benefícios alternativos; códigos NBM antigos sem conversão; cBEN sem comprovação; referência 19% confundida com ausência de benefício; ativo sem NCM; carga repetida ou conflito concorrente. A evidência anterior e posterior acompanhará o lote.

Conclusão em 28/10/2026: 18/18 sublotes aplicados; leitura consultor_readonly idêntica ao ensaio por hashes das três tabelas. NCM10516, regras634, benefícios1777, fontes63. Suíte581/581; motor10516/10516; nove amostras de interface sem exceções. Regressão de sal iodado RED→GREEN, condição de interpretação pendente preservada. Evidência e relatório no pacote de conferência.

Ruling: preservar o checkout isolado e não publicar código nem mudar branch — AGENTS.md e autorização atual limitam a publicação — custo se incorreto: scripts ficam apenas no checkout até solicitação explícita.
Ruling: fracionar a carga rejeitada413 em18DOs com os mesmos guards — limite de transporte impede envio único — custo se interrompido: carga parcial até retomada;18/18 concluídos.
Final: fixed alerta de sal25010011 — verificar_pendencias.py RED→GREEN, suite581/581.
Final: revisão independente concluída com modelo disponível após Astraindisponível porlimite; nenhum minor adiado. Os pontos deixados para julgamento e suas decisões constam de revisao_independente.md no pacote.

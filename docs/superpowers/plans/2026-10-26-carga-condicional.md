# Carga aprovada de candidatos aos 12%

O usuário aprovou cadastrar os 593 novos NCMs como candidatos condicionais e reforçou que todo NCM válido deve apresentar uma alíquota. São 597 registros, porque quatro NCMs têm duas famílias candidatas. Preservar os 14 registros anteriores, os quatro benefícios e todo o catálogo NCM. Não mudar esquema, publicar código ou alterar os 14 enquadramentos existentes.

- [x] Gerar carga reproduzível com 597 candidatos exatos, seis fundamentos separados e condições visíveis na descrição e observação; exige_descricao=SIM. Cadastro ativo desde a data da carga, sem retroação.
- [x] Testar proteção de dados existentes, rejeição de conflitos, atomicidade, repetição idempotente e apresentação condicional pelo motor existente.
- [x] Ensaiar carga em branch Neon e conferir a leitura com consultor_readonly.
- [x] Aplicar a mesma carga na produção autorizada, sem UPDATE/DELETE, e comparar os registros anteriores.
- [x] Verificar resposta para todos os 10.516 NCMs na data da carga: regra específica/condicional ou referência geral. Reportar as lacunas fiscais sem atestar cobertura normativa completa.

Decisão: não cadastrar 9.909 linhas idênticas de 19%. A referência geral já está no motor, com vigência desde 01/04/2024. NCM inexistente ou inválido permanece sem percentual.

Produção conferida com consultor_readonly. 563 testes aprovados; motor verificado para 10.516 NCMs. Sem commit/push.

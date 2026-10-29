A revisão documental das 60 propostas e 107 rotas não identificou erro demonstrável que exija excluir algum dos candidatos restritos do lote. Há um achado **Important** de rastreabilidade a corrigir antes de declarar esta etapa concluída. A prontidão para carga continua condicionada a essa correção e às validações operacionais do agente principal; não constitui homologação fiscal.

Referência: 29/10/2026. Lote revisado: `revisao/vinculos_91_20261029/lote_consolidado.json`, SHA-256 `2c9042fd195f3ded48d5ad107ed8af4a54e774c51de937ac09c70886e9d09daf`. Foram lidos AGENTS.md, plano, pacote de revisão, conclusões dos 91 IDs, fontes, lote e rastreabilidade. Não usei o diff global nem alterei checkout, Git, Neon ou dados operacionais. Os únicos arquivos escritos pelo revisor são este relatório e sua versão JSON.

**Cobertura dos passes**

| Grupo | IDs examinados | Pares fundamento/NCM | Rotas | IDs com proposta |
|---|---:|---:|---:|---:|
| Químicos | 20 | 12 | 19 | 17 |
| Medicamentos | 43 | 16 | 51 | 40 |
| Equipamentos | 28 | 32 | 37 | 23 |
| Total | 91 | 60 | 107 | 80 |

São 46 novos registros, 14 complementos e 3 fontes novas. A versão JSON enumera todos os 60 pares e todas as 107 rotas revisadas.

**Critical: nenhum achado.**

**Important — I1: parcialidade da pesquisa de equipamentos se perde no inventário final.**

`equipamentos/conclusoes.json` declara expressamente rotas/candidatos parciais nos IDs OUTROS_017, OUTROS_019, OUTROS_034, OUTROS_035 e OUTROS_083, respectivamente nas linhas 6019, 6253, 6499, 6871 e 10658. Em `inventario_final.json`, as entradas iniciadas nas linhas 1673, 1723, 1769, 1792 e 2137 recebem `CANDIDATO_CONDICIONAL_DOCUMENTADO` e `residuo: null`. `resumo.json:18` lista apenas OUTROS_118, OUTROS_101 e OUTROS_102 como parciais. O consolidador só lê `residuo_nao_resolvido` e `subescopos_ainda_pendentes`, não o campo `limites` usado nessa pesquisa.

O caso mais claro é OUTROS_017: a proposta alcança somente cabeça de impressão por impacto, enquanto a conclusão admite outras tecnologias na descrição legal. O candidato continua restrito no lote, mas uma triagem futura baseada apenas no inventário pode perder o escopo restante. OUTROS_019 restringe tecnologia; OUTROS_034/035 restringem a interseção dos cabeçalhos antigos/atuais; OUTROS_083 restringe matéria. A parcialidade declarada nesses quatro também precisa ser conservada ou justificada explicitamente, distinguindo condição classificatória de resíduo documental real.

Correção necessária: registrar por ID o limite e o escopo não coberto, harmonizando conclusões, inventário, resumo e comunicação final. Não criar novos NCMs para corrigir a estatística. Ao menos OUTROS_017 exige resíduo explícito; não chamar os 80 IDs de integralmente resolvidos. Esta correção documental pode preservar integralmente o lote ensaiado. Se algum conteúdo operacional mudar, repetir a comparação/ensaio pertinente.

**Minor: nenhum achado adicional material.**

**Resultado das conferências independentes**

- Comparei os 14 objetos `antes` com a base reconstruída fornecida: igualdade integral. Em cada `depois`, apenas `condicoes` e `observacao` mudam. A alternativa A conserva literalmente todas as condições anteriores, e a observação anterior permanece como prefixo.
- Conferi os 60 registros e a presença literal das restrições específicas de todas as 107 rotas no lote, incluindo limites, apresentação, alertas e resíduos excluídos. As rotas novas ficam em alternativa B e os produtos dentro dela são separados por OR. Não há novas alíquotas nem revisões de alíquotas neste lote. Os parâmetros fiscais são os dos fundamentos correspondentes, sem percentual novo inventado.
- Químicos: conferi NVE/TIPI, identidades CAS e células legais, inclusive sildenafila base versus citrato; levotiroxina base versus sódio e hidratos; galantamina versus seu sal; dorzolamida sem extensão automática ao cloridrato; micofenolato sódico sem troca pelo mofetila. A NVE sustenta identidade/código nominal e não o direito ao benefício. A tensão entre NVE da sildenafila base e fundamentação da SC do citrato está declarada como exigência de revisão fiscal expressa.
- Medicamentos: as rotas 30021300/30021400 exigem, respectivamente, pureza ou mistura e ausência de doses/varejo. As rotas dosadas conservam princípio ativo, apresentação e dose. Interferonas peguiladas e não peguiladas, código nominal e residual, não foram fundidas. Codeína exclui os dois derivados não comprovados; imunoglobulina anti-hepatite não converte UI em mg; tenecteplase dosada não resolve o fármaco industrial; vacina meningite C tem alternativas de apresentação explicitamente excludentes. Levodopa associada é tratada pelo medicamento dosado da linha, sem carregar os componentes isolados bloqueados.
- Equipamentos: conferi atributos de tecnologia, largura/velocidade, conexão, matéria, função, comando numérico, precisão, tensão e potência. Os limites antigos de descrição permanecem mesmo quando o código atual é residual. A rota da torre eólica não foi estendida à lista solar. Códigos repetidos/reorganizados são cotejados pelo cabeçalho, não só pelos dígitos.
- As descrições de todas as 43 conclusões farmacêuticas e 28 de equipamentos foram localizadas no texto GO fornecido, excluídas as classes de redação revogada. Cotejei trechos primários e páginas TIPI/NVE/NESH e os recortes GO dos químicos. Trechos compostos de hierarquia ou de tabela foram tratados como composição documental, não citação contínua literal. As três fontes novas reproduzem os inícios 06/06/2003, 01/09/2010 e 01/12/2010 e o término 31/12/2026 nas notas GO dos índices 3158–3166 e 3205–3208 (base zero). O começo cadastral das novas propostas é 29/10/2026, sem homologação retroativa.
- Reabri as fontes primárias CONFAZ [101/97](https://www.confaz.fazenda.gov.br/legislacao/convenios/1997/CV101_97) e [204/19](https://www.confaz.fazenda.gov.br/legislacao/convenios/2019/CV204_19-1), que sustentam a alteração da torre eólica. O acesso direto ao Decreto 6.905 no Planalto foi bloqueado; sua [publicação original na Câmara](https://www2.camara.leg.br/legin/fed/decret/2009/decreto-6905-20-julho-2009-589728-publicacaooriginal-114631-pe.html) e os trechos oficiais disponíveis foram usados como evidência histórica, conjuntamente com a TIPI atual. O rastreador MDIC não foi usado como prova normativa exclusiva.

Os 11 IDs sem proposta continuam fora do lote: OUTROS_002, OUTROS_039, OUTROS_040, OUTROS_041, OUTROS_043, OUTROS_112, OUTROS_115, OUTROS_151, OUTROS_152, OUTROS_183 e OUTROS_196. Os resíduos explícitos de levotiroxina hidratada e dos derivados de codeína permanecem excluídos; I1 trata da incompletude adicional do inventário de equipamentos.

**Testes do principal, distintos desta revisão**

Li `validacao_integral.json` e o código de `verificar_lote.py`. O principal informou 598 testes aprovados, 38 avisos, 10.516 NCMs, 2.267 benefícios, 72 fontes, oito AppTests, idempotência das duas partes, rejeição de conflito sem alteração de hash e comparação de 60 benefícios/3 leis com zero divergências no stage. Esses resultados não foram executados ou atestados diretamente por este revisor. Minhas próprias verificações de arquivos são as comparações documentais e de preservação descritas acima. Não consultei produção nem dados sensíveis.

Também li `guarda_antes.sql` e `guarda_depois.sql`, acrescentados ao empacotamento após os passes documentais. As guardas fazem bloqueio das tabelas, aceitam o conjunto de hashes inicial ou final na entrada e exigem os hashes finais na saída. O principal informou execução das duas partes em uma única transação, replay bem-sucedido e rollback integral em teste provocado. Não executei essas guardas; o empacotamento não alterou o SHA-256 do lote acima e não muda o achado I1.

**Declined to judge**

Não julgo homologado o enquadramento de uma mercadoria ou operação concreta sem composição, forma química, apresentação, destinatário e demais documentos exigidos. Não resolvo por inferência a divergência classificatória da sildenafila base, não certifico equivalência histórica universal e não considero fonte federal ou de outra jurisdição concessão automática de ICMS/GO. Também não atesto execução própria da suíte, estado de produção, CI, autorização de implantação ou exaustividade de alterações normativas fora da evidência consultada.

**Prontidão condicional**

Apto para prosseguir com os mesmos candidatos restritos após corrigir I1 e conferir as validações do principal. Preservar os bloqueios, os resíduos e o caráter condicional; usar exatamente o lote/SQL ensaiados e verificar os hashes e o inventário de produção após eventual carga pelo fluxo autorizado. Nenhuma alteração fiscal foi feita por este revisor.

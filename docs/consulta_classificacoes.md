# Consulta por lista e ficha

A pesquisa mantém NCM e Consultar. O resultado apresenta botões para os tratamentos de ICMS realmente encontrados no cadastro, com descrição e identificador próprios. Se não há tratamento de alíquota vigente, apresenta apenas o registro existente no catálogo NCM. Selecionar abre uma ficha; Voltar mantém o NCM e a lista. Benefícios não são transformados em opções de classificação nem em Ex da TIPI.

Na ficha, benefícios encontrados por NCM são candidatos: o vínculo específico com o tratamento selecionado não está comprovado pelo esquema atual. Redução da base, carga efetiva e crédito outorgado permanecem separados. Os campos de referência geral de 19% e hipótese de 12% do motor anterior não são usados para montar opções nem preencher a ficha pública. Não há consulta à Objetiva ou uso de base proprietária.

## Comparação com o vídeo fornecido

O vídeo de aproximadamente 18 segundos permite observar a lista com duas descrições (por volta de 7 s), a ficha de uma opção (aproximadamente 10 s), a ficha de outra opção (aproximadamente 14 s) e o retorno à lista no trecho final. A gravação foi usada somente como referência de interação, sem importar descrições, percentuais ou fundamentos como dados operacionais.

Os ajustes funcionais são: quantidade real de opções encontradas, ficha identificada por NCM e descrição, resumo separado de ICMS/adicional/carga total e formulário de pesquisa restrito à lista. O botão Voltar restaura o NCM original, inclusive sua formatação. O tema escuro próprio foi mantido; cores, marca e composição proprietárias não foram reproduzidas. As duas opções do vídeo não são criadas artificialmente: a quantidade exibida depende dos registros efetivamente carregados.

## Verificação oficial pendente

Em 15/10/2026, as tentativas de acesso à página de legislação/TIPI e ao documento no domínio da Receita Federal (`www.gov.br/receitafederal`) falharam com `ProxyError`, inclusive na tentativa com permissão de rede ampliada. O conteúdo, a descrição e a vigência do Ex 01 para 04029900 não puderam ser confirmados nesta sessão. Nenhuma dessas descrições foi adicionada como dado operacional. A TIPI trata de classificação/IPI; sua confirmação futura não prova tratamento de ICMS.

## Menor adaptação necessária, sem execução

Atualmente `ncm.ncm` é chave primária e comporta apenas uma descrição por NCM. Não há código Ex, fonte/versionamento de classificação nem vínculo entre um Ex e as regras de ICMS. Inserir outra linha com o mesmo NCM não resolve isso; criar um benefício com a descrição do Ex também não.

A menor extensão relacional que preserva catálogo e histórico é:

- Uma tabela filha de classificações com `id_classificacao`, `ncm` (referência ao catálogo), `codigo_ex` (vazio para a classificação base), `descricao_oficial`, `vigencia_inicio`, `vigencia_fim`, `id_legislacao` e `ativo`. Usar identidade por versão e unicidade de NCM, código Ex e início de vigência. A tabela `legislacao` existente pode guardar o ato classificatório, dispositivo, URL oficial e data de verificação; isso não o torna fundamento de ICMS.
- Um vínculo opcional `id_classificacao` em `aliquotas` e `beneficios`. Um vínculo vazio permite apenas indicar correspondência por NCM, sem herdar a regra automaticamente para todos os Ex. Não usar descrições ou percentuais para deduzir esse vínculo.
- Após autorização específica: migração aditiva, carga oficial conferida e adaptação do `PostgresRepository` para carregar esses registros. Nenhuma tabela, coluna, migração ou carga foi criada nesta etapa.

## Confirmação fiscal e totais

O esquema atual não contém decisão fiscal auditável por tratamento/classificação. Mesmo quando as verificações cadastrais passam, a ficha não afirma alíquota fiscal confirmada para a mercadoria. O percentual nominal fica identificado como informação cadastrada, pendente de enquadramento. A data de verificação de uma norma não substitui a decisão fiscal específica.

`adicional_percentual`, isoladamente, não comprova incidência, fundamento próprio, base de cálculo ou sua combinação com a alíquota nominal. A ficha mostra essa pendência e não calcula carga total. Habilitar confirmação e cálculo exigirá comprovação explícita da incidência conjunta, sem confundir carga efetiva de benefício com soma de percentuais.

Todos os testes usam registros fictícios em memória. Não foi consultado ou alterado o Neon, nem foram alterados os módulos de aprovação/publicação fiscal. O tema escuro de `.streamlit/config.toml` foi preservado.

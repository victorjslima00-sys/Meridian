# Integridade dos dados de pesquisa

Requisito do projeto: nenhuma observação financeira pode ser inventada, mascarada ou completada silenciosamente. Dados incompletos podem ser preservados para investigação, sempre identificados e sem liberação para previsão.

- Preservar o arquivo recebido. Transformações produzem outro arquivo, com origem, parâmetros e hash do insumo.
- Distinguir observação coletada, cálculo derivado e dado sintético de teste. Dados sintéticos não pertencem aos conjuntos de pesquisa ou previsão.
- Não substituir ausências por zero, interpolar preços, duplicar pregões ou corrigir divergências automaticamente.
- Uma URL declarada não autentica uma fonte. Um hash confirma consistência de bytes, não veracidade econômica.
- Registrar período solicitado e recebido, unidade, moeda, fuso, política de ajustes e limitações. Informação desconhecida permanece desconhecida.
- Confrontar preços, calendário e eventos com evidência independente antes de avaliar a estratégia. Mais registros não substituem qualidade.
- Para variáveis de previsão, registrar quando a informação ficou disponível e usar apenas o que já era conhecido na decisão. Data de referência sozinha não prova ausência de informação futura.

## Estado verificado em 13/09/2026

O histórico demo de quatro códigos contém 1.032 barras D1. Os dois relatórios derivados referenciam o mesmo SHA-256 do histórico preservado. A comparação de calendário cobre somente o período pesquisado. Divergências entre normal e fracionário e ajustes por proventos continuam pendentes.

O inventário `reports/data-evidence-inventory-20260913.json` identifica cinco artefatos de pesquisa, categorias, hashes e limitações. Nenhum está aprovado para previsão. Ele não cobre todos os arquivos do projeto nem os arquivos recebidos em Downloads.

Esta política e o inventário documentam a pesquisa. Não constituem bloqueio global já implementado no robô: os coletores atuais não alimentam a estratégia, e a integração futura deverá impor a validação antes de aceitar qualquer conjunto. Não ativar o backend supondo que estes metadados já sejam fiscalizados por ele.

## Proteções aplicadas à ingestão existente

A normalização agora rejeita colunas ou valores ausentes: não replica fechamento como preço ajustado nem elimina barras com valores nulos. O caminho Yahoo mantém a duplicação explícita de Close em adj_close apenas porque a requisição já usa auto_adjust=True; isso não confirma a exatidão dos ajustes da fonte.

Na leitura brapi, ausência de histórico é erro, sem fabricar candle a partir da cotação atual e do relógio do computador. Na leitura Yahoo padrão, suspeitas identificadas pelo filtro legado bloqueiam o lote inteiro, sem entregar a série com barras removidas. Os limiares legados são heurísticas, não prova de erro econômico.

Limitação: sanitize=False permanece disponível para inspeção bruta; consumidores diretos do banco, filtro macro e outras entradas ainda não passam por uma autorização comum baseada em evidências. A função legada sanitize_ohlcv continua disponível para análises antigas. Estas correções não completam uma barreira global de previsão. O backend permanece desligado.

## Validação na entrada do motor de sinais

compute_signal agora valida as barras antes dos indicadores, inclusive quando os dados chegam por fora da ingestão. Rejeita campos ausentes, nulos, números não finitos, preços não positivos, volumes negativos, OHLC incoerente e datas diárias repetidas ou fora de ordem. O analista encaminha abertura e fechamento recebidos do feed para essa verificação. Séries curtas continuam sem sinal.

Esta barreira é estrutural. Não comprova origem, ajustes, calendário, disponibilidade histórica da informação nem atualidade do feed. Não altera o filtro macro nem autoriza os históricos demo pendentes. A autorização global por evidências ainda exige integração própria.

## Aprovação obrigatória no compute_signal

O motor principal agora consulta `config/data_approvals.json` antes de calcular indicadores. O registro começa vazio, portanto nenhum conjunto produz sinais por esse caminho até revisão. Isso também impede sinais nos backtests que usam o motor real; resultado vazio não é avaliação de rentabilidade. Testes que substituem o motor não certificam esta integração.

A aprovação vincula o ticker e a sequência exata de barras normalizadas (datas, OHLC, fechamento ajustado e volume) a um SHA-256. Exige identificação do revisor, notas e quatro referências locais com hashes: origem, calendário, ajustes e disponibilidade temporal da informação. Ausência, ambiguidade, arquivo de evidência alterado ou inexistente bloqueiam o sinal. Uma fatia, novo pregão ou preço alterado requer nova revisão; não há aprovação herdada do DataFrame ou de argumentos opcionais.

O registro local é a fronteira de confiança administrativa: somente uma revisão efetiva deve acrescentar entradas. O código confere vínculo e integridade, não interpreta nem prova a veracidade dos relatórios. Quem puder editar código, registro e evidências pode alterar essa política; não é uma assinatura criptográfica nem defesa contra administrador malicioso. Nenhuma aprovação de produção foi criada. Evidências sintéticas existem exclusivamente em diretórios temporários dos testes.

Escopo: compute_signal e seus consumidores. Esta mudança não habilita execução nem resolve a validação do filtro macro, frescor ao vivo ou outros motores independentes. O histórico demo segue pendente de comparação de preços. Os parágrafos anteriores descrevem etapas anteriores; a aprovação obrigatória agora existe no motor principal, sem representar autorização global de ordens.

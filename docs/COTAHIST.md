# Histórico B3 para pesquisa

O módulo `trading_bot.data.cotahist` importa TXT local no layout oficial de
245 bytes. Não faz download, envia ordens, altera configurações ou alimenta
sinais/backtests. Nenhuma dependência adicional foi instalada.

```powershell
python -m trading_bot.data.cotahist --input caminho/COTAHIST.TXT --output reports/importacao-nova --tickers PETR4 PETR4F VALE3 VALE3F --source-url URL_ORIGINAL
```

O destino deve ser uma pasta nova. São produzidos `quotes.csv` e
`manifest.json`; o manifesto é escrito por último. Pasta sem manifesto indica
exportação incompleta. Nenhum arquivo de origem ou destino anterior é apagado.

## Validação

- Confere tamanho, tipos de registro, cabeçalho, rodapé e contagem completa.
- Valida campos numéricos sem reparar caracteres ou substituir erros por zero.
- Preserva preços nominais com Decimal, fator de cotação de sete posições,
  ISIN, distribuição, moeda e tipo de mercado. Não presume preço por ação
  quando o fator de cotação é diferente de um.
- Valida estrutura e OHLC de todos os registros; seleciona apenas os tickers
  pedidos. Duplicação é checada na seleção por data/ticker/mercado/ISIN/distribuição.
- Erros estruturais impedem exportação. Alertas semânticos ficam no CSV e no
  manifesto: preço zero, volume incompatível, moeda/mercado fora do escopo.
- Reconcilia volume financeiro com preço médio × quantidade / fator, com
  tolerância de um centavo no preço médio por unidade cotada, mais um centavo
  no volume financeiro. É um alerta de investigação, não prova de erro da fonte.
- Registra SHA-256 do TXT e verifica que ele não mudou durante a importação.
  URL informada pelo operador é origem declarada, não autenticação da fonte.

`ready_for_backtest` permanece falso: faltam calendário, completude histórica,
eventos corporativos, universo sem viés e avaliação dos alertas. Preços e datas
são os do arquivo; não são corrigidos por dividendos, inflação ou calendário.
A data do pregão não é convertida artificialmente em timestamp UTC.

## Verificação com arquivo oficial em 13/09/2026

Foi baixado o ZIP público de demonstração da B3. O TXT contém 553 registros
(551 cotações, cabeçalho e rodapé). Foram selecionados quatro registros de
PETR4, PETR4F, VALE3 e VALE3F, todos de 12/02/2003. Não é um histórico de
anos, nem dados atuais. VALE3F recebeu alerta de volume financeiro:
103,65 × 1.595 = 165.321,75, contra 165.301,91 informado no arquivo.
O valor original foi preservado. A causa dessa diferença não foi determinada.

Download e comprovante SHA-256 em `reports/b3-official-sample/`; importação em
`reports/b3-sample-import/`. O download mensal do portal solicitou CAPTCHA,
portanto não foi concluído. Nenhum CAPTCHA foi contornado.

Fontes:
- https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/historico/mercado-a-vista/cotacoes-historicas/
- https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf
- https://www.b3.com.br/data/files/9C/F3/01/C4/297BE410F816C9E492D828A8/SeriesHistoricas_DemoCotacoesHistoricas12022003.zip

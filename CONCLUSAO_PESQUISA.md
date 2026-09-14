# Meridian — Conclusão da Pesquisa

**Encerrado em 2026-07-27.** Este documento fecha o Meridian como investigação.
Não é um relatório de progresso: é o registro do que foi medido, do que se
concluiu, e — principalmente — dos **erros de medição** encontrados no caminho.

> **Decisão:** não construir a camada de execução para capital real.
> A justificativa é aritmética, não opinião. Está na seção 2.

---

## 1. O quadro final medido

Todos os números abaixo são de **dado saneado**, universo corrigido por
sobrevivência, contra **benchmark de mesmo risco** (25% IBOV + 75% CDI
rebalanceado diariamente), janela **OOS 2011-2025**, com filtro de liquidez
X=1% do ADTV e modelo de impacto de mercado ativo.

| métrica | valor |
|---|---|
| excesso sobre benchmark de mesmo risco | **+2,02% a.a.** |
| `t` robusto a cluster anual | **+1,18** (limiar 1,96) → **NÃO significativo** |
| Information Ratio | +0,207 |
| teto de capacidade | **R$100 mil** (inviável em R$1M) |
| drawdown máximo | ~17% |
| **valor absoluto** | **≈ R$2.000/ano** |

> ⚠️ **Correção (2026-07-28).** A primeira versão deste documento pareava
> `+2,02%` com `t=+1,82`. Os dois números vinham de **runs diferentes** — o
> excesso de `liq_c100000_x0.01` (R$100k, X=1%, com slippage) e o `t` de
> `san_congel2` (capital R$300, sem slippage nem filtro de liquidez, cujo
> excesso era +3,42%). Medidos no MESMO run, o par correto é
> **(+2,02% ; t=+1,18)**. A correção **reforça** a não-significância.

> ⚠️ **Múltiplos testes.** Ao longo da pesquisa foram testadas **13
> configurações** (11 famílias de estratégia + 2 combinações). Reportar o
> melhor `t` de 13 tentativas **infla o número por seleção**. Com correção de
> Bonferroni o limiar efetivo seria ≈ **2,7**, não 1,96 — e o melhor `t`
> medido em qualquer configuração foi **+1,31**.

### Robustez do que foi medido

O teto de R$100k é **robusto a três modelos de impacto** de mercado — raiz
quadrada com coeficiente 1,0, raiz com 0,5, e linear. A magnitude do excesso
varia (+2,02% a +3,83%), mas **o sinal não inverte em nenhum nível de
capital**, e o teto fica em R$100k nos três cenários.

O edge **por trade** é real e significativo (t=+2,78, 1.100+ trades). O que
não é significativo é o excesso da **carteira** sobre o benchmark — porque o
sleeve de ações é ≤25% do patrimônio (kelly 0,25 / 3 posições), então o alfa
dele dilui contra a régua.

### Onde o dado é confiável

A janela com <5% de anomalia em volume **e** preço é **2019-2025** (7 anos).
Com o filtro de sanidade aplicado por pregão — em vez de descartar anos
inteiros — a janela de 15 anos é preservada com 88% do dado e 97% dos trades.
Os números acima usam essa segunda abordagem.

---

## 2. A conclusão, em aritmética

**Não construir a camada de execução para capital real.**

O raciocínio tem três passos, todos medidos:

**1. O teto de capacidade é R$100 mil.** Acima disso o impacto de mercado
consome o excesso: em R$1M o excesso vira **−2,50% a.a.**, negativo em todos
os três modelos de impacto testados.

**2. O valor absoluto no teto é ~R$2.000/ano.** R$100.000 × 2,02%. E o excesso
não é estatisticamente significativo (t=+1,82) — ou seja, R$2.000/ano é o
ponto-estimativa de uma quantidade cuja barra de erro cruza zero.

**3. O TETO É POR MERCADO.** Escalar capital não aumenta o valor absoluto —
acima de R$100k o excesso vira negativo, então o retorno em reais **cai**.
Apenas **mais mercados em paralelo** aumentariam o total.

A camada de execução (OMS, adapter da corretora, ledger, reconciliação,
idempotência, tratamento de rejeição/parcial/desconexão) foi estimada em
**~12 semanas**. Construir 12 semanas de engenharia de risco financeiro para
capturar R$2.000/ano não-significativos, num teto que não escala, é a decisão
errada por aritmética simples.

### E a sondagem de cripto não muda isso

| | B3 | cripto (8 pares ≥7 anos) |
|---|---|---|
| ADTV mediano | R$103,8M/dia | US$106,5M/dia (R$575M) |
| razão | — | **5,5×** |
| custo round-trip | 0,10% | 0,20% |
| histórico | 940 ativo-anos | ~66 (**14× menos**) |

O teto implicado em cripto seria ~R$550k → valor absoluto ~R$9.000/ano
(**4,5×**, não ordens de grandeza). E isso **assumindo que o edge transfere**
— hipótese não testada, com 14× menos dado para testá-la.

⚠️ Uma comparação inválida foi descartada no caminho: a razão "menor-vs-menor"
dá 1.192×, mas compara o par de cripto menos líquido com a **menor small cap**
da B3. O gargalo de uma carteira de 3 posições é o ativo menos líquido **que
ela escolhe**, e o filtro de liquidez já rejeita os ilíquidos. A comparação
justa é a mediana: 5,5×.

---

## 3. Os SETE erros de medição

**Este é o ativo mais transferível do projeto.** Cada um destes defeitos
produziu — ou teria produzido — uma conclusão errada com aparência de rigor.
Nenhum foi erro de estratégia; **todos foram erro de dado ou de modelagem do
dado.**

### 3.1 Warm-up truncava 200 pregões de cada regime

`run_regime_backtest` cortava o DataFrame **para** a janela do regime antes de
calcular indicadores, e depois exigia 200 barras para a SMA-200. Os primeiros
200 pregões de cada janela ficavam incapazes de gerar sinal.

- **Conclusão errada que gerou:** *"o filtro de tendência funciona em bear real
  — `crise_volatilidade`: n=0 trades"*. A janela tinha 148 pregões e precisava
  de 200: era **impossível** abrir posição ali. Registrado como fato no
  backlog.
- **Também invalidava** a baseline "Sharpe −1,22", colhida em ~metade de duas
  janelas e nada da terceira.
- **Corrigido:** `warmup_bars=300` como história de indicador, com `all_dates`
  restrito à janela para não contaminar o regime.

### 3.2 Caixa ocioso rendia 0%

`capital_cash` — o dinheiro fora de posições — ficava parado. Com kelly 0,25 e
3 slots, o teto de exposição é 25%: **~66% do patrimônio rendia zero**, e em
42% dos pregões não havia posição alguma.

- **Conclusão errada que gerou:** *"a estratégia perde para o CDI, Sharpe
  −0,33"*. A comparação confrontava 100%-no-CDI contra 34%-em-ações-**e-66%-
  embaixo-do-colchão** — alternativas que ninguém escolheria.
- **Depois da correção:** Sharpe **+0,27**, CAGR 12,72% contra 10,08% do CDI.
  **O sinal da conclusão principal inverteu.**
- **Corrigido:** `cash_daily_yield` com a série real do CDI (SGS 12).

### 3.3 Otimizador ranqueava contra risk-free ZERO

`calculate_sharpe_ratio` tinha default `risk_free_rate=0.0` — e é a função que
**ordena** os resultados de uma varredura de parâmetros.

- **Conclusão errada que teria gerado:** selecionar configurações que batem
  zero, não o CDI. Num país de juros de dois dígitos, "melhor que zero" é um
  filtro que não filtra — com aparência de rigor (varredura ampla, ranking
  ordenado, melhor config no topo).
- **Medido no RED:** uma curva rendendo **4% a.a. num mundo de 10% a.a.
  pontuava Sharpe +0,494** — positivo, e subiria no ranking.
- **Segundo defeito na mesma função:** a taxa era subtraída de um retorno
  **diário** enquanto o nome e a docstring diziam "anualizado". Quem passasse
  `0.10` pensando "10% a.a." subtrairia **10% por dia**.
- **Corrigido:** `risk_free_annual` explícito, convertido internamente, com
  default da mesma fonte do portão.

### 3.4 Viés de sobrevivência

O universo de 50 tickers foi escolhido **hoje** por liquidez — empresas que
quebraram no caminho não estavam nele.

- **Quanto custava:** 0,82 p.p. de CAGR (12,72% → 11,91%) e 0,70 p.p. do
  excesso. O p-valor foi de 0,065 para **0,128**.
- **Como foi medido:** adicionando ao universo os desastres conhecidos da B3
  que o yfinance ainda serve (OGXP3, que **deslista em 2019-01-10**; AMER3,
  IRBR3, OIBR3, PDGR3, RSID3, VIVR3, GFSA3, TCSA3, CVCB3, LIGT3). Nesses
  tickers a estratégia entrega **−0,033%/trade** contra +0,555% nos
  sobreviventes.
- **Correção incompleta e assumidamente conservadora:** 3 dos 14 desastres não
  têm dados, e a lista foi montada com hindsight. O viés residual real é
  provavelmente **maior**.

### 3.5 ADTV corrompido no yfinance

O volume de tickers brasileiros é sistematicamente quebrado em períodos
antigos — **não** por grupamento, mas por **dado ausente**.

```
PCAR3  2017: R$280/dia | 2019: R$1.313/dia | 2020: R$96.473.549/dia (73.478x)
```

PCAR3 é blue chip há décadas; volume de 3 ações/dia em 2008 não existe.
**11,6% de todos os pregões** têm volume financeiro < R$100k/dia, e 31 de 58
tickers têm >2% de pregões ruins — vários com corte sistêmico em `2018-01-25`.

- **Conclusão errada que gerou:** *"capital máximo entre R$10k e R$50k"*.
  Doze trades (1,7%) com ADTV inválido respondiam por **40,5% de todo o
  slippage**, com participação média de **119% do volume diário** —
  fisicamente impossível de executar.
- **Depois da correção:** teto de **R$100k**, 10-20× maior.
- **Armadilha evitada:** testar o filtro de liquidez sobre esse dado teria
  removido exatamente os trades corrompidos e produzido uma curva
  **espetacular e falsa**.

### 3.6 Encoding cp1252 na leitura de config

`AppConfig.load()` e `ingestion._load_settings()` usavam `open()` sem
`encoding=`. Sem ele, Python usa a codepage do **sistema** — cp1252 no
Windows, UTF-8 em Linux.

- **O bug era latente e dependia de QUAL acento alguém escrevesse:** `ã`, `ç`,
  `é` viram bytes que existem em cp1252 (decodificavam **errado, em
  silêncio**); já `Í` é UTF-8 `\xc3\x8d`, e `\x8d` é **indefinido** em cp1252.
- **O que aconteceu:** escrever "IRREPRODUZÍVEL" num comentário do
  `settings.yaml` derrubou **29 testes** de uma vez.
- **Por que importa além do susto:** a config vinha sendo lida com texto
  corrompido silenciosamente em toda máquina Windows. O mesmo commit passaria
  no CI (Ubuntu, UTF-8) e quebraria em produção local.
- **Corrigido:** `encoding="utf-8"` explícito, com teste **estrutural (AST)**
  que varre o projeto — um teste de comportamento passaria no CI e falharia só
  em Windows, que é exatamente como o bug sobreviveu tanto tempo.

### 3.7 Modelo "linear" que era no-op

No script de sensibilidade ao modelo de impacto, o bloco que deveria emular o
modelo linear fazia `v * sqrt(a) / sqrt(a)` — algebricamente **igual a `v`**.

- **Conclusão errada que teria gerado:** reportar "linear vs raiz" tendo
  comparado **raiz com raiz**, e concluir que o modelo não importa porque os
  números batem — quando na verdade os dois cenários eram o mesmo cenário.
- **Corrigido:** parâmetro `slippage_exponent` real no engine, com teste que
  trava a relação (expoente 1,0 pune **menos** que 0,5 quando a participação é
  <100%, porque √x > x para x<1).
- **Lição:** o instrumento de medição precisa de teste como o código medido.

### O padrão comum

Todos os sete produziam números **plausíveis**. Nenhum estourava, nenhum
gerava aviso. Cinco deles alteraram — ou teriam alterado — o **sinal** ou a
**ordem de grandeza** de uma conclusão. A defesa que funcionou não foi
revisão de código: foi **ceticismo simétrico** — aplicar à boa notícia o mesmo
rigor que se aplica à má.

---

## 3.8 Varredura de famílias — o que mais foi testado e falhou

Depois do encerramento, 11 configurações de estratégia foram medidas sob a
mesma régua (dado saneado, X=1%, caixa no CDI, benchmark 25/75, custo com
componente fixo, impacto de mercado, OOS 2011-2025, R$100k), com parâmetros
**canônicos da literatura, não otimizados**.

```
estrategia        exc a.a.      IR  t robusto  P(exc<=0)   maxDD     n  winrate
Donchian 20d        +2.02%  +0.180      +1.18      0.119  -17.4%   630   41.1%
Donchian+ADX        +4.02%  +0.273      +1.12      0.127  -22.6%   757   44.0%
Cruz.50/200         +1.28%  +0.124      +0.62      0.267  -12.8%   275   50.2%
Squeeze Boll.       +1.42%  +0.124      +0.57      0.278  -23.1%   657   44.6%
Donchian 55d        +0.76%  +0.074      +0.42      0.343  -19.1%   552   41.1%
Donchian 40d        +0.63%  +0.060      +0.38      0.371  -17.4%   589   40.4%
Mom.absoluto        +0.19%  +0.011      +0.04      0.475  -38.7%   690   44.6%
RSI(2)Connors       -2.34%  -0.174      -0.70      0.739  -36.7%   812   42.7%
Mom.XS 12-1         -2.81%  -0.176      -0.81      0.796  -31.2%   670   43.6%
Boll.reversao       -3.30%  -0.308      -1.21      0.886  -29.3%   398   39.9%
Reversao 5d         -6.25%  -0.375      -1.67      0.953  -50.0%   761   43.0%
```

**Nenhuma passa 1,96.** Combinação 50/50 das duas melhores: `t`=+1,31.

Quatro achados que valem além do veredito:

**Reversão é negativa neste universo — não voltar ali.** As três variantes
perdem (RSI(2), Bollinger, 5 dias), somando **1.971 trades**, e a mais
agressiva é a pior. Não é ruído: é padrão.

**Variar o período do Donchian não diversifica.** Correlação do 20d com o 40d
= **0,86** e com o 55d = **0,79**, e ambos rendem menos. É a mesma aposta com
calibração pior. Diversificar exige mudar de **família**, não de parâmetro.

**Donchian+ADX é o caso didático de por que ranquear por RETORNO engana.** Tem
o maior excesso (+4,02%, o dobro do Donchian puro) e simultaneamente `t`
**menor** (+1,12), o IC95% **mais largo de todos** ([−2,84%, +11,21%]) e
drawdown pior (−22,6%). O ADX seleciona menos oportunidades e mais
concentradas: a média sobe, a variância sobe mais. Um ranking por retorno o
colocaria em primeiro; por confiança, ele perde.

**Diversificação melhora, mas não cria edge onde não há.** As estratégias com
excesso positivo são pouco correlacionadas entre si (ρ 0,15-0,30) — o cenário
em tese ideal. Combinar as duas melhores dá `t`=+1,31, superior a qualquer
isolada e ainda muito longe de 1,96 (ou dos ~2,7 exigidos por Bonferroni).
**Duas medianas descorrelacionadas continuam sendo duas medianas.**

---

## 4. O que fica reutilizável

Independentemente do destino da estratégia, estes componentes medem
honestamente e servem a qualquer pesquisa futura:

### Motor de backtest que mede honestamente
`trading_bot/backtest/engine.py` — com warm-up correto, caixa ocioso rendendo
a taxa livre de risco real, custo com componente fixo **e** percentual,
impacto de mercado por participação no volume, filtro de liquidez na entrada,
e regime testado sem contaminação de janela. Cada um desses termos existe
porque a ausência dele produziu uma conclusão errada documentada acima.

### Filtro de sanidade de dados
`trading_bot/data/sanity.py` — descarta o **pregão** implausível em vez do
período, preservando janela e poder estatístico. Dois critérios objetivos
(volume financeiro implausível, fechamento congelado) e uma recusa deliberada:
**não** filtra por retorno extremo, porque queda de 50% num dia é evento real
e removê-la enviesaria o backtest para cima.

### Modelo de custo com componente fixo
Corretagem fixa não escala com o tamanho da posição — R$2,50 numa posição de
R$75 é 3,3% por ordem. Foi o que revelou que R$300 de capital com corretagem
fixa é **ruína matemática**, não margem apertada.

### Benchmark de mesmo risco
Comparar uma carteira 25%-exposta contra 100%-CDI compara riscos diferentes. O
benchmark honesto é 25% IBOV + 75% CDI rebalanceado. Foi essa régua que
mostrou que o overlay agrega ~2,4 p.p. — e que o IBOV puro **perdeu** do CDI
no período (8,17% vs 10,06%), então "bastaria comprar índice" era falso.

### Série do CDI versionada
`trading_bot/data/cdi_sgs12.csv` + `risk_free.py` — 5.022 pregões (2006-2025)
da API SGS do Banco Central. Alimenta o rendimento do caixa ocioso e o
risk-free do portão, que agora **deriva da série** em vez de uma constante.

### Protocolo anti-overfitting
Critérios declarados **antes** de rodar; separação IS/OOS com o OOS gasto uma
única vez por hipótese; exigência de **platô** de parâmetro em vez de ponto
ótimo; bootstrap de bloco anual e `t` robusto a cluster (retornos diários são
autocorrelacionados — o `t` ingênuo mente). Foi esse protocolo que rejeitou a
hipótese do whipsaw em 12 de 12 células e que impediu a otimização de
parâmetros de virar caça a ruído.

### Fail-closed assimétrico entre backtest e produção
`backend/app/risk/liquidity.py` — o **mesmo** dado ausente significa coisas
diferentes: no backtest é lacuna histórica (não bloqueia, senão apaga trades
por falta de dado e enviesa a medição); em produção é feed degradado **agora**
(bloqueia entrada, mantém gestão de saída).

---

## 5. Limitações que permanecem

Registradas para que ninguém retome o projeto assumindo mais do que foi
provado:

- **Nada disso é estatisticamente significativo.** O melhor `t` robusto medido
  foi +1,82, abaixo de 1,96. O ponto-estimativa é positivo e consistente; a
  barra de erro cruza zero.
- **Sem árbitro externo de dados.** brapi exige token (HTTP 401); toda a
  auditoria é auto-consistente, sem uma segunda fonte para confirmar.
- **O modelo de impacto é estimativa, não medição.** Nunca observamos execução
  real. A forma da curva é robusta; a magnitude não.
- **Viés de sobrevivência residual** — a correção é conservadora e incompleta.
- **IR não modelado** (15% swing, com isenção de R$20 mil/mês em vendas).
- **O edge em cripto nunca foi testado** — só a liquidez foi sondada.
- **Dado licenciado é pré-requisito** para qualquer decisão sobre capital
  próprio. brapi Pro (~R$117/mês) ou feed da corretora. O yfinance serve para
  pesquisa exploratória e **não** para decidir sobre dinheiro real.

---

## 5b. O que está RODANDO em paper trading (2026-07-28)

**Estratégia em produção: Donchian 20d.** É o `compute_signal` que o
`MarketAnalyst` já usava — zero mudança de código no sinal.

⚠️ **A combinação 50/50 (Donchian 20d + Donchian+ADX) NÃO está rodando e NÃO
é executável.** O `+3,01% a.a.` e o `t=+1,31` daquela linha da varredura são a
**média de duas séries de excesso** calculada em pós-processamento — não a
medição de uma estratégia que alguém possa operar. O motor ao vivo executa um
sinal por vez; rodar dois exigiria arquitetura nova. Nenhum backtest mediu uma
implementação que produza aquele número em operação.

Escolha do Donchian 20d sobre o Donchian+ADX, apesar do ADX ter excesso maior
(+4,02% vs +2,02%): `t` **maior** (+1,18 vs +1,12), IC95% muito mais estreito
([−1,34%, +5,53%] vs [−2,84%, +11,21%]) e drawdown melhor (−17,4% vs −22,6%).
Estabilidade acima de retorno nominal — e zero mudança de código elimina risco
de bug na virada.

**O que dos parâmetros da pesquisa se aplica ao runtime:**

| parâmetro | ao vivo? | por quê |
|---|---|---|
| filtro de liquidez X=1% | **SIM, ligado** | proteção real; fail-closed sem ADTV |
| filtro de sanidade | não | calibrado para barra diária; no feed de 1min descartaria 100% das barras de papéis de liquidez média (medido) |
| caixa ocioso no CDI | n/a | contabilidade de backtest — ao vivo o dinheiro rende o que a corretora paga |
| custo com componente fixo | n/a | modelagem de backtest — ao vivo o custo é o que a corretora cobra |

**Paper trading contra broker simulado.** O `CedroClient` é fictício: `auth()`
devolve token mock e `send_order()` devolve `order_id` hardcoded, sem HTTP.
As "ordens" gravam em SQLite local. Isso é deliberado — ver seção 2.

## 6. Estado do repositório

- **436 testes passando** (suíte completa, incluindo e2e).
- **Modo:** PAPER TRADING. Nenhuma ordem real foi implementada.
- **Camada de execução:** deliberadamente **não construída** (ver seção 2). O
  `CedroClient` permanece fictício — `auth()` devolve token mock, `send_order()`
  devolve `order_id` hardcoded, sem HTTP.
- **Histórico das reversões:** o `BACKLOG.md` mantém o registro de cada
  conclusão que mudou de sinal, com os números crus de antes e depois. É
  proposital: quem retomar precisa ver que o projeto errou e como corrigiu,
  não só o estado final.

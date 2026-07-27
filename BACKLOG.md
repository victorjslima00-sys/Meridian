# Backlog Meridian

Itens conhecidos, ainda não implementados. Marcados por prioridade.

## 🧭 ACHADO METODOLÓGICO (vale mais que qualquer resultado desta sessão)

Duas armadilhas que o projeto atravessou inteiras antes de perceber. Valem
para toda pesquisa futura, aqui ou em outro mercado.

**1. Significância num nível não transfere para outro.** O edge POR TRADE do
Donchian é real e significativo: t=+2,78, +3,06 na expectância por trade,
1.100+ trades, IC95% por bootstrap de bloco anual que não cruza zero. Mas o
excesso da CARTEIRA sobre o CDI **não** é significativo: t=+1,21 (o sleeve de
ações é ≤25% do patrimônio, então o alfa dele dilui contra o benchmark).
Provar que os trades têm expectância positiva e provar que a carteira bate a
renda fixa são perguntas diferentes — a primeira não implica a segunda.
**Sempre medir contra o custo de oportunidade real (CDI), e no nível da
CARTEIRA, não do trade.** (Ver o achado central: a conclusão "perde do CDI"
era artefato de caixa a zero; corrigida, o ponto-estimativa vira positivo mas
segue dentro do ruído.)

**2. Descrever a perda não é prevê-la.** A anatomia de 848 trades mostrou um
padrão nítido e estatisticamente forte: 52% dos perdedores fazem o topo no
próprio dia da entrada; 0% dos ganhadores tem MFE ≤ 1%; o corte "topo até o
dia 2" separava win rate de 8% contra 69%. Parecia um filtro pronto. **Era
descrição verdadeira e preditor inútil** — "dia do topo" só se conhece na
saída, então a informação que separa os grupos só existe DEPOIS do fato. A
versão para a frente da mesma hipótese foi rejeitada em 12 de 12 células.

Corolário prático: toda métrica derivada do histórico COMPLETO de um trade
(MFE, dia do topo, duração) é suspeita como sinal. Antes de desenhar regra
em cima de um padrão, perguntar: **essa informação existiria no momento da
decisão?**

## 🟡 ACHADO CENTRAL — REVERTIDO: "perde para o CDI" era artefato do caixa a zero

**A conclusão anterior ("perde para o CDI, Sharpe −0,33") NÃO sobreviveu à
correção do caixa ocioso.** Era artefato de um defeito de modelagem: o
backtest rendia 0% sobre o dinheiro fora de posições, que é ~66% do
patrimônio em média (kelly 0,25 / 3 slots → teto de exposição 25%; 42% dos
pregões sem posição alguma). A comparação confrontava 100%-no-CDI contra
34%-em-ações-**e-66%-embaixo-do-colchão**.

Corrigido (`cash_daily_yield`, o caixa ocioso rende o CDI diário real,
`trading_bot/data/cdi_sgs12.csv`), a mesma carteira de PRODUÇÃO
(`max_positions=3`, R$300, 2006-2025, custo 0,10%), stdout cru:

```
cenario                          n    final R$    CAGR    maxDD  Sharpe vs CDI  Calmar
COM filtro + caixa CDI (PROD)  848     3289.94  12.72%  -16.9%        +0.270   0.752
COM filtro, caixa ZERO (antigo)848      852.77   5.36%  -17.9%        -0.334   0.300
CDI (SGS serie 12), base R$300  —      2046.10  10.08%      —              —       —

excesso sobre CDI (config producao, caixa corrigido):
  Information Ratio anualizado = +0.270
  t-stat ingenuo               = +1.21   (>1.96 = significativo)
  t-stat robusto a cluster anual = +1.24   (20 anos)
  anos com excesso positivo sobre CDI: 9/20
```

**A leitura honesta — nem "perde", nem "ganha" com confiança:**

1. **O sinal do ponto-estimativa VIROU.** Com o caixa corrigido a carteira
   rende **12,72% a.a. contra 10,08% do CDI**, com drawdown menor (−16,9% vs
   as próprias oscilações do 100%-CDI seriam ~0, mas contra buy-hold de ações
   é baixo). Sharpe vs CDI de −0,334 para **+0,270**; Calmar 0,752.
2. **MAS o excesso sobre o CDI NÃO é estatisticamente significativo:** t=+1,21
   (ingênuo) / +1,24 (robusto a cluster anual), ambos < 1,96; bate o CDI em
   apenas **9 de 20 anos**. O ponto-estimativa é positivo; a barra de erro
   cruza o CDI com folga.
3. **De onde vem o resultado:** a carteira é ~75%+ CDI o tempo todo, com uma
   sobreposição de ações de no máximo 25%. Os +2,64 p.p. sobre o CDI vêm
   dessa sobreposição fina. **Não é "a Donchian é ótima"** — é "um overlay
   pequeno de ações sobre CDI adiciona ~2,6 p.p., dentro do ruído".
4. **O edge POR TRADE continua real e significativo** (t=+2,78 na expectância
   por trade): as ações que a estratégia compra têm expectância positiva. O
   que não é significativo é o excesso da CARTEIRA sobre o CDI — porque o
   sleeve de ações é pequeno demais para o alfa dele descolar do benchmark.

**A lição metodológica desta reversão** (registrada no topo, seção
"Significância ≠ vantagem econômica" tem agora sua irmã): um defeito de
modelagem no denominador da comparação inverteu o SINAL da conclusão
principal. O mesmo ceticismo aplicado à má notícia teve de ser aplicado à boa:
o resultado positivo também não passa no teste de significância.

**Próximo passo honesto:** o portão de aprovação e o otimizador precisam
medir contra CDI real E creditar o caixa (hoje só o `fase1_backtest.py`
credita; ver defeitos de medição). E a comparação justa não é contra
100%-CDI — é contra um benchmark de MESMO risco (ex.: 25% IBOV + 75% CDI),
que **não foi medido**.

### Capital mínimo operável — corretagem FIXA destrói conta pequena

> ⚠️ **Números CAGR/Sharpe/veredito desta tabela são do caixa-a-zero (antigo)
> e estão SUPERADOS pelo achado central revertido.** O que permanece VÁLIDO e
> é o ponto desta seção: (a) corretagem FIXA destrói contas pequenas, (b) o
> retorno percentual do sleeve de ações é invariante a escala. A conclusão
> "nenhum capital opera" caía do teto 5,36%, que era artefato — com o caixa no
> CDI o teto sobe. Não reler os vereditos "perde do CDI" abaixo como atuais.

`fixed_fee_per_order` (corretagem fixa em R$ por ordem) agora é modelado —
antes o custo era 100% percentual, o que escondia o efeito abaixo:

```
  capital  taxa fixa  trades    cap.final    CDI daria     CAGR  Sharpe vs CDI  veredito
      300 R$    0.00     848      852.77     2044.77    5.36%         -0.334  perde do CDI
      300 R$    2.50      60        5.24     2044.77  -18.32%         -1.558  conta destruida
      300 R$    5.00      30        8.46     2044.77  -16.35%         -1.326  conta destruida
    10000 R$    2.50     848    20887.64    68158.85    3.75%         -0.470  perde do CDI
    10000 R$    5.00     848    13349.53    68158.85    1.46%         -0.665  perde do CDI
    50000 R$    0.00     848   142128.75   340794.25    5.36%         -0.334  perde do CDI
    50000 R$    2.50     848   134590.64   340794.25    5.08%         -0.359  perde do CDI
    50000 R$    5.00     848   127052.53   340794.25    4.78%         -0.384  perde do CDI
```

- **R$300 com QUALQUER corretagem fixa = conta destruída.** Com R$2,50/ordem
  o capital acaba após 60 trades (de 848 possíveis). A posição típica é
  ~R$75; R$5 de round-trip fixo são 6,7% por trade contra uma expectância de
  +0,56%. Não é margem apertada — é ruína matemática.
- **O custo fixo deixa de ser fatal por volta de R$10k e vira irrelevante em
  R$50k** (come 1,61 p.p. do CAGR em R$10k, 0,28 p.p. em R$50k).
- **O retorno percentual do sleeve de ações é invariante a escala.** Controle:
  com taxa fixa zero, R$300 e R$50.000 dão CAGR do sleeve **idêntico**
  (5,3646%, diferença 0,000000 p.p.). Isso continua válido. **O que mudou:**
  esse 5,36% era o CAGR SEM o caixa render — com o caixa no CDI a carteira
  vai a 12,72%. A frase original "nenhum capital opera porque o teto 5,36% <
  CDI" está ERRADA: o teto não era 5,36%, era o sleeve isolado. Corrigido, a
  carteira supera o CDI no ponto-estimativa (sem significância — ver achado
  central).

**O que o modelo de custo ainda NÃO cobre** (relevante antes de configurar
custo real): IR de 15% sobre ganho líquido em swing trade (com isenção de
R$20 mil/mês em vendas — irrelevante em R$300, material em R$50k);
emolumentos/liquidação da B3 (~0,03%, hoje teriam de ser embutidos no
`brokerage_pct`); custo assimétrico entrada vs saída; e impacto de mercado
proporcional à liquidez.

### Hipótese do whipsaw: REJEITADA no in-sample

A anatomia de 848 trades sugeria que perdedores param de subir quase
imediatamente. A versão **para a frente** dessa hipótese — "no fechamento do
dia N, sai se não avançou X%", decidida só com preço até N, sem look-ahead —
foi implementada (`early_exit_day` / `early_exit_min_gain`) e testada.

Critérios declarados ANTES de rodar: excesso sobre o CDI ≥ 0; amostra ≥
metade do baseline; ganho tem de aparecer como platô, não como ponto único.
IS = 2006-2015, OOS = 2016-2025 reservado.

```
IN-SAMPLE 2006-2015 | CDI 10,91% a.a. | BASELINE sem regra: excesso -6,44% a.a., Sharpe -0,668, n=353

              X=0%                      X=1%                      X=2%
  N=1    -8.11%aa Sh-0.95 n=504    -8.73%aa Sh-1.14 n=566    -7.70%aa Sh-1.03 n=613
  N=2    -7.61%aa Sh-0.87 n=468    -7.48%aa Sh-0.92 n=508    -7.37%aa Sh-0.93 n=546
  N=3    -7.82%aa Sh-0.87 n=439    -9.47%aa Sh-1.13 n=467    -9.32%aa Sh-1.13 n=493
  N=5    -8.19%aa Sh-0.89 n=400    -8.59%aa Sh-0.95 n=424    -8.46%aa Sh-0.97 n=434
```

**As 12 células são PIORES que o baseline.** Não há platô, não há ponto
único bom, não há o que escolher. A hipótese morre no in-sample e o **OOS
2016-2025 permanece intocado** — preservado para um teste futuro que
mereça gastá-lo.

**Por que falha** (medido, baseline vs N=2/X=1% no mesmo IS):

```
                          BASELINE      COM A REGRA
  n                            353              508
  win rate                   43.3%            38.0%
  ganho medio do vencedor    +6.20%           +4.06%   (-34%)
  perda media do perdedor    -3.98%           -2.15%   (-46%)
  expectancia por trade     +0.431%          +0.213%   (METADE)
  saidas                  stop 164,        early_exit 288,
                          timeout 69       timeout 7
```

**A hipótese acertou o diagnóstico e errou o remédio.** A regra REALMENTE
corta as perdas — a perda média cai 46%, mais do que os 34% que ela corta do
ganho médio. Mesmo assim a expectância cai pela metade, porque o **win rate
despenca de 43,3% para 38,0%**: a regra mata no dia 2 trades que ainda não
tinham andado mas que teriam virado vencedores. Ganhadores fazem o topo por
volta do dia 11; exigir avanço no dia 2 é exigir cedo demais.

Reduzir a perda média não basta quando o custo é converter vencedores em
perdedores. Vale como aviso para toda a família: **não insistir em variações
de "cortar cedo" para esta estratégia** — o problema não é o tamanho das
perdas, é que o sinal precisa de tempo para se manifestar.

Lição de método: o padrão "perdedores topam no dia 0" era descrição
verdadeira e preditor inútil — a informação só existe depois do fato. A
distinção entre descrever a perda e prevê-la é o que separou uma hipótese
promissora de um resultado nulo.


## 📊 BENCHMARK DE MESMO RISCO (25% IBOV + 75% CDI) — o teste que decide

Comparar com 100%-CDI compara carteiras de risco diferente. O benchmark justo
para uma estratégia que fica ~25-34% em ações é **25% IBOV + 75% CDI
rebalanceado**, mesmo período, mesmo custo. Medido 2026-07-26:

```
                          final R$    CAGR    maxDD  Sharpe vs CDI  Calmar
ESTRATEGIA (producao)      3289.94  12.72%  -16.9%        +0.270    0.752
25% IBOV + 75% CDI         2121.34  10.28%  -16.1%        +0.063    0.640
CDI puro                   2046.10  10.06%      —              —       —
IBOV puro                        —   8.17%      —              —       —
```

**A estratégia bate o benchmark de mesmo risco em CAGR (+2,44 p.p.), Sharpe e
Calmar.** Nota: o IBOV puro PERDEU do CDI no período (8,17% vs 10,06%) — não
é o caso de "bastaria comprar índice".

### Significância do excesso — marginal, NÃO conclusiva

```
                      vs CDI      vs 25/75 (DECISIVO)
Information Ratio     +0.271      +0.240
excesso anualizado    +3.13%      +2.70%
desvio do excesso   0.7155%/d    0.7006%/d
t-stat ingenuo        +1.20        +1.06
t-stat cluster anual  +1.29        +1.51
anos positivos         9/20        11/20

correlacao estrategia x IBOV = 0.323
BOOTSTRAP de bloco anual (10k) do excesso sobre 25/75:
  IC95% = [-0.71% ; +6.39%] a.a.
  P(excesso <= 0) = 0.065   -> NAO significativo a 5%
```

**Uma armadilha de raciocínio corrigida aqui:** era intuitivo supor que, sendo
o excesso sobre o 25/75 MENOR em magnitude que sobre o CDI, o `t` também seria
menor. Falso — `t = média/(desvio/√n)`, e o 25/75 contém IBOV, correlacionado
com o sleeve de ações (ρ=0,323), então parte da variância **cancela** na série
de diferença. Medido: o desvio cai (0,7155% → 0,7006%/dia) e o **t robusto a
cluster anual SOBE de +1,29 para +1,51**, com 11/20 anos positivos contra
9/20. Magnitude e significância são coisas distintas.

**Veredito honesto:** p=0,065 é sugestivo, não conclusivo. O IC95% cruza zero
por pouco (−0,71%). **Não afirmar "edge demonstrado"** — afirmar "excesso
positivo consistente, marginalmente fora da significância convencional, com
20 anos de dados". **E este número ainda NÃO corrige sobrevivência — ver
abaixo, que o reduz.**

### Viés de sobrevivência: custa 0,82 p.p. de CAGR (medido, não estimado)

O universo de 50 tickers foi escolhido HOJE por liquidez — empresas que
quebraram no caminho não estão nele. Correção aplicada: adicionar ao universo
os **desastres conhecidos da B3** que o yfinance ainda serve (OGXP3, que
**deslista em 2019-01-10**; AMER3 (fraude 2023); IRBR3 (fraude 2020); OIBR3,
LIGT3, PDGR3, RSID3, VIVR3, GFSA3, TCSA3, CVCB3 — 11 dos 14 tentados
entraram). Universo 47 → 58.

```
                              47 sobreviventes  58 (+11 desastres)     delta
  capital final R$                     3289.94             2844.46   -445.48
  CAGR %                                 12.72               11.91     -0.82
  max drawdown %                         -16.9               -16.9      -0.0
  excesso s/ 25/75 % a.a.                 2.70                2.00     -0.70
  Information Ratio                      0.240               0.171    -0.068
  t cluster anual                         1.51                1.16     -0.35
  trades                                   848                 935       +87

  trades EM tickers-desastre: 168 (18% do total)
    media/trade nos desastres    = -0.033%
    media/trade nos sobreviventes= +0.555%   -> diferenca -0.588 p.p.

  BOOTSTRAP (universo corrigido) IC95% = [-1.31% ; +5.54%] a.a.
  P(excesso <= 0) = 0.128  -> NAO significativo
```

**O viés é real e mensurável: 0,82 p.p. de CAGR e 0,70 p.p. do excesso.** Nos
tickers-desastre a estratégia entrega −0,033%/trade contra +0,555% nos
sobreviventes — quase 0,6 p.p. de diferença. Com o universo corrigido, o
excesso sobre o 25/75 cai para **+2,00% a.a.** e a significância piora de
p=0,065 para **p=0,128**.

**Limitação desta correção (não é completa):** 3 dos 14 desastres tentados não
têm dados no yfinance (MMXM3, HRTP3, BTOW3/LAME4/VIIA3 aparecem como
renomeações ou sumiram), e a própria lista foi montada com hindsight — sei
quais quebraram. A correção é **conservadora e direcionalmente correta**
(só pode piorar o resultado, e quantifica quanto), mas o viés residual
verdadeiro é provavelmente **maior** que 0,82 p.p., não menor. Correção plena
exigiria composições históricas de índice, que o projeto não tem.


### Walk-forward: o EDGE sobrevive, a OTIMIZAÇÃO de parâmetros é rejeitada

Primeiro walk-forward do projeto (antes, tudo era in-sample de 20 anos).
Protocolo: 5 folds, IS 5 anos → OOS 3 anos, grade 3×3
(`breakout_period` ∈ {10,20,40} × `target_atr_mult` ∈ {2,3,4}), seleção no IS
por excesso sobre o 25/75, avaliação no OOS. **Critérios declarados ANTES de
rodar.**

```
fold OOS        sel bp/tat    exc SEL   IR SEL   exc FIXO  IR FIXO
2011-2013           10/4.0     +3.57%   +0.379     +2.50%   +0.267
2014-2016           10/3.0     +6.99%   +0.577     +4.04%   +0.348
2017-2019           10/4.0     -3.87%   -0.350     +0.07%   +0.006
2020-2022           40/3.0     -4.73%   -0.406     -4.98%   -0.428
2023-2025           40/4.0     +7.35%   +0.803    +10.68%   +1.019
------------------------------------------------------------------------
  MEDIA OOS   SELECIONADOS: +1.86% a.a.  |  FIXOS (producao): +2.46% a.a.
  folds positivos:  SEL 3/5  |  FIXO 4/5
```

**Contra os critérios pré-declarados:**

| # | critério | SEL | FIXO |
|---|---|---|---|
| 1 | OOS agregado > 0 | PASSA (+1,86%) | **PASSA (+2,46%)** |
| 2 | ≥3/5 folds positivos | PASSA (3/5) | **PASSA (4/5)** |
| 3 | platô estável do parâmetro | **FALHA** | n/a |
| 4 | otimização agrega? | **NÃO** (−0,60 p.p.) | — |

**Duas conclusões opostas, e ambas importam:**

1. **O EDGE SOBREVIVE fora da amostra, com os parâmetros de PRODUÇÃO.**
   +2,46% a.a. de excesso médio sobre o 25/75 em 5 janelas OOS, 4 das 5
   positivas — notavelmente próximo do +2,70% medido in-sample nos 20 anos
   (e do +2,00% corrigido por sobrevivência). O edge não evapora.
2. **A OTIMIZAÇÃO DE PARÂMETROS é rejeitada.** O `breakout_period` ótimo salta
   de **10** (folds 2006-2016) para **40** (folds 2015-2022) — não há platô,
   há dois regimes. E os params escolhidos pelo walk-forward performam **PIOR**
   no OOS (+1,86%) que simplesmente manter os fixos (+2,46%), com menos folds
   positivos (3/5 vs 4/5).

**O lado bom do critério 3 falhar:** significa que a config de produção
(`bp=20`, `tat=3.0`) **NÃO está sobreajustada** — ela é um meio-termo que
performa tão bem ou melhor que qualquer escolha "ótima" fora da amostra.
**Não perseguir parâmetro ótimo nesta família de estratégia** — a superfície
muda de regime e otimizar é caçar ruído.

**Limitação:** 5 folds é amostra pequena para o próprio walk-forward, e a
variância entre folds é enorme (−4,98% a +10,68%). O +2,46% é média de 5
pontos muito dispersos; **não faz sentido testar significância com n=5**.

### O NÚMERO HONESTO: walk-forward OOS com universo corrigido

Os +2,46% acima ainda carregavam o viés de sobrevivência. Re-rodado com o
universo expandido (58 tickers, com os desastres):

```
fold OOS          n   exc 47 (viesado)   exc 58 (honesto)    delta    IR 58
2011-2013        95             +2.50%             +2.84%    +0.34   +0.315
2014-2016       136             +4.04%             +3.64%    -0.40   +0.301
2017-2019       178             +0.07%             +2.35%    +2.28   +0.189
2020-2022       145             -4.98%             -4.33%    +0.65   -0.357
2023-2025       139            +10.68%             +6.62%    -4.06   +0.590
------------------------------------------------------------------------
  MEDIA OOS   universo 47: +2.46%  |  universo 58 (HONESTO): +2.22% a.a.
  MEDIANA     universo 47: +2.50%  |  universo 58: +2.84%
  folds positivos: 4/5 em ambos    |    IR medio (58): +0.207
```

**Este é o número de referência da estratégia: +2,22% a.a. de excesso sobre
o benchmark de mesmo risco, fora da amostra, com o universo corrigido por
sobrevivência, 4 de 5 janelas positivas.** O viés custou só 0,24 p.p. no OOS
(contra 0,70 p.p. na amostra cheia) — porque o OOS cobre 2011-2025, onde há
menos casualidades que no início da série.

### Decaimento do edge: HIPÓTESE REFUTADA — o edge é MAIS forte no recente

Motivação da suspeita: o fold IS 2018-2022 teve 6 de 9 combinações com
excesso negativo. Se o edge decaísse monotonicamente, a média de 20 anos
superestimaria a expectativa futura — que é o que importa para capital
próprio. Medido em blocos de 5 anos, universo expandido, params de produção:

```
bloco              n     CAGR    bench   excesso a.a.       IR    maxDD
2006-2010        244   13.35%   13.72%         -0.00%   -0.000   -10.7%
2011-2015        161    6.34%    5.54%         +1.01%   +0.109    -9.0%
2016-2020        305   15.33%   12.16%         +3.74%   +0.267   -13.7%
2021-2025        225   12.90%   10.07%         +3.18%   +0.292   -16.9%

  tendencia: -0.00% -> +1.01% -> +3.74% -> +3.18%
  monotonicamente decrescente? NAO
  inclinacao: +1.23 p.p. por bloco de 5 anos
  media 2006-2015: +0.51%   |   media 2016-2025: +3.46%
```

**O edge CRESCE, não decai.** Os dois blocos recentes (+3,46% médio) são
muito melhores que os dois antigos (+0,51%). O bloco 2006-2010 entrega
excesso ZERO.

**Por que a intuição estava errada, e é instrutivo:** na amostra viesada o
período antigo parecia forte (+0,98%/trade pré-2010 contra +0,55% pós-2016).
Isso era **survivorship inflando o passado** — as empresas que quebraram entre
2008 e 2015 (OGX, PDG, Rossi, Viver) não estavam no universo. Corrigido, o
passado desinflaciona e a tendência inverte de sinal. O "6 de 9 negativos" do
IS 2018-2022 era artefato daquela janela específica (crash COVID + bear de
2022), não uma tendência.

**Ressalva:** 4 blocos é amostra minúscula; a inclinação de +1,23 p.p./bloco
vem de 4 pontos e **não é estatisticamente significativa**. A conclusão
defensável é a negativa — **não há evidência de decaimento** — não a positiva
de que o edge esteja crescendo de forma confiável.


## 🚫 ALTA FREQUÊNCIA — HIPÓTESE TESTADA E REJEITADA (2026-07-26)

Proposta avaliada: muitas operações pequenas (~100/dia, alvo R$5-10) apostando
em alta taxa de acerto. **Rejeitada por aritmética**, não por opinião. Não
reabrir sem dado novo que contrarie os mecanismos abaixo.

Win rate de EMPATE: `W = 0,5 + C/(2A)` — C = custo round-trip como fração da
posição, A = alvo. Custo do repositório (`engine.py`): `(brokerage_pct +
spread_pct) × 2`, mais `fixed_fee_per_order × 2 / posição`.

```
custo SO percentual (fixo R$0):
  alvo A | rt=0.1% | rt=0.2% | rt=0.3% | rt=0.5%
  0.25%  |  70.0%  |  90.0%  | IMPOSS  | IMPOSS
  0.50%  |  60.0%  |  70.0%  |  80.0%  | IMPOSS
  1.00%  |  55.0%  |  60.0%  |  65.0%  |  75.0%
  2.00%  |  52.5%  |  55.0%  |  57.5%  |  62.5%
  6.00%  |  50.8%  |  51.7%  |  52.5%  |  54.2%

com FIXO R$2,50/ordem (R$5/round-trip), pct=0.1%:
  alvo A | pos R$100 | pos R$1000 | pos R$10000
  0.25%  |  IMPOSS   |  IMPOSS    |   80.0%
  0.50%  |  IMPOSS   |  IMPOSS    |   65.0%
  1.00%  |  IMPOSS   |   80.0%    |   57.5%
  2.00%  |  IMPOSS   |   65.0%    |   53.8%
  6.00%  |   92.5%   |   55.0%    |   51.2%
```

**Dois mecanismos independentes matam a hipótese:**

1. **B3 — a corretagem FIXA mata antes de começar.** R$5 de round-trip fixo
   numa posição de R$100 são 5% de custo; qualquer alvo < 2,5% fica
   literalmente IMPOSSÍVEL (o custo excede o alvo, nenhum win rate salva).
   Alta frequência pressupõe posições pequenas E alvos pequenos — exatamente
   o quadrante morto.
2. **Cripto (sem taxa fixa) — o win rate exigido é inatingível.** A 0,2% de
   round-trip (Binance taker), alvo de 0,5% exige **70%** de acerto e 1% exige
   60%. O sinal medido do projeto entrega ~43% de acerto, operando com alvos
   de ~6% e MFE de +8% — regime de alvo GRANDE/horizonte diário. Encolher o
   alvo empurra a exigência para 60-70%, sem nenhuma evidência de que seja
   alcançável.
3. **Tributação piora ainda mais.** Day trade paga **20%** sobre ganho líquido
   **sem** a isenção de R$20 mil/mês (que só vale para swing), mais IRRF
   "dedo-duro" de **1% sobre o ganho líquido do dia** (creditável, mas trava
   caixa recorrentemente). Para o MESMO retorno líquido, o edge bruto acima do
   empate precisa ser 1/(1−0,20) = **25% maior**.

**Conclusão registrada:** não existe combinação de alvo/custo/capital que
torne a hipótese viável na B3; em cripto só fecharia com win rate de 60-70%,
para o qual não há evidência. O edge que o projeto tem (rompimento diário,
alvo ~6%) **não é transportável** para alta frequência.


## 🪙 CRIPTO — o custo já começa dentro da faixa que matou a B3

Registrado ANTES de qualquer implementação, porque muda a expectativa.

`engine.py` calcula `round_trip = (brokerage_pct + spread_pct) × 2`. Todas as
medições da BT foram reportadas em **round-trip**:

```
  B3, modelo usado          0,10% round-trip  (0,05% por ponta)
  Binance taker realista    0,20% round-trip  (0,10% por ordem)   = 2x a B3
  Binance conservador       0,30% round-trip  (com slippage)      = 3x a B3
```

**A B3 perdeu significância estatística a 0,3% de round-trip** (t caiu de
+2,78 para +1,78, abaixo de 1,96) e o CAGR desabou de 5,36% para 3,18%.

Ou seja: **cripto na Binance começa a 0,2% — metade do caminho até o ponto
onde o edge da B3 morreu — e o cenário conservador cai exatamente em cima
dele.** Não é um detalhe de configuração; é a expectativa correta antes de
rodar. Uma estratégia de rompimento em cripto precisa de um edge bruto
materialmente maior que o da B3 só para empatar depois do custo.

### Critério de aprovação declarado ANTES de rodar

Benchmark primário: **buy-and-hold da mesma carteira de moedas**, no mesmo
período, com o **mesmo custo aplicado**. CDI como piso.

Aprovação exige **ajuste a risco, não retorno absoluto**:

- `Sharpe(estratégia) > Sharpe(buy-and-hold)` **E**
- `Calmar(estratégia) > Calmar(buy-and-hold)`

Retorno absoluto sozinho NÃO aprova. Buy-and-hold de BTC tem drawdown de
~-80%; uma estratégia que rende 70% do BTC com metade do drawdown pode ser
superior, e uma que rende mais com drawdown pior não é. Este critério existe
para não repetir na cripto o erro que a B3 expôs: aprovar contra régua baixa.


## 🔧 DEFEITOS DE MEDIÇÃO — corrigir ANTES de qualquer pesquisa nova

Nenhum dos dois é o portão (`backtest.min_sharpe_aggregate`). **O portão está
CORRETO:** `metrics.py::_trade_sharpe` já subtrai risk-free e reprovou a
estratégia atual (`Sharpe Agregado: -0.18 [REPROVA]`). Os defeitos estão em
volta dele — registrar isso importa porque a sessão chegou a acreditar que o
portão media contra zero, confundindo-o com o otimizador.

### 1. ~~PRIORIDADE ALTA — o otimizador ranqueia contra ZERO~~ ✅ CORRIGIDO (PR #18)

`calculate_sharpe_ratio` agora ranqueia contra `RISK_FREE_RATE_ANNUAL` (mesma
régua do portão), com o parâmetro renomeado para `risk_free_annual` (era
`risk_free_rate=0.0`, e ainda subtraía taxa anual de retorno diário). Fica o
registro do que era: ranquear contra zero selecionava configs que batem zero,
não o CDI, com aparência de rigor. Medido no RED: curva de 4% a.a. num mundo
de 10% pontuava Sharpe +0,494.

### 1b. PENDENTE — os otimizadores NÃO creditam o caixa ocioso

O `cash_daily_yield` (caixa ocioso rende CDI) só está ligado em
`fase1_backtest.py`. Os otimizadores (`backtest/optimizer.py:76`,
`signals/optimizer.py:62`, `scripts/fase3_quant_optimizer.py:92`) chamam
`run_regime_backtest` **sem** ele → medem com caixa a zero. Como o caixa a
zero distorce o CAGR (ver achado central), qualquer varredura de parâmetros
hoje ranqueia por uma métrica enviesada. **Religar antes de qualquer Fase 3.**
Não foi feito neste turno porque muda comportamento de código de medição, que
exige aprovação explícita.

### 1c. 🔴 BLOQUEANTE PARA CAPITAL REAL — impacto de mercado não modelado

O modelo de custo é **fração fixa** da posição (`brokerage_pct`,
`spread_pct`) mais taxa fixa por ordem. Nenhum termo escala com a **liquidez
do ativo**. Em R$300 isso é irrelevante: a posição típica de R$25-75 não move
preço nenhum. Com capital real a premissa quebra — quando a ordem vira fração
material do volume diário negociado, o preço de execução piora com o tamanho,
e o efeito é **não-linear**.

Consequência direta: **todo backtest deste repositório superestima o retorno
de uma carteira grande**, e superestima mais quanto maior o capital. O
`12,72%` medido é um teto que assume execução sem impacto.

**Exige dado que o projeto não tem:** volume/liquidez diária por ativo
(ADTV), para derivar um termo de impacto proporcional a
`(tamanho da ordem / volume diário)`. Enquanto isso não existir, **não é
possível dimensionar o capital máximo operável** — nem afirmar que o edge
sobrevive a ele. Bloqueante antes de qualquer R$ real acima de valores
simbólicos.

### 2. Risk-free é número mágico fixo

`trading_bot/backtest/metrics.py:24` — `RISK_FREE_RATE_ANNUAL = 0.10`
("Selic aproximada"). Usado por `_trade_sharpe` (o portão) e por `_sortino`.

Calibrou bem **por coincidência**: o CDI medido em 2006-2025 deu 10,08% a.a.
Mas é fixo — se a Selic for a 15% ou cair a 2%, o portão segue medindo
contra 10% em silêncio, e aprova ou reprova errado sem avisar. Viola a regra
do próprio CLAUDE.md: "nunca usar número/limite inventado quando já existe um
equivalente configurado no sistema — derivar dali, não duplicar".

**Deveria vir da série real do BCB.** ✅ **A série já está versionada**
(`trading_bot/data/cdi_sgs12.csv` + `trading_bot/data/risk_free.py`,
`load_cdi_daily_fractions` / `cdi_annualized`). Falta o passo final: fazer
`metrics.RISK_FREE_RATE_ANNUAL` derivar de `cdi_annualized()` em vez da
constante 0,10 — aí o portão acompanha a Selic real em vez de um número fixo.
Não feito neste turno (muda comportamento do portão; exige aprovação).

### A/B do filtro macro (ibov_filter) — medido com a régua corrigida

Nunca havia sido validado: `ibov_filter=True` rodava em tudo sem medição. Com
o caixa no CDI (régua correta), 2006-2025:

```
              n     CAGR    maxDD   Sharpe vs CDI  Calmar
COM filtro   848   12.72%  -16.9%       +0.270     0.752
SEM filtro  1154   11.78%  -22.6%       +0.186     0.522
```

**O filtro macro vence nas duas métricas** (Sharpe E Calmar) e corta o
drawdown de −22,6% para −16,9%, ao custo de 306 trades. Mantê-lo ligado.
Ressalva de poder: são ~4-5 episódios de regime macro em 20 anos; o delta é
indicativo, não prova. (Na medição anterior, com caixa a zero, a régua estava
torta CONTRA o filtro — ele perdia em Sharpe; a correção do caixa reverteu
isso, porque o filtro aumenta o tempo em caixa, que agora rende.)


## 🛑 PRIORIDADE MÁXIMA — A BASELINE ANTERIOR ERA INVÁLIDA (bug de warm-up, corrigido)

**Correção de registro (2026-07-23).** A entrada anterior deste backlog
afirmava duas coisas como fato. Ambas eram falsas, e ambas vinham do MESMO
defeito de medição:

1. ~~"O projeto não possui estratégia com edge demonstrado" (Sharpe -1,22)~~
2. ~~"O filtro de tendência FUNCIONA em bear real (`crise_volatilidade`:
   n=0 trades)"~~

**O bug.** `run_regime_backtest` cortava o DataFrame PARA a janela do regime
**antes** de calcular indicadores (`engine.py:132`) e depois exigia
`len(df_hist) >= 200` para a SMA-200 (`engine.py:241`). Os primeiros 200
pregões de CADA janela ficavam estruturalmente incapazes de gerar sinal:

```
crise_volatilidade   148 pregões ->   0 testáveis (0%)
alta_juros           396 pregões -> 196 testáveis (49%)  — só a partir de 2022-03-22
recuperacao_lateral  372 pregões -> 172 testáveis (46%)  — só a partir de 2023-10-19
```

- **O `n=0` do `crise_volatilidade` NÃO era prova de nada.** A janela tem 148
  pregões e o backtest precisava de 200: era impossível abrir posição ali,
  independentemente do que o mercado fizesse. Foi artefato de medição
  registrado como fato. Com o bug corrigido, a mesma janela produz **29
  trades** — o filtro de tendência **não** bloqueou o crash da COVID.
- **A baseline `-1,22` é inválida.** Vinha de 50 trades colhidos em ~metade
  de duas janelas e em nada da terceira.

**Correção:** `warmup_bars=300` — barras anteriores ao `start` entram só como
história de indicador; `all_dates` continua restrito a `[start, end]`, então
nenhuma entrada ocorre fora do regime medido. Regressão em
`tests/test_backtest_warmup.py` (RED provado antes do fix).

**Baseline NOVA** (2026-07-23, `scripts/fase1_backtest.py`, parâmetros de
produção 1.5/3.0, custo 0,10% round-trip), stdout cru:

```
Trades totais: 138
Sharpe Agregado: -0.18 ([REPROVA])
  crise_volatilidade: n=29  wr=34%  aw=+7.9%  al=-4.1%  Sh=-0.17
  alta_juros        : n=55  wr=31%  aw=+6.9%  al=-3.9%  Sh=-0.95
  recuperacao_latera: n=54  wr=44%  aw=+6.3%  al=-3.6%  Sh=0.58
```

- A amostra quase triplicou (50 → 138) e o agregado subiu de -1,22 para
  **-0,18**. `recuperacao_lateral` passou de -0,09 para **+0,58** — agora
  acima do portão de 0,5 por regime.
- **O achado do whipsaw sobrevive, atenuado:** `alta_juros` segue o pior
  regime (**-0,95**, wr 31%), mas longe do -2,49 anterior.
- **O `~0.33` do comentário em `settings.yaml` continua irreproduzível** com
  os dados atuais. Causa provável: tickers deslistados (ELET3/ELET6/NTCO3 dão
  404 no yfinance hoje), janela/fonte diferente (settings menciona brapi.dev),
  ou versão anterior da estratégia. Não usar como referência.

**Sobre "existe edge?" — a pergunta segue ABERTA, e a razão é tamanho de
amostra.** Com desvio de ~5% por trade, provar um edge de +0,5%/trade a 95%
com 80% de poder exige **~730 trades**; os 3 regimes dão 138. As medições de
amostra longa (20 anos, universo atual) estão registradas na seção
"Pesquisa de estratégia" abaixo. **Não afirmar ausência de edge com base nos
3 regimes** — eles cobrem 18% do tempo disponível e são o pedaço pior dele.

Os Commits 3 (pandas-ta) e 4 (filtro fundamental) da Fase 1 seguem
**cancelados**: enriquecer indicadores antes de ter uma medição confiável é
otimizar no escuro. A ordem correta é medir, depois decidir.


## Pesquisa de estratégia — medições de amostra longa (2026-07-23)

Universo atual (47 dos 50 tickers retornam dados), 2006-2025, parâmetros de
produção, com o warm-up já corrigido.

**Carteira real — `max_positions=3`, capital R$300** (é este o número que
responde "o bot ganha dinheiro", não a expectância por trade):

```
round-trip     n   cap.final   ret total     CAGR  Sharpe curva    MaxDD  media/trade       t
     0.0%   848    1051.49      250.5%    6.47%          0.62   -17.5%       0.656%   +3.28
     0.1%   848     852.77      184.3%    5.36%          0.52   -17.9%       0.556%   +2.78   <- custo modelado hoje
     0.3%   848     560.60       86.9%    3.18%          0.34   -21.6%       0.356%   +1.78
     0.5%   848     368.26       22.8%    1.03%          0.15   -30.6%       0.156%   +0.78
```

Sem cap efetivo (`max_positions=50`, custo 0,1%): n=1148, média +0,524%/trade,
t=+3,06. **O cap de 3 captura 74% do fluxo de sinal** — não é o gargalo.

### O que estes números dizem, e o que NÃO dizem

- **Custo é a variável que decide.** `engine.py:123` modela
  `(brokerage 0,03% + spread 0,02%) × 2 = 0,10%` de round-trip. A **0,3% o
  edge deixa de ser estatisticamente significativo** (t=1,78 < 1,96); a 0,5%
  o CAGR cai para 1,03%. Para posições de algumas dezenas de reais,
  corretagem **fixa** (ex.: R$2,50) equivale a 5-10% de round-trip — nesse
  regime não sobra nada. **Confirmar se a corretora cobra percentual ou fixo
  é pré-requisito para qualquer decisão de operar.**
- **Sharpe aqui é contra risk-free ZERO** (`optimizer.py:13`,
  `risk_free_rate=0.0`). No Brasil de 2006-2025 a taxa livre de risco rodou
  em dois dígitos na maior parte do período. Um CAGR de 5,36% com drawdown
  de -17,9% provavelmente perde para renda fixa com folga. **Significância
  estatística não é o mesmo que valer a pena** — a comparação contra CDI
  **não foi medida** e é o próximo teste honesto.
- **Viés de sobrevivência não corrigido:** o universo foi escolhido hoje.
  Trades pré-2010 rendem +0,98%/trade contra +0,55% pós-2016 — o viés infla,
  e infla mais no começo da série.

### Anatomia das perdas — re-medida sobre 848 trades

```
                 dias ate o topo (mediana)   topo no dia 0    MFE mediana
PERDEDORES (488)            0                52%              +1.93%
GANHADORES (360)           11                 2%              +8.40%
```

Saídas: `stop` 420, `stop_gap` 47, `target` 206, `target_gap` 19,
`timeout` 154. Win rate 42%.

**O padrão é real e forte:** metade dos perdedores nunca faz uma máxima nova
depois do dia da entrada; 0% dos ganhadores tem MFE ≤ 1%.

⚠️ **MAS o corte "topo até o dia 2 → win rate 8% / topo depois → 69%" é em
boa parte TAUTOLÓGICO** e não deve ser lido como filtro achado. "Dia do
topo" só é conhecido na saída: um trade cujo topo é o dia da entrada é, quase
por definição, um trade que só caiu. A versão acionável tem de ser uma regra
**para a frente** — "no fim do dia N, com informação só até N, sai se não
avançou X%" — e essa **não foi testada**. Não confundir a descrição da perda
com um preditor.


## Multi-mercado (encaixe pronto na Fase 1, Commit 1)

- **Resolução de mercado para tickers SEM sufixo (cripto).** Hoje
  `markets/resolve_market()` descobre o mercado pela FORMA do ticker
  (sufixo `.SA` ou padrão B3 `AAAA9`) — pragmático porque só a B3 existe.
  Quando cripto entrar, a forma CERTA de estender é **resolução explícita
  por config** (um mapa ticker→mercado no `settings.yaml`, ou registro por
  padrão/prefixo), **NÃO** um `if symbol in {"BTC-USD", ...}` hardcodado em
  `resolve_market`. Hardcodar símbolo é o bug que só aparece quando o
  segundo mercado chega. `resolve_market` já FALHA (ValueError) em ticker
  não reconhecido em vez de assumir B3 — o tripwire está posto; o que falta
  é a fonte de verdade em config para os símbolos de cripto.


- **O que falta para plugar um MERCADO NOVO (ex.: cripto).** A camada
  `backend/app/markets/` já define os protocolos `Market` e `Broker` e traz
  `B3Market` + `PaperBroker`. Adicionar cripto = criar uma implementação de
  `Market` e registrá-la em `markets/__init__.py::get_market`. O que essa
  implementação precisa resolver, que a B3 resolve de um jeito e cripto de
  outro:
  1. **Feed próprio** — a B3 usa yfinance com sufixo `.SA`; cripto usa par
     (BTC-USD) e provavelmente outra fonte (exchange/API), com outra
     granularidade e outro rate limit.
  2. **Calendário 24/7** — `is_open()` na B3 é dia útil + 10:00-17:30; em
     cripto é sempre aberto, e o conceito de "dia de pregão" (usado no
     snapshot diário de equity) precisa de uma convenção explícita (UTC?
     fuso do usuário?).
  3. **Corretora** — `PaperBroker` serve para simular qualquer mercado, mas
     uma corretora real de cripto tem taxa, precisão decimal e mínimo de
     ordem próprios; entra como outra implementação de `Broker`.
  4. **Sem lote/fracionário** — cripto não tem lote padrão nem mercado
     fracionário separado, o que remove a fragmentação de custo que a B3 tem
     (ver item de custo de fracionário abaixo).
  5. **Feriados** — `B3Market.is_open()` NÃO considera feriados da B3 (exigiria
     calendário externo). Um mercado novo precisa decidir o equivalente.
  - Nota: `is_open()` existe mas **não está ligado ao laço de trading** — ligá-la
    mudaria comportamento (hoje o bot opera fora do pregão). É uma decisão
    explícita pendente, não um esquecimento.

## Alta prioridade

- **ROI Global removido do dashboard (Track B, 2026-07-21) — precisa de
  fonte de verdade de capital inicial antes de voltar.** O card calculava
  `((patrimonio_total - 100) / 100) * 100` no frontend (`App.jsx`), com
  `100` fixo no código, sem nenhum registro real de capital inicial
  (não existe `capital_inicial` em `settings.yaml` nem coluna equivalente
  no banco). Rotulado "Retorno Histórico (Real)", o que passava confiança
  indevida a um número sem base. Mais grave: a partir do momento em que o
  CapitalVault (`POST /api/portfolio/depositar`/`retirar`) for usado, esse
  cálculo passaria a misturar **movimentação de capital** com **resultado
  de trading** — um depósito de R$500 apareceria como se fosse lucro de
  500%. Achado durante o diagnóstico do Track B (dashboard-v2), tratado
  como prioridade 1 pelo usuário: "número real com fórmula quebrada,
  rotulado 'Real', que vira mentira ativa assim que o CapitalVault for
  usado".
  **Antes do ROI poder voltar à UI, é preciso um trabalho de backend com o
  mesmo rigor de tudo que mexe em capital**: uma fonte de verdade dedicada
  para capital inicial — coluna própria (ex.: `capital_inicial` em
  `portfolio`, setada uma vez no primeiro depósito real) ou o primeiro
  `equity_snapshot` gravado, **isolada** de depósitos/retiradas
  subsequentes do cofre (senão o mesmo problema de hoje se repete: uma
  movimentação de capital contaminando o cálculo de retorno). Com essa
  fonte definida, o ROI passa a ser `(equity_atual - capital_inicial) /
  capital_inicial`, sem tocar em `patrimonio_reservado` movimentado pelo
  cofre.
  Arquivos: `backend/app/data/database.py` (schema `portfolio`,
  `compute_current_equity`), `backend/app/main.py` (`/api/portfolio`,
  `/api/positions`), `frontend/src/App.jsx` (card removido, ver commit
  do Track B).

- **`get_risk_metrics()` (`backend/app/data/database.py`) tem um campo
  fabricado e um mal rotulado — achado durante o honest-dashboard Bloco
  3.** `"calmar": sharpe * 0.8` (comentário no próprio código: `#
  Approximated`) não tem relação nenhuma com a fórmula real de Calmar
  Ratio (retorno anualizado / max drawdown) — é um placeholder que imita
  métrica real, exatamente o que a regra nova do CLAUDE.md proíbe.
  `max_drawdown_pct` também é enganoso: hoje é só o pior trade individual
  (`min(losses)`), não o drawdown pico-a-vale real da curva de
  patrimônio — que agora dá pra calcular de verdade a partir de
  `equity_snapshots` (`GET /api/equity_snapshots`, Bloco 3). `sharpe`/
  `sortino`/`var_95_daily` são aproximações honestas mas não-padrão
  (retornos por trade, não série temporal anualizada com taxa livre de
  risco) — value real, só não é a métrica clássica que o nome sugere;
  vale um aviso na UI ou renomear os campos. Decidir: implementar calmar/
  drawdown de verdade a partir da equity curve, ou remover/renomear os
  campos até existir cálculo real.
  Arquivos: `backend/app/data/database.py` (`get_risk_metrics`),
  `frontend/src/EliteCharts.jsx` (`RiskMetricsPanel`).

- **Latência de stop-loss: PHASE 1 (saídas) só reavaliada a cada ciclo completo (10+ min).**
  Enquadramento: isto NÃO é performance — é latência de proteção de capital.
  O worker processa os tickers sequencialmente num único `for`; cada ticker em
  PHASE 2 (entrada) gasta 4–7 s em `await asyncio.sleep(2)` fixos (cadência de
  UI/log). Com 50 tickers, o ciclo passa de 10 min (ver medição no item de
  heartbeat abaixo). Consequência: a PHASE 1 (checagem de stop/target de uma
  posição aberta) de um dado ticker só roda uma vez por ciclo. **Um stop furado
  no minuto 2 só seria percebido no minuto 12.** Num bot que gerencia stop-loss,
  isso é risco direto de capital.

  **Solução proposta (decidir e implementar; pode ser mais urgente que o P3):**
  1. **Separar a cadência da PHASE 1 da PHASE 2.** Saídas (gestão de posições
     abertas) precisam de um laço próprio, rápido (poucos segundos), varrendo só
     os tickers com posição ativa — que são poucos. Entradas (PHASE 2, análise
     LLM de todo o universo) podem seguir num laço mais lento. Assim o stop de
     qualquer posição é reavaliado em segundos, independente do tamanho do
     universo.
  2. **Remover / reduzir drasticamente os `sleep(2)`.** São só espaçamento de
     log/UI; não têm função de trading. Removê-los encolhe o ciclo em ~200–350 s.
     Pode ser feito junto de (1) ou como primeiro passo isolado.
  Observação: FAIL-CLOSED continua valendo — a separação não pode deixar a
  PHASE 1 rodar com feed/preço não confiável.
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle` — PHASE 1 vs PHASE 2),
  `backend/app/worker_state.py` (cadências separadas, se necessário).

## Risco / Resiliência

- **Heartbeat marcado só no fim do ciclo → falso alarme com worker saudável.**
  O P2 grava o heartbeat (`mark_scan`) apenas quando `_run_one_scan_cycle()`
  termina. Um ciclo real sobre o universo atual (50 tickers) NÃO cabe dentro do
  `HEARTBEAT_TIMEOUT_SECONDS` (300s / 5 min), então `worker_alive` vira `false`
  com o worker saudável — falso alarme recorrente, e alarme que dispara à toa
  vira alarme ignorado.

  **Medição (13/07/2026, 50 tickers):**
  - Loop por ticker: ~4,8 s/ticker medido (16 tickers em ~77 s) → ~4–5 min só o
    laço, e uma execução completa NÃO terminou dentro de um teto de 10 min
    (o yfinance passa a limitar as chamadas e o backoff de retry do feed
    adiciona esperas crescentes — gaps de ~11 s observados no fim do ciclo).
  - Piso determinístico só dos `await asyncio.sleep(2)` fixos da fase de entrada:
    50 tickers × 4 s (todos HOLD) = **200 s**; × 6–7 s (BUY/SELL) = **300–350 s**.
    Ou seja, o piso sozinho já iguala/excede o timeout de 300 s.

  **Decisão tomada (não implementado):** heartbeat **granular** — marcar
  atividade a cada ticker processado dentro do `for`, mantendo SEPARADAS as duas
  noções: "última atividade" (por ticker, base do `worker_alive`) e "último
  ciclo completo". **NÃO aumentar `HEARTBEAT_TIMEOUT_SECONDS`**: detectar um
  worker travado só 15–20 min depois é inaceitável num bot que gerencia
  stop-loss. Um hang no meio do ciclo passa a ser detectado em segundos.
  Provável de ser feito junto do item de alta prioridade acima (a separação de
  cadências torna o heartbeat por atividade natural).
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle`, `ai_committee_worker`),
  `backend/app/worker_state.py` (`mark_scan`, separar `last_activity_at` de
  `last_full_cycle_at`).

- **P3-B — Resolvido (2026-07-20): `ResilientLLMClient` agora tem cadeia de
  fallback multi-provedor de verdade.** Motivado por um caso real: o tier
  gratuito do Gemini (`gemini-3.1-flash-lite`) permite só 15 req/min —
  varrer os ~50 tickers do universo em sequência rápida estoura isso em
  segundos (429). Implementado: `gemini -> groq -> cerebras -> github_models
  -> openai`, cada provedor só entra na cadeia se sua chave estiver
  configurada (`GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GITHUB_MODELS_TOKEN` —
  ver `.env.example`); em falha, tenta o próximo; só retorna `None`
  (→ `HOLD` fail-closed, decisão do P3-A) se todos os configurados falharem.
  Groq/Cerebras/OpenAI/GitHub Models usam um único cliente compartilhado via
  SDK `openai` (todos compatíveis com a API da OpenAI, só muda
  `base_url`/`model`). Também adicionado `LLM_CALL_SPACING_SECONDS = 4.5`
  em `main.py` entre chamadas consecutivas do laço de entradas, pra não
  estourar o limite por-minuto de nenhum provedor configurado.
  **Ainda pendente**: só o Gemini está com chave configurada até o usuário
  criar as contas gratuitas dos demais (Groq/Cerebras não exigem cartão;
  GitHub Models usa a conta GitHub já existente) e colar as chaves no
  `.env`. Sem isso, o comportamento é idêntico a antes (só Gemini, fail-closed
  em HOLD se ele falhar).
  Arquivos: `trading_bot/core/llm_client.py`, `backend/app/main.py`,
  `.env.example`, `tests/test_llm_client.py`.
  Arquivos: `trading_bot/core/llm_client.py`, `backend/app/agents/market_analyst.py`.

- **`llm.failure_policy` aceita `"technical_fallback"` no YAML mas é dead
  code.** `RuntimeConfig` valida e expõe `llm_failure_policy` (`hold` |
  `technical_fallback`), mas nenhum consumidor (`market_analyst.py`,
  `risk_manager.py`, `llm_client.py`) lê esse campo — o comportamento real é
  sempre `HOLD` hardcoded em `market_analyst.py`, independente do valor
  configurado. Não é vulnerabilidade (o hardcode é fail-safe), mas é uma
  opção enganosa: promete um comportamento (`technical_fallback`) que nunca é
  entregue. Ou implementar de verdade (junto do P3-B acima) ou remover a
  opção do config até existir.
  Arquivos: `backend/app/runtime_config.py`, `backend/app/agents/market_analyst.py`.

- **`RuntimeConfig.load()` relendo `config/settings.yaml` do disco a cada
  ticker do laço de entradas (~50x/ciclo), não 1x.** A Etapa 4 adicionou a
  checagem de `autonomous_entries_enabled` dentro do `for ticker in
  tickers_to_watch:`, chamando `RuntimeConfig.load()` (I/O síncrono, sem
  cache, abre e faz parse de dois arquivos YAML) a cada iteração — antes,
  `entradas_liberadas` já era calculado 1x fora do loop e reusado. Não é bug
  funcional (o comportamento continua correto), é I/O síncrono redundante
  bloqueando o event loop compartilhado com o `exit_loop` ~50x por ciclo em
  vez de 1x. Corrigir movendo `RuntimeConfig.load()` para antes do loop, ao
  lado de `entradas_liberadas`, reusando o resultado dentro do loop (mesmo
  padrão já usado para `entradas_liberadas`).
  Arquivos: `backend/app/main.py` (`_run_one_scan_cycle`).

- **Docstring/comentário de `risk_manager.py` ainda citam "10%" fixo.** O
  limite de posição virou parametrizável via `config/settings.yaml`
  (`max_position_fraction`, hardening pós-Etapa 4), mas a docstring da classe
  e um comentário interno ainda dizem "Maximum allocation limit bumped to
  10%" / "Max risk allowed is 10%" — podem confundir quem for alterar o valor
  depois, já que o número real agora vem do config, não do código.
  Arquivos: `backend/app/agents/risk_manager.py` (linhas ~29-30, ~39).

## Higiene de dependências

- **`pytest`/`pytest-asyncio` estão no `requirements.txt` de produção.** São
  ferramentas de teste e não deveriam ir para o ambiente de produção (o deploy
  instala só o `requirements.txt`). O lugar delas é o `requirements-dev.txt`.
  Não movidas no PR de fix do CI (`fix/ci-deps`) para manter aquele fix focado
  em declarar o que faltava. Mover num PR próprio de higiene.
- **Produção não está pinada com `==`.** Após o PR `fix/ci-deps`, só
  `pydantic==2.11.10` está pinado exato no `requirements.txt`; todo o resto usa
  faixas `>=` (`pandas>=2.0`, `yfinance>=0.2.40`, `requests>=2.31`, `pyyaml>=6.0`,
  `google-generativeai>=0.5`, `anthropic>=0.30`, `schedule>=1.2`, `numpy>=1.26`,
  `scipy>=1.13`, `click>=8.1`, `pytest>=8.0`, `pytest-asyncio>=0.23`,
  `fastapi>=0.111`, `uvicorn>=0.30`, `redis>=5.0.0`, `PyMySQL>=1.1.0`,
  `cryptography>=42.0.0`, `SQLAlchemy>=2.0.0`). Faixas permitem drift silencioso
  entre CI/dev/produção — indesejável num sistema financeiro. Pinar tudo com `==`
  (idealmente via lockfile: `pip-compile`/`pip freeze`) num PR próprio.

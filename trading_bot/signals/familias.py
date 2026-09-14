"""Famílias de estratégia para varredura comparativa.

Todas obedecem ao contrato `(df, ticker, **params) -> Optional[Candidate]` e
rodam sob a MESMA régua (`run_regime_backtest`): mesmo custo, mesmo benchmark,
mesma janela, mesmo filtro de liquidez, mesma contabilidade de caixa. Isolar a
família é o ponto — se cada uma tivesse seu próprio loop, diferença de
contabilidade viraria "alfa".

PARÂMETROS CANÔNICOS, NÃO OTIMIZADOS. Cada função documenta a fonte e o valor.
Otimizar aqui invalidaria a comparação: a família com mais graus de liberdade
venceria por overfit, não por mérito.

`df` chega com histórico até D-1 (o engine corta `ts < current_date`), então
usar a última barra é a informação disponível na decisão — sem look-ahead.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from trading_bot.signals.engine import Candidate


def _atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["h"].to_numpy(float), df["l"].to_numpy(float), df["adj_close"].to_numpy(float)
    if len(c) < n + 1:
        return float("nan")
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-n:]))


def _rsi(serie: np.ndarray, n: int) -> float:
    if len(serie) < n + 1:
        return float("nan")
    d = np.diff(serie[-(n + 1):])
    g, p = d[d > 0].sum(), -d[d < 0].sum()
    if p == 0:
        return 100.0
    rs = (g / n) / (p / n)
    return float(100 - 100 / (1 + rs))


def _cand(df, ticker, score, stop_mult, target_mult, **extra) -> Optional[Candidate]:
    """Monta o Candidate com stop/alvo em ATR — comum a todas as famílias, para
    que a diferença medida seja de SINAL e não de gestão de saída."""
    p = float(df["adj_close"].iloc[-1])
    a = _atr(df)
    if not np.isfinite(a) or a <= 0 or p <= 0:
        return None
    return Candidate(
        ticker=ticker, score=float(score), entry_price=p,
        stop=p - stop_mult * a, target=p + target_mult * a,
        signal_ts=df["ts"].iloc[-1], rsi=extra.get("rsi", 50.0),
        volume_ratio=extra.get("vr", 1.0), near_support=False,
        signal_details=extra,
    )


# ---------------------------------------------------------------------------
# REVERSÃO
# ---------------------------------------------------------------------------

def rsi2_connors(df, ticker, rsi_period=2, rsi_entry=10.0, sma_period=200,
                 stop_atr_mult=1.5, target_atr_mult=3.0, **kw):
    """RSI(2) sobrevendido com filtro SMA-200.

    CANÔNICO — Connors & Alvarez, *Short Term Trading Strategies That Work*
    (2008): RSI de 2 períodos, entrada abaixo de 10, apenas acima da SMA-200.
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < sma_period + rsi_period + 2:
        return None
    if c[-1] <= np.mean(c[-sma_period:]):
        return None
    r = _rsi(c, rsi_period)
    if not np.isfinite(r) or r > rsi_entry:
        return None
    return _cand(df, ticker, score=(rsi_entry - r), stop_mult=stop_atr_mult,
                 target_mult=target_atr_mult, rsi=r)


def bollinger_reversao(df, ticker, bb_period=20, bb_std=2.0, sma_period=200,
                       stop_atr_mult=1.5, target_atr_mult=3.0, **kw):
    """Toque na banda inferior de Bollinger, com filtro de tendência.

    CANÔNICO — Bollinger, *Bollinger on Bollinger Bands* (2001): 20 períodos,
    2 desvios-padrão. Filtro SMA-200 mantido para paridade com as demais.
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < max(sma_period, bb_period) + 2:
        return None
    if c[-1] <= np.mean(c[-sma_period:]):
        return None
    jan = c[-bb_period:]
    inferior = jan.mean() - bb_std * jan.std(ddof=0)
    if c[-1] > inferior:
        return None
    return _cand(df, ticker, score=(inferior - c[-1]) / max(jan.std(ddof=0), 1e-9),
                 stop_mult=stop_atr_mult, target_mult=target_atr_mult)


def reversao_curto_prazo(df, ticker, lookback=5, sma_period=200,
                         stop_atr_mult=1.5, target_atr_mult=3.0, **kw):
    """Pior retorno de 5 dias (reversão de curto prazo), acima da SMA-200.

    CANÔNICO — Jegadeesh (1990) e Lehmann (1990) documentam reversão em
    horizonte de 1 semana. O ranking entre tickers é feito pelo engine, que
    ordena por `score` — aqui o score é o negativo do retorno de 5 dias.
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < max(sma_period, lookback) + 2:
        return None
    if c[-1] <= np.mean(c[-sma_period:]):
        return None
    ret5 = c[-1] / c[-1 - lookback] - 1
    if ret5 >= 0:
        return None
    return _cand(df, ticker, score=-ret5, stop_mult=stop_atr_mult,
                 target_mult=target_atr_mult)


# ---------------------------------------------------------------------------
# MOMENTUM / TENDÊNCIA
# ---------------------------------------------------------------------------

def momentum_cross_sectional(df, ticker, lookback=252, skip=21,
                             stop_atr_mult=2.0, target_atr_mult=4.0, **kw):
    """Ranking por retorno 12m pulando o último mês; o engine pega o topo.

    CANÔNICO — Jegadeesh & Titman (1993); a convenção de pular o mês mais
    recente (12-1) vem de Fama & French (2012) e existe para evitar a reversão
    de curto prazo contaminar o sinal de momentum.
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < lookback + skip + 2:
        return None
    mom = c[-1 - skip] / c[-1 - skip - lookback] - 1
    if mom <= 0:
        return None
    return _cand(df, ticker, score=mom, stop_mult=stop_atr_mult,
                 target_mult=target_atr_mult)


def momentum_absoluto(df, ticker, lookback=252, stop_atr_mult=2.0,
                      target_atr_mult=4.0, **kw):
    """Time-series momentum: comprado só se o retorno de 12m for positivo.

    CANÔNICO — Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*;
    Antonacci (2014) usa a mesma janela de 12m.
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < lookback + 2:
        return None
    mom = c[-1] / c[-1 - lookback] - 1
    if mom <= 0:
        return None
    return _cand(df, ticker, score=mom, stop_mult=stop_atr_mult,
                 target_mult=target_atr_mult)


def cruzamento_medias(df, ticker, curta=50, longa=200, stop_atr_mult=2.0,
                      target_atr_mult=4.0, **kw):
    """Golden cross 50/200 — o baseline mais simples possível.

    CANÔNICO — 50/200 é a convenção de mercado há décadas. Entra no dia do
    cruzamento (a média curta cruza a longa para cima), não enquanto estiver
    acima, para não virar "sempre comprado".
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < longa + 2:
        return None
    s_hoje, l_hoje = np.mean(c[-curta:]), np.mean(c[-longa:])
    s_ontem, l_ontem = np.mean(c[-curta - 1:-1]), np.mean(c[-longa - 1:-1])
    if not (s_ontem <= l_ontem and s_hoje > l_hoje):
        return None
    return _cand(df, ticker, score=(s_hoje / l_hoje - 1), stop_mult=stop_atr_mult,
                 target_mult=target_atr_mult)


# ---------------------------------------------------------------------------
# VOLATILIDADE / REGIME
# ---------------------------------------------------------------------------

def squeeze_bollinger(df, ticker, bb_period=20, bb_std=2.0, squeeze_pct=0.25,
                      sma_period=200, stop_atr_mult=1.5, target_atr_mult=3.0, **kw):
    """Compressão de volatilidade seguida de rompimento.

    CANÔNICO — "Bollinger Squeeze" (Bollinger, 2001): largura de banda no
    quartil inferior (25%) do último ano, seguida de fechamento acima da banda
    superior.
    """
    c = df["adj_close"].to_numpy(float)
    if len(c) < max(sma_period, 252) + 2:
        return None
    if c[-1] <= np.mean(c[-sma_period:]):
        return None
    s = pd.Series(c)
    m = s.rolling(bb_period).mean()
    d = s.rolling(bb_period).std(ddof=0)
    largura = ((m + bb_std * d) - (m - bb_std * d)) / m
    hist = largura.iloc[-252:].dropna()
    if len(hist) < 100:
        return None
    # squeeze ONTEM (a compressão precede o rompimento)
    if largura.iloc[-2] > hist.quantile(squeeze_pct):
        return None
    if c[-1] <= (m.iloc[-1] + bb_std * d.iloc[-1]):
        return None
    return _cand(df, ticker, score=float(hist.quantile(squeeze_pct) - largura.iloc[-2]),
                 stop_mult=stop_atr_mult, target_mult=target_atr_mult)


def donchian_com_adx(df, ticker, breakout_period=20, adx_period=14, adx_min=25.0,
                     sma_period=200, stop_atr_mult=1.5, target_atr_mult=3.0, **kw):
    """Donchian só quando o ADX indica tendência estabelecida.

    CANÔNICO — Wilder (1978), *New Concepts in Technical Trading Systems*:
    ADX de 14 períodos, limiar de 25 para "tendência presente". É a hipótese
    de filtro de regime que o BACKLOG deixou registrada e nunca foi testada.
    """
    c = df["adj_close"].to_numpy(float)
    h, l = df["h"].to_numpy(float), df["l"].to_numpy(float)
    if len(c) < max(sma_period, breakout_period, adx_period * 3) + 2:
        return None
    if c[-1] <= np.mean(c[-sma_period:]):
        return None
    if c[-1] <= np.max(h[-1 - breakout_period:-1]):
        return None
    up, dn = h[1:] - h[:-1], l[:-1] - l[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    n = adx_period
    atr_ = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm).ewm(alpha=1 / n, adjust=False).mean() / atr_.replace(0, np.nan)
    ndi = 100 * pd.Series(ndm).ewm(alpha=1 / n, adjust=False).mean() / atr_.replace(0, np.nan)
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if not np.isfinite(adx) or adx < adx_min:
        return None
    return _cand(df, ticker, score=float(adx), stop_mult=stop_atr_mult,
                 target_mult=target_atr_mult)


FAMILIAS = {
    "rsi2_connors": rsi2_connors,
    "bollinger_reversao": bollinger_reversao,
    "reversao_5d": reversao_curto_prazo,
    "momentum_xs_12_1": momentum_cross_sectional,
    "momentum_absoluto": momentum_absoluto,
    "cruzamento_50_200": cruzamento_medias,
    "squeeze_bollinger": squeeze_bollinger,
    "donchian_adx": donchian_com_adx,
}

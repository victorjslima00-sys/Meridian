"""
Módulo 2 — Motor de Sinais v3 (Breakout + Filtro de Mercado IBOV)
=================================================================
Lições dos testes anteriores:
  - RSI(14) mean reversion em B3: win rate 28-35% → não bate Selic 10%
  - RSI(2) em B3: win rate 14-31% → pior (muito curto, muito ruído)
  - Alta_juros (IBOV -15%): qualquer sinal de compra falha sem filtro macro

Solução:
  1. Filtro macro IBOV (^BVSP > SMA-50): bloqueia trading em bear market
  2. Sinal de Breakout 20 dias (Donchian): compra quando ativo faz nova máxima
     com volume — win rate 38-48%, avg_win tipicamente > 2× avg_loss

Por que Breakout vs Mean Reversion?
  - Mean reversion (RSI oversold): compra na queda → exige timing fino → B3
    high-volatility → frequentemente continua caindo
  - Breakout: compra na FORÇA → ativo já mostrou poder de compra → maior
    probabilidade de follow-through → win rate menor mas R:R muito melhor
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Estrutura de saída (mantida para compatibilidade)
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    ticker: str
    score: float
    entry_price: float
    stop: float
    target: float
    signal_ts: date
    rsi: float
    volume_ratio: float
    near_support: bool
    signal_details: dict


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100.0)

def _volume_ratio(volume: pd.Series, ma_period: int = 20) -> float:
    if len(volume) < ma_period + 1:
        return 1.0
    avg = volume.iloc[-ma_period - 1:-1].mean()
    return float(volume.iloc[-1] / avg) if avg > 0 else 1.0


# ---------------------------------------------------------------------------
# Filtro de Mercado IBOV
# ---------------------------------------------------------------------------

_ibov_cache: dict[str, pd.DataFrame] = {}

def get_ibov_data(start: date) -> Optional[pd.DataFrame]:
    """
    Baixa dados do IBOVESPA (^BVSP) para o filtro macro.
    Cacheado em memória para evitar downloads repetidos.
    """
    key = str(start)
    if key in _ibov_cache:
        return _ibov_cache[key]
    try:
        import yfinance as yf
        df = yf.download("^BVSP", start=str(start), auto_adjust=True, progress=False)
        if df.empty:
            return None
        # Normalizar colunas (pode ser MultiIndex)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]
        df = df.reset_index()
        # Normalizar de novo para pegar a coluna de data gerada pelo reset_index
        df.columns = [str(c).lower() for c in df.columns]
        
        # O yfinance pode chamar de "date" ou "datetime" dependendo da versao
        if "datetime" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"datetime": "ts", "close": "c"})
        else:
            df = df.rename(columns={"date": "ts", "close": "c"})
            
        df["ts"] = pd.to_datetime(df["ts"]).dt.date
        df["sma50"] = _sma(df["c"], 50)
        _ibov_cache[key] = df
        logger.info("IBOV carregado: %d candles desde %s", len(df), start)
        return df
    except Exception as e:
        logger.warning("Falha ao carregar IBOV: %s", e)
        return None

def ibov_in_uptrend(ibov_df: Optional[pd.DataFrame], ref_date: date) -> bool:
    """
    Retorna True se o IBOV está acima da SMA-50 no dia de referência.
    Em caso de falha (sem dados), retorna True (não bloqueia por default).
    """
    if ibov_df is None:
        return True  # Sem dado → não bloquear
    row = ibov_df[ibov_df["ts"] <= ref_date]
    if row.empty:
        return True
    last = row.iloc[-1]
    c = float(last["c"])
    s = float(last["sma50"]) if not pd.isna(last["sma50"]) else None
    if s is None:
        return True
    return c > s


# ---------------------------------------------------------------------------
# Sinal principal: Breakout 20 dias (Donchian Channel)
# ---------------------------------------------------------------------------

def compute_signal(
    df: pd.DataFrame,
    ticker: str,
    breakout_period: int = 20,         # Período do canal Donchian
    volume_mult: float = 2.0,          # Volume > 2.0x média 20d
    sma_trend_period: int = 200,       # Filtro estrutural: preço > SMA-200
    rsi_max: float = 75.0,             # Não comprar se RSI > 75 (sobrecomprado)
    stop_atr_mult: float = 1.5,        # Stop = baixa do canal (ou ATR-based)
    stop_pct: float = 0.04,            # Stop mínimo (fallback)
    target_pct: float = 0.10,          # Target: 10%
) -> Optional[Candidate]:
    """
    Sinal de Breakout de 20 dias + Filtro SMA-200 + Volume.

    Regras de entrada (TODAS obrigatórias):
      1. Preço > SMA-200 (uptrend estrutural)
      2. Fechamento de hoje > máxima dos últimos 20 dias (breakout confirmado)
      3. Volume > 2.0× média 20d (confirmação de interesse institucional)
      4. RSI(14) entre 50 e 75 (momentum presente, não sobrecomprado)

    Stop: mínima dos últimos 10 dias (natural stop abaixo do pivot)
    Target: 10% (leva tempo, mas wins são grandes quando o breakout é real)

    R:R esperado: stop ~4-6% abaixo, target 10% → R:R de 2:1 a 3:1
    Win rate esperado: 38-48% → expectancy positiva contra Selic
    """
    min_rows = max(breakout_period + 1, sma_trend_period + 1, 22)
    if len(df) < min_rows:
        return None

    df = df.sort_values("ts").reset_index(drop=True)
    close = df["adj_close"]
    high  = df["h"]
    low   = df["l"]
    volume = df["v"]
    signal_date = df["ts"].iloc[-1]
    current_price = float(close.iloc[-1])

    # --- Filtro 1: SMA-200 ---
    sma200_val = float(_sma(close, sma_trend_period).iloc[-1])
    if pd.isna(sma200_val) or current_price < sma200_val:
        return None

    # --- Breakout: novo fechamento > máxima dos últimos N dias (excl. hoje) ---
    prev_highs = high.iloc[-(breakout_period + 1):-1]
    if len(prev_highs) < breakout_period:
        return None
    donchian_high = float(prev_highs.max())
    is_breakout = current_price > donchian_high

    if not is_breakout:
        return None

    # --- Filtro RSI: momentum mas não sobrecomprado ---
    rsi14 = float(_rsi(close, 14).iloc[-1])
    if pd.isna(rsi14) or rsi14 < 50 or rsi14 > rsi_max:
        return None

    # --- Confirmação de volume ---
    vol_ratio = _volume_ratio(volume)
    if vol_ratio < volume_mult:
        return None

    # --- Score ---
    breakout_strength = (current_price - donchian_high) / donchian_high  # % acima da resistência
    score = (
        0.40 * min(1.0, breakout_strength / 0.01)   # Força do breakout (0.4 máx)
        + 0.35                                       # Volume (agora obrigatório)
        + 0.25 * min(1.0, (current_price - sma200_val) / sma200_val / 0.10)  # Distância SMA-200
    )

    if score < 0.55:
        return None

    # --- Stop: usa o mais PRÓXIMO entre natural e % fixo (cap de risco) ---
    # Bug anterior: min() → stop mais longe → avg_loss > stop_pct
    # Correto: max() → stop mais próximo → cap avg_loss em stop_pct
    natural_stop = float(low.iloc[-10:].min())
    stop_from_pct = current_price * (1 - stop_pct)
    stop = max(natural_stop, stop_from_pct)   # tighter stop = less risk

    target = round(current_price * (1 + target_pct), 2)
    stop   = round(stop, 2)

    logger.info(
        "[%s] BREAKOUT | Score=%.2f | Preço=%.2f > Donchian=%.2f (+%.1f%%) | "
        "RSI14=%.1f | Vol=%.1fx | Stop=%.2f Alvo=%.2f",
        ticker, score, current_price, donchian_high,
        breakout_strength * 100, rsi14, vol_ratio, stop, target,
    )

    return Candidate(
        ticker=ticker,
        score=round(score, 4),
        entry_price=current_price,
        stop=stop,
        target=target,
        signal_ts=signal_date,
        rsi=round(rsi14, 2),
        volume_ratio=round(vol_ratio, 2),
        near_support=False,
        signal_details={
            "breakout_strength_pct": round(breakout_strength * 100, 3),
            "donchian_high": round(donchian_high, 2),
            "rsi14": round(rsi14, 2),
            "sma200": round(sma200_val, 2),
            "stop_pct_actual": round((current_price - stop) / current_price, 4),
            "target_pct": target_pct,
        },
    )


# ---------------------------------------------------------------------------
# Scan do universo
# ---------------------------------------------------------------------------

def scan_universe(
    data: dict[str, pd.DataFrame],
    ibov_df: Optional[pd.DataFrame] = None,
    ref_date: Optional[date] = None,
    **signal_kwargs,
) -> list[Candidate]:
    """
    Escaneia todos os ativos. Aplica filtro macro IBOV se ibov_df fornecido.
    """
    if ibov_df is not None and ref_date is not None:
        if not ibov_in_uptrend(ibov_df, ref_date):
            logger.info("IBOV abaixo da SMA-50 em %s — sem sinais (filtro macro)", ref_date)
            return []

    candidates = []
    for ticker, df in data.items():
        try:
            c = compute_signal(df, ticker, **signal_kwargs)
            if c:
                candidates.append(c)
        except Exception as e:
            logger.debug("[%s] Erro: %s", ticker, e)

    candidates.sort(key=lambda c: c.score, reverse=True)
    logger.info("Scan: %d candidatos de %d ativos", len(candidates), len(data))
    return candidates

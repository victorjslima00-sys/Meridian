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
from typing import Any, Optional

import numpy as np
import pandas as pd
from trading_bot.data.signal_input import validate_signal_input
from trading_bot.data.approval import require_data_approval

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

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()

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

def ibov_in_uptrend(
    ibov_df: Optional[pd.DataFrame],
    ref_date: date,
    current_market_date: Optional[date] = None,
) -> bool:
    """
    Retorna True se o IBOV está acima da SMA-50 no dia de referência (FECHADO).
    FAIL-CLOSED (NEXUS-004): Em caso de ausência de dados, dados insuficientes para SMA-50,
    barra parcial de hoje ou data futura, retorna False (bloqueia novas entradas autônomas).
    """
    if ibov_df is None or ibov_df.empty:
        logger.warning("Filtro macro: IBOV ausente ou vazio (fail-closed)")
        return False

    import math
    import datetime
    from backend.app.markets.b3_session import B3_TIMEZONE

    mkt_date = current_market_date
    if mkt_date is None:
        mkt_date = datetime.datetime.now(B3_TIMEZONE).date()

    # Barra em formação ou data futura não autoriza entrada
    if ref_date >= mkt_date:
        logger.warning(
            "Filtro macro: ref_date (%s) >= current_market_date (%s) — barra em formação/futura rejeitada",
            ref_date,
            mkt_date,
        )
        return False

    df = ibov_df.copy()
    if "ts" not in df.columns:
        if "date" in df.columns:
            df["ts"] = pd.to_datetime(df["date"]).dt.date
        elif isinstance(df.index, pd.DatetimeIndex):
            df["ts"] = df.index.date
        elif "datetime" in df.columns:
            df["ts"] = pd.to_datetime(df["datetime"]).dt.date
        else:
            logger.warning("Filtro macro: IBOV sem coluna ou índice temporal reconhecido (fail-closed)")
            return False
    else:
        df["ts"] = pd.to_datetime(df["ts"]).dt.date

    c_col = "c" if "c" in df.columns else ("close" if "close" in df.columns else None)
    if c_col is None:
        logger.warning("Filtro macro: IBOV sem coluna de fechamento (fail-closed)")
        return False

    if "sma50" not in df.columns:
        df["sma50"] = _sma(df[c_col], 50)

    # Filtra apenas barras fechadas anteriores à data do pregão
    closed_ibov = df[df["ts"] < mkt_date]
    if closed_ibov.empty:
        logger.warning("Filtro macro: sem barras IBOV fechadas anteriores a %s", mkt_date)
        return False

    row = closed_ibov[closed_ibov["ts"] <= ref_date]
    if row.empty:
        logger.warning("Filtro macro: sem histórico IBOV até ref_date %s", ref_date)
        return False

    last = row.iloc[-1]
    raw_c = last.get("c") if "c" in last else last.get("close")
    raw_s = last.get("sma50")

    if raw_c is None or isinstance(raw_c, bool):
        return False
    if raw_s is None or isinstance(raw_s, bool) or pd.isna(raw_s):
        return False

    try:
        c = float(raw_c)
        s = float(raw_s)
    except (TypeError, ValueError):
        return False

    if not math.isfinite(c) or not math.isfinite(s) or c <= 0 or s <= 0:
        return False

    return c > s


# ---------------------------------------------------------------------------
# Sinal principal: Breakout 20 dias (Donchian Channel)
# ---------------------------------------------------------------------------

def compute_signal(
    df: pd.DataFrame,
    ticker: str,
    breakout_period: int = 20,         # Período do canal Donchian
    volume_mult: float = 1.5,          # Volume > 1.5x média 20d (Aprovado pelo Guard-Rail)
    sma_trend_period: int = 200,       # Filtro estrutural: preço > SMA-200
    rsi_max: float = 75.0,             # Não comprar se RSI > 75 (sobrecomprado)
    stop_atr_mult: float = 2.0,        # Stop baseado no ATR
    stop_pct: float = 0.04,            # Stop de segurança (hard cap)
    target_atr_mult: float = 4.0,      # Target dinâmico (ATR * 4, R:R 1:2)
    registry_path: Any = None,
    project_root: Any = None,
    settings_path: Any = None,
    **kwargs,                          # Ignora argumentos adicionais para evitar TypeErrors
) -> Optional[Candidate]:
    """
    Sinal de Breakout de 20 dias + Filtro SMA-200 + Volume.
    """
    import math

    # Validação estrita fail-closed dos parâmetros
    for param_name, param_val in [
        ("breakout_period", breakout_period),
        ("volume_mult", volume_mult),
        ("sma_trend_period", sma_trend_period),
        ("rsi_max", rsi_max),
        ("stop_atr_mult", stop_atr_mult),
        ("stop_pct", stop_pct),
        ("target_atr_mult", target_atr_mult),
    ]:
        if param_val is None or isinstance(param_val, bool):
            logger.warning("[%s] Parâmetro %s inválido: %r (fail-closed)", ticker, param_name, param_val)
            return None
        try:
            val_f = float(param_val)
            if not math.isfinite(val_f) or val_f <= 0.0:
                logger.warning("[%s] Parâmetro %s não finito ou <= 0: %r", ticker, param_name, param_val)
                return None
        except (TypeError, ValueError):
            return None

    min_rows = max(int(breakout_period) + 1, int(sma_trend_period) + 1, 22)
    if len(df) < min_rows:
        return None

    try:
        validate_signal_input(df)
        approval_kwargs = {}
        if registry_path is not None:
            approval_kwargs["registry_path"] = registry_path
        if project_root is not None:
            approval_kwargs["project_root"] = project_root
        if settings_path is not None:
            approval_kwargs["settings_path"] = settings_path
        require_data_approval(df, ticker, **approval_kwargs)
    except ValueError:
        logger.warning("[%s] Histórico inválido ou sem aprovação; sinal bloqueado", ticker)
        return None
    df = df.reset_index(drop=True)
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

    # --- Volatilidade (ATR) ---
    atr_series = _atr(high, low, close, period=14)
    atr_val = float(atr_series.iloc[-1]) if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (current_price * 0.02)

    # --- Stop: usa o mais PRÓXIMO entre natural, ATR e % fixo (cap de risco do Guard-Rail) ---
    natural_stop = float(low.iloc[-10:].min())
    stop_from_atr = current_price - (atr_val * stop_atr_mult)
    stop_from_pct = current_price * (1 - stop_pct)
    
    # max() seleciona o maior valor (mais próximo do preço atual = menor risco financeiro)
    stop = max(natural_stop, stop_from_atr, stop_from_pct)

    # --- Alvo dinâmico via ATR (e indicação de Trailing Stop) ---
    target = round(current_price + (atr_val * target_atr_mult), 2)
    stop   = round(stop, 2)

    logger.info(
        "[%s] BREAKOUT | Score=%.2f | Preço=%.2f > Donchian=%.2f (+%.1f%%) | "
        "RSI14=%.1f | Vol=%.1fx | Stop=%.2f (ATR: %.2f) Alvo=%.2f",
        ticker, score, current_price, donchian_high,
        breakout_strength * 100, rsi14, vol_ratio, stop, atr_val, target,
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
            "atr14": round(atr_val, 2),
            "stop_pct_actual": round((current_price - stop) / current_price, 4),
            "trailing_stop_recommended": True,
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

"""
Módulo 1 — Ingestão de dados de mercado
========================================
Fontes:
  - brapi.dev   → candle diário corrente (plano grátis, interval=1d)
  - yfinance    → histórico para backtest (sufixo .SA para B3)

Confirmado empiricamente (2026-07-05):
  interval=60m → {"error":true,"message":"O intervalo '60m' não está disponível
                  no seu plano. Intervalos permitidos: 1d","code":"INVALID_INTERVAL"}
  interval=1d  → OK no plano grátis (15.000 req/mês)

Contrato de saída:
  DataFrame com colunas padronizadas: ticker, ts, o, h, l, c, v, adj_close
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import requests
import yaml
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Carregamento de configurações
# ---------------------------------------------------------------------------

def _load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _load_universe(path: str = "config/universe.yaml") -> list[str]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data["universe"]["tickers"]


# ---------------------------------------------------------------------------
# Normalização de schema
# ---------------------------------------------------------------------------

STANDARD_COLUMNS = ["ticker", "ts", "o", "h", "l", "c", "v", "adj_close"]


def _normalize(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Garante schema padronizado independente da fonte."""
    df = df.copy()
    df["ticker"] = ticker

    # Renomear colunas para o padrão interno
    rename_map = {
        "Open": "o", "High": "h", "Low": "l", "Close": "c",
        "Volume": "v", "Adj Close": "adj_close",
        "open": "o", "high": "h", "low": "l", "close": "c",
        "volume": "v", "adjustedClose": "adj_close",
    }
    df = df.rename(columns=rename_map)

    # Garantir coluna ts (timestamp normalizado para data)
    if df.index.name in ("Date", "Datetime", "date", "datetime", None):
        df = df.reset_index()
        date_col = next(
            (c for c in df.columns if "date" in c.lower() or "time" in c.lower()),
            None
        )
        if date_col:
            df["ts"] = pd.to_datetime(df[date_col]).dt.date
        else:
            raise ValueError(f"[{ticker}] Coluna de data não encontrada. Colunas: {df.columns.tolist()}")

    # Garantir que adj_close existe (fallback para close se não vier ajustado)
    if "adj_close" not in df.columns and "c" in df.columns:
        df["adj_close"] = df["c"]
        logger.warning("[%s] adj_close não disponível na fonte — usando close como fallback", ticker)

    # Selecionar apenas colunas do schema
    available = [col for col in STANDARD_COLUMNS if col in df.columns]
    missing = set(STANDARD_COLUMNS) - set(available)
    if missing:
        logger.warning("[%s] Colunas ausentes no schema: %s", ticker, missing)

    return df[available].dropna(subset=["ts", "c"])


# ---------------------------------------------------------------------------
# Fonte 1: yfinance (histórico para backtest)
# ---------------------------------------------------------------------------

def fetch_yfinance(
    ticker: str,
    start: date,
    end: Optional[date] = None,
    yf_suffix: str = ".SA",
) -> pd.DataFrame:
    """
    Busca histórico OHLCV via yfinance.
    Inclui preço ajustado por proventos (auto_adjust=True por padrão no yfinance).

    Args:
        ticker: Código B3 sem sufixo (ex: "PETR4")
        start:  Data de início
        end:    Data de fim (default: hoje)
        yf_suffix: Sufixo para B3 no Yahoo Finance (default: ".SA")
    """
    yf_ticker = ticker + yf_suffix
    from trading_bot.core.clock import today_b3
    end = end or today_b3()

    logger.info("[yfinance] Buscando %s de %s a %s", yf_ticker, start, end)
    try:
        df = yf.download(
            yf_ticker,
            start=str(start),
            end=str(end + timedelta(days=1)),
            progress=False,
            auto_adjust=True,   # Inclui ajuste por proventos
            actions=False,
        )
    except Exception as e:
        logger.error("[yfinance] Falha ao buscar %s: %s", yf_ticker, e)
        raise

    if df.empty:
        logger.warning("[yfinance] Nenhum dado retornado para %s", yf_ticker)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    # yfinance >= 0.2.40 pode retornar MultiIndex columns (Ticker, Price)
    # ao baixar um único ticker. Achatar para colunas simples.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    # com auto_adjust=True, "Close" já é o preço ajustado por proventos.
    # Duplicamos como "adj_close" antes de chamar _normalize, que vai renomear
    # "Close" → "c" via rename_map.
    if "Close" in df.columns:
        df["adj_close"] = df["Close"]

    return _normalize(df, ticker)


# ---------------------------------------------------------------------------
# Fonte 2: brapi.dev (candle diário corrente)
# ---------------------------------------------------------------------------

def fetch_brapi(
    ticker: str,
    token: str,
    base_url: str = "https://brapi.dev/api",
    max_retries: int = 3,
    backoff: float = 2.0,
) -> pd.DataFrame:
    """
    Busca candle diário mais recente via brapi.dev (plano grátis).
    Interval hardcoded em '1d' — único intervalo suportado no plano grátis.

    Args:
        ticker:    Código B3 (ex: "PETR4")
        token:     API token brapi.dev
        base_url:  Base URL da API
        max_retries: Tentativas em caso de erro
        backoff:   Segundos entre tentativas (exponencial)
    """
    url = f"{base_url}/quote/{ticker}"
    params = {
        "interval": "1d",   # Único intervalo disponível no plano grátis
        "range": "1d",
        "token": token,
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("error"):
                code = data.get("code", "")
                msg = data.get("message", "")
                if code == "INVALID_INTERVAL":
                    # Este erro nunca deve ocorrer (interval está hardcoded em 1d)
                    raise RuntimeError(
                        f"[brapi] INVALID_INTERVAL para {ticker}. "
                        "Verifique se o interval está em '1d'. Erro original: " + msg
                    )
                raise RuntimeError(f"[brapi] Erro da API para {ticker}: {msg} (code={code})")

            results = data.get("results", [])
            if not results:
                logger.warning("[brapi] Sem resultados para %s", ticker)
                return pd.DataFrame(columns=STANDARD_COLUMNS)

            quotes = results[0].get("historicalDataPrice", [])
            if not quotes:
                # Fallback: usar o preço atual como candle do dia
                r = results[0]
                quotes = [{
                    "date": int(datetime.now().timestamp()),
                    "open": r.get("regularMarketOpen"),
                    "high": r.get("regularMarketDayHigh"),
                    "low": r.get("regularMarketDayLow"),
                    "close": r.get("regularMarketPrice"),
                    "volume": r.get("regularMarketVolume"),
                    "adjustedClose": r.get("regularMarketPrice"),
                }]

            df = pd.DataFrame(quotes)
            df["ts"] = pd.to_datetime(df["date"], unit="s").dt.date

            return _normalize(df, ticker)

        except requests.RequestException as e:
            wait = backoff ** attempt
            logger.warning(
                "[brapi] Tentativa %d/%d falhou para %s: %s. Aguardando %.1fs",
                attempt, max_retries, ticker, e, wait
            )
            if attempt < max_retries:
                time.sleep(wait)
            else:
                logger.error("[brapi] Todas as tentativas falharam para %s", ticker)
                raise


# ---------------------------------------------------------------------------
# Interface principal: busca em lote para o universo de ativos
# ---------------------------------------------------------------------------

def fetch_universe_yfinance(
    tickers: list[str],
    start: date,
    end: Optional[date] = None,
    yf_suffix: str = ".SA",
) -> dict[str, pd.DataFrame]:
    """
    Busca histórico completo de todos os ativos do universo via yfinance.
    Usado principalmente para backtest.

    Returns:
        Dict {ticker: DataFrame} com schema padronizado
    """
    results: dict[str, pd.DataFrame] = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.info("[%d/%d] Buscando histórico: %s", i, total, ticker)
        try:
            df = fetch_yfinance(ticker, start=start, end=end, yf_suffix=yf_suffix)
            if not df.empty:
                results[ticker] = df
            else:
                logger.warning("[%s] Sem dados no período solicitado", ticker)
        except Exception as e:
            logger.error("[%s] Falha ao buscar yfinance: %s", ticker, e)

        # Pequeno delay para não sobrecarregar o yfinance
        time.sleep(0.2)

    logger.info("Fetch concluído: %d/%d ativos com dados", len(results), total)
    return results


def fetch_universe_brapi(
    tickers: list[str],
    token: str,
    base_url: str = "https://brapi.dev/api",
) -> dict[str, pd.DataFrame]:
    """
    Busca candle diário corrente de todos os ativos via brapi.dev.
    Estimativa de consumo: ~50 req/dia × 22 dias = ~1.100 req/mês (de 15.000 disponíveis).

    Returns:
        Dict {ticker: DataFrame} com schema padronizado
    """
    results: dict[str, pd.DataFrame] = {}
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.info("[%d/%d] Buscando candle diário brapi: %s", i, total, ticker)
        try:
            df = fetch_brapi(ticker, token=token, base_url=base_url)
            if not df.empty:
                results[ticker] = df
        except Exception as e:
            logger.error("[%s] Falha ao buscar brapi: %s", ticker, e)

        # Rate limiting: ~1 req/segundo para margem segura
        time.sleep(1.0)

    logger.info("Fetch brapi concluído: %d/%d ativos com dados", len(results), total)
    return results

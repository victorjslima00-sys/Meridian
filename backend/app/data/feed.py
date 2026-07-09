import time
import logging
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# Crypto tickers que não precisam do sufixo .SA
_CRYPTO_TICKERS = {"BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "ADA-USD"}
_PASSTHROUGH_TICKERS = {"^BVSP", "BRL=X", "SPY", "QQQ"}


def _normalize_ticker(ticker: str) -> str:
    """Adiciona sufixo .SA para ações B3 quando necessário."""
    if ticker in _CRYPTO_TICKERS or ticker in _PASSTHROUGH_TICKERS:
        return ticker
    if not ticker.endswith(".SA") and len(ticker) >= 4 and ticker[-1].isdigit():
        return f"{ticker}.SA"
    return ticker


def fetch_recent_data(
    ticker: str, period: str = "5d", interval: str = "1h", max_retries: int = 3
):
    """
    Busca dados OHLCV recentes usando yfinance.
    Inclui retry com backoff exponencial para tolerância a falhas de rede.

    Args:
        ticker:      Ticker do ativo (ex: "BTC-USD", "PETR4")
        period:      Período de histórico (ex: "5d", "1mo")
        interval:    Intervalo dos candles (ex: "15m", "1h", "1d")
        max_retries: Número máximo de tentativas antes de desistir

    Returns:
        DataFrame normalizado ou None em caso de falha total.
    """
    normalized = _normalize_ticker(ticker)

    for attempt in range(max_retries):
        try:
            df = yf.download(
                normalized,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )

            if df is None or df.empty:
                logger.warning(
                    "[%s] Dados vazios (tentativa %d/%d)",
                    normalized,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                continue

            # Normalizar índice e colunas
            df.reset_index(inplace=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.rename(columns={"Datetime": "date", "Date": "date"}, inplace=True)
            df.columns = [c.lower() for c in df.columns]

            logger.debug(
                "[%s] %d candles carregados (period=%s interval=%s)",
                normalized,
                len(df),
                period,
                interval,
            )
            return df

        except Exception as e:
            wait = 2**attempt
            logger.warning(
                "[%s] Erro na tentativa %d/%d: %s. Aguardando %ds...",
                normalized,
                attempt + 1,
                max_retries,
                e,
                wait,
            )
            if attempt < max_retries - 1:
                time.sleep(wait)

    logger.error("[%s] Falha total após %d tentativas.", normalized, max_retries)
    return None


def get_current_price(ticker: str) -> float:
    """Retorna o preço mais recente do ativo. Retorna 0.0 em caso de falha."""
    df = fetch_recent_data(ticker, period="1d", interval="1m")
    if df is not None and not df.empty:
        return float(df.iloc[-1]["close"])
    return 0.0

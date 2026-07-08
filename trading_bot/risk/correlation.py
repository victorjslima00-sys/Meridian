import pandas as pd
from trading_bot.data.storage import load_ohlcv
from datetime import date

def build_returns_matrix(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, list[float]]:
    """
    Constrói a matriz de retornos diários (% change) de uma lista de tickers,
    buscando os dados do storage.
    Retorna: {ticker: [retornos diarios...]}
    """
    returns_matrix = {}
    for ticker in tickers:
        df = load_ohlcv(ticker, start=start, end=end)
        if df.empty or len(df) < 2:
            returns_matrix[ticker] = []
            continue
            
        adj_col = "adj_close" if "adj_close" in df.columns else "c"
        returns = df[adj_col].pct_change().dropna().tolist()
        returns_matrix[ticker] = returns
        
    return returns_matrix

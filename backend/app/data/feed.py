import yfinance as yf
import pandas as pd

def fetch_recent_data(ticker: str, period="5d", interval="1h"):
    """
    Fetches recent OHLCV data for a ticker using yfinance.
    Useful for feeding the Market Analyst Agent.
    """
    try:
        # For B3 stocks, yfinance expects .SA
        if not ticker.endswith(".SA") and ticker not in ["^BVSP", "BRL=X", "SPY", "QQQ"]:
            # If it's a typical 4-letter + number B3 ticker, append .SA
            if len(ticker) >= 4 and ticker[-1].isdigit():
                ticker = f"{ticker}.SA"
                
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df.empty:
            return None
            
        # Format the dataframe for our agents
        df.reset_index(inplace=True)
        # Handle MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        
        # Rename 'Datetime' or 'Date' to 'date'
        df.rename(columns={"Datetime": "date", "Date": "date"}, inplace=True)
        # Lowercase columns
        df.columns = [c.lower() for c in df.columns]
        
        return df
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None

def get_current_price(ticker: str) -> float:
    df = fetch_recent_data(ticker, period="1d", interval="1m")
    if df is not None and not df.empty:
        return float(df.iloc[-1]['close'])
    return 0.0

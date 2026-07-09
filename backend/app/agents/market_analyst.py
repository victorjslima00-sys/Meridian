import pandas as pd
from typing import Dict, Any
from ..data.feed import fetch_recent_data

class MarketAnalyst:
    def __init__(self, ticker: str):
        self.ticker = ticker
        
    def analyze(self) -> Dict[str, Any]:
        """
        Analyzes the market using simple moving averages and RSI.
        Returns a recommendation (BUY, SELL, HOLD).
        """
        df = fetch_recent_data(self.ticker, period="60d", interval="1d")
        if df is None or len(df) < 20:
            return {"signal": "HOLD", "reason": "Insufficient data"}
            
        # Calculate Simple Moving Averages
        df['sma_10'] = df['close'].rolling(window=10).mean()
        df['sma_20'] = df['close'].rolling(window=20).mean()
        
        # Latest values
        last_close = df.iloc[-1]['close']
        last_sma10 = df.iloc[-1]['sma_10']
        last_sma20 = df.iloc[-1]['sma_20']
        
        signal = "HOLD"
        reason = "Market is ranging."
        
        if last_sma10 > last_sma20 and last_close > last_sma10:
            signal = "BUY"
            reason = f"Uptrend detected. Price ({last_close:.2f}) is above SMA10 and SMA10 > SMA20."
        elif last_sma10 < last_sma20 and last_close < last_sma10:
            signal = "SELL"
            reason = f"Downtrend detected. Price ({last_close:.2f}) is below SMA10 and SMA10 < SMA20."
            
        return {
            "signal": signal,
            "reason": reason,
            "last_price": float(last_close),
            "sma_10": float(last_sma10),
            "sma_20": float(last_sma20)
        }

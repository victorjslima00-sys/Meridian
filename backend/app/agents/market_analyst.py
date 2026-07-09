import pandas as pd
from typing import Dict, Any
import json
import logging
from ..data.feed import fetch_recent_data
from trading_bot.core.llm_client import ResilientLLMClient

logger = logging.getLogger(__name__)

class MarketAnalyst:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.llm_client = ResilientLLMClient()
        
    async def analyze(self) -> Dict[str, Any]:
        """
        Analyzes the market using technical indicators and Gemini AI.
        Returns a recommendation (BUY, SELL, HOLD).
        """
        # GAP 3 Fix: Use 15m interval to justify the aggressive 60s loop scan
        df = fetch_recent_data(self.ticker, period="5d", interval="15m")
        if df is None or len(df) < 20:
            return {"signal": "HOLD", "reason": "Insufficient data"}
            
        # Calculate Simple Moving Averages
        df['sma_10'] = df['close'].rolling(window=10).mean()
        df['sma_20'] = df['close'].rolling(window=20).mean()
        
        # Latest values
        last_close = df.iloc[-1]['close']
        last_sma10 = df.iloc[-1]['sma_10']
        last_sma20 = df.iloc[-1]['sma_20']
        
        # Baseline trend check
        trend = "Ranging"
        if last_sma10 > last_sma20 and last_close > last_sma10:
            trend = "Uptrend"
        elif last_sma10 < last_sma20 and last_close < last_sma10:
            trend = "Downtrend"
            
        # GAP 2 Fix: Call Gemini for actual AI analysis
        prompt = f"""
        Você é o Market Analyst (Especialista em Cripto e Ações) do fundo quantitativo Meridian.
        Sua tarefa é analisar o ticker {self.ticker} no tempo gráfico de 15 minutos (intraday) e 
        retornar sua recomendação de trading estritamente em formato JSON.

        DADOS ATUAIS (Fechamento mais recente):
        - Preço de Fechamento: {last_close:.2f}
        - SMA 10 (Rápida): {last_sma10:.2f}
        - SMA 20 (Lenta): {last_sma20:.2f}
        - Tendência Matemática: {trend}

        REGRA DE DECISÃO:
        Se Uptrend claro com preço acima das médias, você pode considerar BUY.
        Se Downtrend claro com preço abaixo das médias, você pode considerar SELL.
        Se a diferença for muito apertada ou sem direção, vote HOLD.

        INSTRUÇÃO DE SAÍDA:
        Responda APENAS com um JSON puro contendo as chaves:
        "signal": (deve ser "BUY", "SELL" ou "HOLD")
        "reason": (um texto de no máximo 15 palavras explicando o racional)
        """
        
        signal = "HOLD"
        reason = "Awaiting LLM..."
        
        llm_response = await self.llm_client.generate_text_async(prompt)
        
        if llm_response and llm_response.content:
            try:
                content = llm_response.content.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(content)
                signal = parsed.get("signal", "HOLD").upper()
                if signal not in ["BUY", "SELL", "HOLD"]:
                    signal = "HOLD"
                reason = parsed.get("reason", f"Gemini analyzed. Trend: {trend}")
            except Exception as e:
                logger.warning(f"Failed to parse LLM response for {self.ticker}: {e}. Falling back to basic math.")
                signal = "BUY" if trend == "Uptrend" else "SELL" if trend == "Downtrend" else "HOLD"
                reason = f"Fallback math logic. Trend: {trend}"
        else:
            signal = "BUY" if trend == "Uptrend" else "SELL" if trend == "Downtrend" else "HOLD"
            reason = f"Fallback math logic (LLM Failed). Trend: {trend}"
            
        return {
            "signal": signal,
            "reason": reason,
            "last_price": float(last_close),
            "sma_10": float(last_sma10),
            "sma_20": float(last_sma20)
        }

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

        # Calculate Simple Moving Averages and Volatility
        df["sma_10"] = df["close"].rolling(window=10).mean()
        df["sma_20"] = df["close"].rolling(window=20).mean()
        df["std_dev"] = df["close"].rolling(window=20).std()

        # Latest values
        last_close = df.iloc[-1]["close"]
        last_sma10 = df.iloc[-1]["sma_10"]
        last_sma20 = df.iloc[-1]["sma_20"]
        last_std = df.iloc[-1]["std_dev"]

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
        - Volatilidade (Desvio Padrão 20p): {last_std:.2f}
        - Tendência Matemática: {trend}

        REGRA DE DECISÃO:
        Se Uptrend claro com preço acima das médias, considere BUY.
        Se Downtrend claro com preço abaixo das médias, considere SELL.
        Se a diferença for muito apertada ou sem direção, vote HOLD.

        ALVOS E RISCOS:
        Caso decida por BUY ou SELL, defina um `target_price` e `stop_loss` usando a volatilidade atual 
        para criar uma operação assimétrica inteligente (ex: ganhar mais que a volatilidade e perder menos).
        Defina também seu nível de "confidence" como um número inteiro de 1 a 100.

        INSTRUÇÃO DE SAÍDA:
        Responda APENAS com um JSON puro contendo as exatas chaves:
        "signal": (deve ser "BUY", "SELL" ou "HOLD")
        "confidence": (inteiro de 1 a 100, 0 se HOLD)
        "target_price": (float numérico, 0 se HOLD)
        "stop_loss": (float numérico, 0 se HOLD)
        "reason": (texto sucinto de no máximo 20 palavras explicando a tese)
        """

        signal = "HOLD"
        reason = "Awaiting LLM..."
        confidence = 0
        target_price = 0.0
        stop_loss = 0.0

        llm_response = await self.llm_client.generate_text_async(prompt)

        if llm_response and llm_response.content:
            try:
                content = (
                    llm_response.content.replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
                parsed = json.loads(content)
                signal = parsed.get("signal", "HOLD").upper()
                if signal not in ["BUY", "SELL", "HOLD"]:
                    signal = "HOLD"
                confidence = int(parsed.get("confidence", 50))
                target_price = float(parsed.get("target_price", 0.0))
                stop_loss = float(parsed.get("stop_loss", 0.0))
                reason = parsed.get("reason", f"Gemini analyzed. Trend: {trend}")
            except Exception as e:
                logger.warning(
                    f"Failed to parse LLM response for {self.ticker}: {e}. Falling back to basic math."
                )
                try:
                    import sys; from pathlib import Path
                    root = Path(__file__).resolve().parent.parent.parent.parent.parent
                    if str(root) not in sys.path: sys.path.append(str(root))
                    from trading_bot.core.telegram import TelegramClient
                    TelegramClient().send_message(f"⚠️ [MarketAnalyst] LLM Parse Fallback acionado para {self.ticker}. Resposta inválida da IA.")
                except Exception:
                    pass
                signal = (
                    "BUY"
                    if trend == "Uptrend"
                    else "SELL" if trend == "Downtrend" else "HOLD"
                )
                reason = f"Fallback math logic. Trend: {trend}"
                confidence = 55
                if signal == "BUY":
                    target_price = last_close + (last_std * 3)
                    stop_loss = last_close - (last_std * 1.5)
                elif signal == "SELL":
                    target_price = last_close - (last_std * 3)
                    stop_loss = last_close + (last_std * 1.5)
        else:
            try:
                import sys; from pathlib import Path
                root = Path(__file__).resolve().parent.parent.parent.parent.parent
                if str(root) not in sys.path: sys.path.append(str(root))
                from trading_bot.core.telegram import TelegramClient
                TelegramClient().send_message(f"⚠️ [MarketAnalyst] LLM Offline Fallback acionado para {self.ticker}. IA não respondeu.")
            except Exception:
                pass
            signal = (
                "BUY"
                if trend == "Uptrend"
                else "SELL" if trend == "Downtrend" else "HOLD"
            )
            reason = f"Fallback math logic (LLM Failed). Trend: {trend}"
            confidence = 55
            if signal == "BUY":
                target_price = last_close + (last_std * 3)
                stop_loss = last_close - (last_std * 1.5)
            elif signal == "SELL":
                target_price = last_close - (last_std * 3)
                stop_loss = last_close + (last_std * 1.5)

        return {
            "signal": signal,
            "confidence": confidence,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "reason": reason,
            "last_price": float(last_close),
            "sma_10": float(last_sma10),
            "sma_20": float(last_sma20),
            "std_dev": float(last_std),
        }

from typing import Dict, Any, List

# Grupos de ativos altamente correlacionados.
# Dentro de um grupo, apenas 1 posição aberta é permitida de cada vez.
CORRELATED_GROUPS: List[List[str]] = [
    ["BTC-USD", "ETH-USD"],  # Crypto major → correlação 90%+
]


class RiskManager:
    def __init__(self, saldo_livre: float):
        self.saldo_livre = saldo_livre

    def _is_correlated_with_open(self, ticker: str, open_tickers: List[str]) -> bool:
        """Verifica se o ticker está no mesmo grupo de correlação de algum ativo aberto."""
        for group in CORRELATED_GROUPS:
            if ticker in group:
                for open_t in open_tickers:
                    if open_t in group and open_t != ticker:
                        return True
        return False

    def calculate_position_size(
        self, confidence: float, win_loss_ratio: float
    ) -> float:
        """
        Uses dynamic Kelly Criterion based on AI confidence and trade asymmetry.
        Maximum allocation limit bumped to 10% for extremely high conviction trades.
        """
        win_rate = max(0.01, min(0.99, confidence / 100.0))

        if win_loss_ratio <= 0:
            win_loss_ratio = 1.0

        kelly_pct = win_rate - ((1.0 - win_rate) / win_loss_ratio)

        # Max risk allowed is 10% for exceptional opportunities
        safe_kelly = min(kelly_pct * 0.5, 0.10)

        if safe_kelly < 0:
            return 0.0
        return self.saldo_livre * safe_kelly

    def evaluate_trade(
        self,
        analyst_signal: Dict[str, Any],
        ticker: str = "",
        open_tickers: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Avalia o sinal do analista e decide se deve executar.
        Inclui checagem de correlação entre ativos.
        """
        if open_tickers is None:
            open_tickers = []

        if analyst_signal["signal"] == "HOLD":
            return {"approved": False, "reason": "Analyst recommends HOLD."}

        # GAP 3 Fix: Bloquear ativos altamente correlacionados
        if ticker and self._is_correlated_with_open(ticker, open_tickers):
            correlated = [
                t
                for t in open_tickers
                if any(t in g and ticker in g for g in CORRELATED_GROUPS)
            ]
            return {
                "approved": False,
                "reason": (
                    f"Risco de correlação: {ticker} está no mesmo grupo de correlação "
                    f"que {correlated}. Apenas 1 ativo por grupo é permitido."
                ),
            }

        current_price = analyst_signal.get("last_price", 0.0)
        target_price = analyst_signal.get("target_price", 0.0)
        stop_loss = analyst_signal.get("stop_loss", 0.0)
        confidence = analyst_signal.get("confidence", 50)

        if current_price <= 0 or target_price <= 0 or stop_loss <= 0:
            return {
                "approved": False,
                "reason": "Risk Manager veto: Invalid price targets.",
            }

        # Calculate Reward and Risk distances
        if analyst_signal["signal"] == "BUY":
            reward = target_price - current_price
            risk = current_price - stop_loss
        else:  # SELL
            reward = current_price - target_price
            risk = stop_loss - current_price

        if risk <= 0 or reward <= 0:
            return {
                "approved": False,
                "reason": "Risk Manager veto: Trade direction inverted or illogical targets.",
            }

        win_loss_ratio = reward / risk

        pos_size = self.calculate_position_size(confidence, win_loss_ratio)
        if pos_size <= 0:
            return {
                "approved": False,
                "reason": f"Kelly criterion veto (Conf: {confidence}%, R:R {win_loss_ratio:.2f}).",
            }

        return {
            "approved": True,
            "allocated_capital": pos_size,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "reason": f"Aprovado. Risco:Retorno {win_loss_ratio:.2f} | Confiança {confidence}%. Alocando R$ {pos_size:.2f} (Max 10%).",
        }

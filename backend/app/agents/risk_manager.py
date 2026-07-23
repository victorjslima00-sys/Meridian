from typing import Dict, Any, List

# Grupos de ativos altamente correlacionados.
# Dentro de um grupo, apenas 1 posição aberta é permitida de cada vez.
CORRELATED_GROUPS: List[List[str]] = [
    ["BTC-USD", "ETH-USD"],  # Crypto major → correlação 90%+
]


class RiskManager:
    def __init__(self, saldo_livre: float, config=None, em_posicoes: float = 0.0):
        """
        saldo_livre  = capital_cash (dinheiro fora de posições) — o teto de
                       alocação, o bot nunca aloca mais que o cash livre.
        em_posicoes  = open_positions_capital (capital já em posições). Junto
                       com saldo_livre forma o total_equity que o Kelly do
                       backtest usa. Default 0.0 preserva chamadas antigas.
        """
        from ..runtime_config import RuntimeConfig
        self.saldo_livre = saldo_livre
        self.em_posicoes = em_posicoes
        self.config = config or RuntimeConfig.load()

    def _is_correlated_with_open(self, ticker: str, open_tickers: List[str]) -> bool:
        """Verifica se o ticker está no mesmo grupo de correlação de algum ativo aberto."""
        for group in CORRELATED_GROUPS:
            if ticker in group:
                for open_t in open_tickers:
                    if open_t in group and open_t != ticker:
                        return True
        return False

    # (Fase 1 Commit 2) O antigo calculate_position_size — Kelly derivado da
    # CONFIANÇA do LLM, com teto max_position_fraction — foi REMOVIDO: não era
    # o dimensionamento backtestado. evaluate_trade agora chama a função
    # compartilhada trading_bot.risk.position_sizing.calculate_position_size,
    # a MESMA do backtest (Kelly fixo do equity, teto no cash).

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

        if len(open_tickers) >= self.config.max_positions:
            return {
                "approved": False,
                "reason": f"Limite de {self.config.max_positions} posições atingido.",
            }

        if analyst_signal["signal"] == "HOLD":
            return {"approved": False, "reason": "Analyst recommends HOLD."}

        # Check Global Circuit Breaker — FAIL-CLOSED: qualquer erro bloqueia a entrada
        import sys
        from pathlib import Path
        try:
            root_path = Path(__file__).resolve().parent.parent.parent.parent.parent
            if str(root_path) not in sys.path:
                sys.path.append(str(root_path))
            from trading_bot.risk.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker.from_config()
            if not cb.can_trade():
                return {"approved": False, "reason": "Circuit Breaker ativado (proteção global acionada)."}
        except Exception as e:
            return {
                "approved": False,
                "reason": f"Circuit Breaker indisponível ({e}) — entrada bloqueada (fail-closed).",
            }

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

        # Calculate Reward and Risk distances. A checagem de direção
        # inválida/alvos ilógicos que existia aqui (risk<=0 or reward<=0)
        # foi removida (dashboard-depth Track A): AnalystDecision
        # (backend/app/agents/schemas.py) já garante, via Pydantic, que
        # stop_loss < preço < target_price em BUY (invertido em SELL)
        # ANTES de qualquer sinal chegar aqui — reward e risk são
        # matematicamente positivos por construção quando signal != HOLD.
        if analyst_signal["signal"] == "BUY":
            reward = target_price - current_price
            risk = current_price - stop_loss
        else:  # SELL
            reward = current_price - target_price
            risk = stop_loss - current_price

        win_loss_ratio = reward / risk

        # Fase 1 Commit 2: DIMENSIONAMENTO alinhado ao backtest. Antes usava
        # um Kelly derivado da CONFIANÇA (self.calculate_position_size), que
        # NÃO é o que foi backtestado. Agora chama a MESMA função que o
        # backtest usa (trading_bot.risk.position_sizing.calculate_position_size):
        # Kelly FIXO (kelly_fraction), sobre o total_equity (cash + posições),
        # com teto no cash e no número de posições. Rodar ao vivo exatamente o
        # que foi validado, sizing incluído. win_loss_ratio segue só no texto
        # de log (não dimensiona mais).
        from trading_bot.risk.position_sizing import calculate_position_size

        pos_size = calculate_position_size(
            capital_cash=self.saldo_livre,
            open_positions_capital=self.em_posicoes,
            kelly_fraction=self.config.kelly_fraction,
            max_positions=self.config.max_positions,
            current_open_count=len(open_tickers),
        )
        if pos_size <= 0:
            return {
                "approved": False,
                "reason": (
                    f"Sizing veto: alocação zero (cash R$ {self.saldo_livre:.2f}, "
                    f"posições {len(open_tickers)}/{self.config.max_positions})."
                ),
            }

        return {
            "approved": True,
            "allocated_capital": pos_size,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "reason": (
                f"Aprovado (Donchian). Risco:Retorno {win_loss_ratio:.2f} | "
                f"Kelly {self.config.kelly_fraction} do equity. "
                f"Alocando R$ {pos_size:.2f}."
            ),
        }

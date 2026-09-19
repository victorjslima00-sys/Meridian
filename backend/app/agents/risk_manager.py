from typing import Dict, Any, List

# Grupos de ativos altamente correlacionados.
# Dentro de um grupo, apenas 1 posição aberta é permitida de cada vez.
CORRELATED_GROUPS: List[List[str]] = [
    ["BTC-USD", "ETH-USD"],  # Crypto major → correlação 90%+
]


from trading_bot.risk.position_sizing import _UNSET


class RiskManager:
    def __init__(
        self,
        saldo_livre: float,
        config=None,
        em_posicoes: float = 0.0,
        reference_equity: Any = _UNSET,
        *,
        validation_context=None
    ):
        """
        saldo_livre      = capital_cash (dinheiro fora de posições) — base de
                           alocação operável.
        em_posicoes      = open_positions_capital (capital já em posições).
        reference_equity = Referência canônica de equity (NEXUS-005-C1).
        """
        from ..runtime_config import RuntimeConfig
        from copy import deepcopy
        from .contracts import approval_lookup_context
        approval_lookup_context(validation_context)
        self._validation_context = deepcopy(validation_context)
        self.saldo_livre = saldo_livre
        self.em_posicoes = em_posicoes
        self.reference_equity = reference_equity
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
        analyst_signal: Any,
        ticker: str = "",
        open_tickers: List[str] = None,
    ) -> Any:  # Will return RiskDecision
        from backend.app.agents.contracts import RiskDecision, TypedSignal
        from datetime import datetime, timezone

        if open_tickers is None:
            open_tickers = []

        try:
            if isinstance(analyst_signal, dict):
                analyst_signal_dict = dict(analyst_signal)
                if "ticker" not in analyst_signal_dict and ticker:
                    analyst_signal_dict["ticker"] = ticker
                signal = TypedSignal.model_validate(analyst_signal_dict, context=self._validation_context)
            elif isinstance(analyst_signal, TypedSignal):
                signal = TypedSignal.model_validate(
                    analyst_signal.model_dump(mode="python"), context=self._validation_context
                )
            else:
                raise ValueError("Invalid signal type")
        except Exception as e:
            return RiskDecision(
                signal_id="invalid",
                approved=False,
                reason=f"Risk Manager veto: Invalid strategy signal - {str(e)}",
                target_price=1.0,
                stop_loss=1.0,
                decision_timestamp=datetime.now(timezone.utc),
            )

        _ticker = signal.ticker
        if ticker and ticker != _ticker:
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason="Ticker mismatch",
                target_price=signal.target_price,
                stop_loss=signal.stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        if len(open_tickers) >= self.config.max_positions:
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason=f"Limite de {self.config.max_positions} posições atingido.",
                target_price=signal.target_price,
                stop_loss=signal.stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        if signal.side == "HOLD":
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason="Analyst recommends HOLD.",
                target_price=signal.target_price,
                stop_loss=signal.stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        import sys
        from pathlib import Path
        try:
            root_path = Path(__file__).resolve().parent.parent.parent.parent.parent
            if str(root_path) not in sys.path:
                sys.path.append(str(root_path))
            from trading_bot.risk.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker.from_config()
            if not cb.can_trade():
                return RiskDecision(
                    signal_id=signal.signal_id,
                    approved=False,
                    reason="Circuit Breaker ativado (proteção global acionada).",
                    target_price=signal.target_price,
                    stop_loss=signal.stop_loss,
                    decision_timestamp=datetime.now(timezone.utc),
                )
        except Exception as e:
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason=f"Circuit Breaker indisponível ({e}) — entrada bloqueada (fail-closed).",
                target_price=signal.target_price,
                stop_loss=signal.stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        if _ticker and self._is_correlated_with_open(_ticker, open_tickers):
            correlated = [
                t for t in open_tickers
                if any(t in g and _ticker in g for g in CORRELATED_GROUPS)
            ]
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason=(f"Risco de correlação: {_ticker} está no mesmo grupo de correlação "
                        f"que {correlated}. Apenas 1 ativo por grupo é permitido."),
                target_price=signal.target_price,
                stop_loss=signal.stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        current_price = signal.price
        target_price = signal.target_price
        stop_loss = signal.stop_loss
        confidence = signal.confidence or 50

        if signal.side == "BUY":
            reward = target_price - current_price
            risk = current_price - stop_loss
        elif signal.side == "SELL":
            reward = current_price - target_price
            risk = stop_loss - current_price
        else:
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason=f"Unknown signal side: {signal.side}",
                target_price=target_price,
                stop_loss=stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )
        win_loss_ratio = reward / risk if risk > 0 else 0

        from trading_bot.risk.position_sizing import calculate_position_size
        try:
            sizing_kwargs = {
                "capital_cash": self.saldo_livre,
                "open_positions_capital": self.em_posicoes,
                "kelly_fraction": self.config.kelly_fraction,
                "max_positions": self.config.max_positions,
                "current_open_count": len(open_tickers),
                "max_position_fraction": self.config.max_position_fraction,
            }
            if self.reference_equity is not _UNSET:
                sizing_kwargs["reference_equity"] = self.reference_equity

            pos_size = calculate_position_size(**sizing_kwargs)
        except Exception as e:
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason=f"Sizing veto: fail closed ({e})",
                target_price=target_price,
                stop_loss=stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        if pos_size <= 0:
            return RiskDecision(
                signal_id=signal.signal_id,
                approved=False,
                reason=f"Sizing veto: alocação zero (cash R$ {self.saldo_livre:.2f}, posições {len(open_tickers)}/{self.config.max_positions}).",
                target_price=target_price,
                stop_loss=stop_loss,
                decision_timestamp=datetime.now(timezone.utc),
            )

        return RiskDecision(
            signal_id=signal.signal_id,
            approved=True,
            allocated_capital=pos_size,
            target_price=target_price,
            stop_loss=stop_loss,
            decision_timestamp=datetime.now(timezone.utc),
            reason=(
                f"Aprovado (Donchian). Risco:Retorno {win_loss_ratio:.2f} | "
                f"Kelly {self.config.kelly_fraction:.0%} | "
                f"MaxPosFrac {self.config.max_position_fraction:.0%}. "
                f"Alocando R$ {pos_size:.2f}."
            ),
        )


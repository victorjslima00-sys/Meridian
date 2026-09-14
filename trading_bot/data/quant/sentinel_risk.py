"""
Motor de Gestao de Risco e Circuit Breakers Institucionais — Sentinel
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SentinelRiskEngine:
    """
    Guardião algorítmico do Meridian. Monitora a curva de capital em tempo real,
    desarma ordens automaticamente em caso de violação de limites (Drawdown Cap, Volatilidade Extrema).
    """

    def __init__(self, max_drawdown_limit_pct: float = 10.0, max_leverage: float = 1.0):
        self.max_drawdown_limit_pct = max_drawdown_limit_pct
        self.max_leverage = max_leverage

    def check_risk_breach(self, current_drawdown_pct: float) -> bool:
        return current_drawdown_pct > self.max_drawdown_limit_pct

    def evaluate_portfolio_state(
        self,
        portfolio_value: float,
        peak_value: float,
        volatility_annual: float,
    ) -> dict[str, Any]:
        """
        Avalia o estado de risco da carteira e decide a continuidade operacional.
        """
        drawdown_pct = 0.0
        if peak_value > 0:
            drawdown_pct = max(0.0, ((peak_value - portfolio_value) / peak_value) * 100.0)

        is_breached = self.check_risk_breach(drawdown_pct)
        is_vol_spike = volatility_annual > 0.40  # Volatilidade anualizada > 40% indica estresse extremo

        tripped = is_breached or is_vol_spike
        action = "EMERGENCY_DELEVERAGE" if is_breached else ("REDUCE_SIZE" if is_vol_spike else "NORMAL_OPERATION")
        alloc = 0.0 if is_breached else (0.5 if is_vol_spike else 1.0)

        return {
            "drawdown_pct": round(drawdown_pct, 2),
            "volatility_annual": round(volatility_annual, 2),
            "circuit_breaker_tripped": tripped,
            "action": action,
            "recommended_risk_allocation": alloc,
        }

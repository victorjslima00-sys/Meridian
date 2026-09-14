"""
Motor de Atribuicao de Performance e P&L Institucional — Atlas Analytics
Head of Quantitative Analytics: Atlas
Meridian Technologies
"""
from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


class PerformanceAttributionEngine:
    """
    Desmembra o P&L da carteira em metricas granulares de atribuicao:
      - Profit Factor (Ganhos Brutos / Perdas Brutas)
      - Retorno e P&L acumulado por ticker
      - Tempo medio de duracao das operacoes (holding period)
      - Taxa de acerto institucional
    """

    def __init__(self):
        pass

    def generate_attribution_report(self, trades: List[dict[str, Any]]) -> dict[str, Any]:
        if not trades:
            return {"total_trades": 0, "net_pnl": 0.0}

        total_trades = len(trades)
        pnls = [float(t.get("pnl", 0.0)) for t in trades]
        net_pnl = round(sum(pnls), 2)

        gross_profits = sum(p for p in pnls if p > 0)
        gross_losses = abs(sum(p for p in pnls if p < 0))
        profit_factor = round(gross_profits / max(gross_losses, 1e-6), 2)

        wins = [p for p in pnls if p > 0]
        win_rate_pct = round((len(wins) / total_trades) * 100.0, 2)

        # Decomposicao por ticker
        by_ticker: dict[str, dict[str, Any]] = {}
        for t in trades:
            sym = str(t.get("ticker", "UNKNOWN")).upper()
            if sym not in by_ticker:
                by_ticker[sym] = {"trades": 0, "net_pnl": 0.0, "wins": 0}
            by_ticker[sym]["trades"] += 1
            by_ticker[sym]["net_pnl"] = round(by_ticker[sym]["net_pnl"] + float(t.get("pnl", 0.0)), 2)
            if float(t.get("pnl", 0.0)) > 0:
                by_ticker[sym]["wins"] += 1

        return {
            "total_trades": total_trades,
            "net_pnl": net_pnl,
            "gross_profits": round(gross_profits, 2),
            "gross_losses": round(gross_losses, 2),
            "profit_factor": profit_factor,
            "win_rate_pct": win_rate_pct,
            "by_ticker": by_ticker,
        }

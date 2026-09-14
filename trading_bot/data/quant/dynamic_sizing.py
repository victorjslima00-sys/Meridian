r"""
Motor de Dimensionamento Dinamico de Kelly e Adaptacao Multimercado
Head of Quantitative Analytics: Atlas
Meridian Technologies

Fundamentacao:
Formula de Kelly Fracionario:
  f^* = \frac{p \cdot b - q}{b} \cdot \text{fracao\_base}
Onde:
  p = taxa de acerto (win rate)
  q = 1 - p
  b = razao payoff (avg win / avg loss)
Ajuste Adaptativo por Regime de Mercado (K-Means) e Taxa Selic (Bacen).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DynamicRegimeKellyEngine:
    """
    Calcula a fracao ideal de capital alocada em cada ativo adaptando-se
    ao regime de volatilidade (Baixa, Media, Alta) e a taxa de juros livre de risco.
    """

    def __init__(self, base_fraction: float = 0.25, max_positions: int = 3):
        self.base_fraction = base_fraction
        self.max_positions = max_positions

    def compute_allocation(
        self,
        win_rate: float,
        payoff_ratio: float,
        volatility_regime: str = "LOW",
        selic_rate: float = 0.139,
    ) -> dict[str, Any]:
        p = max(0.01, min(0.99, win_rate))
        q = 1.0 - p
        b = max(0.1, payoff_ratio)

        # Kelly puro (f^*)
        raw_kelly = (p * b - q) / b

        if raw_kelly <= 0:
            return {
                "target_allocation_pct": 0.0,
                "per_position_pct": 0.0,
                "mode": "NO_EDGE",
            }

        # Multiplicador por regime de volatilidade
        regime_upper = volatility_regime.upper()
        if regime_upper == "HIGH":
            regime_mult = 0.5  # Corta pela metade no estresse
            mode = "DEFENSIVE"
        elif regime_upper == "MEDIUM":
            regime_mult = 0.8
            mode = "MODERATE"
        else:
            regime_mult = 1.0
            mode = "NORMAL"

        # Ajuste de custo de oportunidade contra juros altos
        interest_discount = max(0.7, 1.0 - (selic_rate * 0.5))

        effective_fraction = self.base_fraction * regime_mult * interest_discount
        target_allocation = min(1.0, raw_kelly * effective_fraction)
        per_position = target_allocation / float(self.max_positions)

        return {
            "raw_kelly": round(raw_kelly, 4),
            "target_allocation_pct": round(target_allocation * 100.0, 2),
            "per_position_pct": round(per_position, 4),
            "mode": mode,
            "regime": regime_upper,
        }

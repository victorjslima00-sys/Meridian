"""
Simulador de Estresse Macroeconomico e Sensibilidade de Retorno / Custo de Oportunidade
Head of Data Engineering: Orion
Meridian Technologies

Fundamentacao:
Modela o impacto de choques na taxa Selic/CDI sobre o hurdle rate (taxa minima de atratividade)
e deriva o multiplicador de apetite de risco para calibracao automatica de position sizing pela Astra.
"""
from __future__ import annotations

import logging
from typing import Any, List

import numpy as np

logger = logging.getLogger(__name__)


class MacroStressSimulator:
    """
    Simula cenarios de choques de juros (basis points) e calcula o impacto na barreira de rentabilidade
    necessaria para que a estrategia bata a taxa livre de risco com significancia estatistica.
    """

    def __init__(self, initial_selic: float = 13.9, n_simulations: int = 1000):
        self.initial_selic = initial_selic
        self.n_simulations = n_simulations

    def simulate_selic_shocks(self, shocks_bps: List[int]) -> List[dict[str, Any]]:
        """
        Calcula os cenarios de choque de juros.
        shocks_bps: ex [-200, -100, 0, +100, +200]
        """
        results = []
        for bps in shocks_bps:
            delta_pct = bps / 100.0
            simulated_selic = round(self.initial_selic + delta_pct, 2)
            
            # Taxa minima para bater o CDI (Hurdle Rate: CDI + spread de risco operacional de 3%)
            hurdle_rate = round(simulated_selic + 3.0, 2)
            
            # Multiplicador de apetite por risco (quanto mais alto o juro, menor o risco que devemos tomar)
            # Base 1.0 para Selic de 13.9%
            risk_multiplier = round(13.9 / max(simulated_selic, 5.0), 3)

            results.append({
                "shock_bps": bps,
                "simulated_selic": simulated_selic,
                "expected_hurdle_rate": hurdle_rate,
                "risk_appetite_multiplier": risk_multiplier,
                "regime": "Ultra-Restritivo" if simulated_selic > 14.5 else ("Expansionista" if simulated_selic < 11.5 else "Moderado"),
            })

        return results

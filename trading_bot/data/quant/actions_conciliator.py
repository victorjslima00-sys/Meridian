"""
Motor de Mapeamento e Conciliacao Matematica de Proventos CVM vs Precos XP
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import logging
from typing import Any, List

import pandas as pd

logger = logging.getLogger(__name__)


class CorporateActionsConciliator:
    """
    Concilia a diferenca exata entre o preco nominal (COTAHIST B3 / Fracionario XP)
    e o preco ajustado (Lote Padrao XP) atraves do somatorio dos proventos homologados pela CVM.
    """

    def __init__(self):
        pass

    def conciliate_divergence(
        self,
        nominal_price: float,
        adjusted_price: float,
        dividends: List[float],
    ) -> dict[str, Any]:
        """
        nominal_price: Preco COTAHIST / Fracionario
        adjusted_price: Preco Padrao XP
        dividends: Lista de proventos pagos no periodo posterior a data
        """
        observed_delta = round(nominal_price - adjusted_price, 2)
        total_dividends = round(sum(dividends), 2)
        residual = round(abs(observed_delta - total_dividends), 2)

        return {
            "nominal_price": nominal_price,
            "adjusted_price": adjusted_price,
            "observed_delta": observed_delta,
            "total_dividends_cvm": total_dividends,
            "residual": residual,
            "is_fully_explained": residual <= 0.05,  # Tolerancia centesimal de arredondamento
        }

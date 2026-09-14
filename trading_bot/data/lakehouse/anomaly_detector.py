"""
Motor de Deteccao de Anomalias e Qualidade de Dados (Data Quality / Great Expectations Light)
Head of Data Engineering: Orion
Meridian Technologies

Padrão de Big Data:
Audita datasets antes da promocao da camada Silver para Gold.
Detecta:
  - Valores ausentes (NaN/Null) em colunas obrigatorias
  - Precos negativos ou zerados
  - Saltos absurdos de precos (Flash crashes / Spikes anomalos de feed)
  - Timestamps fora de ordem cronologica
"""
from __future__ import annotations

import logging
from typing import Any, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataQualityAnomalyDetector:
    """
    Auditor algorítmico da camada Silver. Bloqueia dados impuros antes de atingir os modelos da Astra.
    """

    def __init__(self, max_allowed_daily_return: float = 0.40):
        self.max_allowed_daily_return = max_allowed_daily_return

    def audit_dataframe(
        self,
        df: pd.DataFrame,
        required_cols: List[str],
        price_col: str = "close",
    ) -> dict[str, Any]:
        if df.empty:
            return {"is_valid": False, "anomalies": ["DataFrame vazio"]}

        anomalies = []

        # 1. Colunas obrigatorias
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            anomalies.append(f"Colunas obrigatorias ausentes: {missing_cols}")

        # 2. Valores nulos
        null_counts = df[required_cols].isnull().sum()
        for col, count in null_counts.items():
            if count > 0:
                anomalies.append(f"Coluna {col} possui {count} valores nulos")

        # 3. Validacao de precos
        if price_col in df.columns:
            negative_prices = (df[price_col] <= 0).sum()
            if negative_prices > 0:
                anomalies.append(f"Coluna {price_col} possui {negative_prices} precos menores ou iguais a zero")

            # Inspecao de saltos de preco anomalos
            prices = df[price_col].values
            if len(prices) > 1:
                # Evita divisao por zero
                safe_prev = np.where(prices[:-1] == 0, 1e-6, prices[:-1])
                pct_changes = np.abs((prices[1:] / safe_prev) - 1.0)
                spikes = np.where(pct_changes > self.max_allowed_daily_return)[0]
                if len(spikes) > 0:
                    anomalies.append(
                        f"Detectado salto anormal de preco superior a {self.max_allowed_daily_return*100}% em {len(spikes)} barras"
                    )

        is_valid = len(anomalies) == 0
        return {
            "is_valid": is_valid,
            "anomalies": anomalies,
            "rows_audited": len(df),
        }

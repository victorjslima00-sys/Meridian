"""
Carregador e Extrator Temporal Causal para Séries Históricas da B3 (COTAHIST)
=============================================================================
Lê conjuntos de cotações gerados por trading_bot.data.cotahist, valida
integridade por hash SHA-256 e manifesto estrutural, e extrai features
estritamente causais (lag 1) com garantia de zero lookahead bias.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from trading_bot.data.model_evaluation import DataPoint


class PointInTimeFeatureExtractor:
    """
    Extrator de features point-in-time com defasagem temporal rígida.
    Garante que as variáveis preditivas para o período t sejam calculadas
    estritamente a partir de informações disponíveis até t-1 (zero lookahead bias).
    """

    @staticmethod
    def extract_causal_features(
        closes: np.ndarray,
        highs: Optional[np.ndarray] = None,
        lows: Optional[np.ndarray] = None,
        warmup_bars: int = 20,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calcula matriz de features X (N - warmup_bars, D) e vetor alvo y.
        Para a barra de índice t (t >= warmup_bars):
          - Features usam exclusivamente preços de índices <= t - 1.
          - Target prevê a direção do retorno entre t-1 e t: 1.0 se close[t] > close[t-1], senão 0.0.
        """
        n = len(closes)
        if n <= warmup_bars:
            raise ValueError(f"insufficient_bars: needed > {warmup_bars}, got {n}")

        if highs is None:
            highs = closes
        if lows is None:
            lows = closes

        features_list = []
        targets = []

        # Retornos diários simples
        daily_returns = np.zeros(n)
        daily_returns[1:] = (closes[1:] - closes[:-1]) / (closes[:-1] + 1e-12)

        for t in range(warmup_bars, n):
            # Causal Window: índices [t - warmup_bars, t - 1] (estritamente ANTERIORES a t)
            # 1. Momentum de curto prazo (retorno de 1 dia defasado: t-2 para t-1)
            f0 = float(daily_returns[t - 1])

            # 2. Retorno móvel de 5 dias defasado: (close[t-1] - close[t-6]) / close[t-6]
            idx_5d = max(0, t - 6)
            f1 = float((closes[t - 1] - closes[idx_5d]) / (closes[idx_5d] + 1e-12))

            # 3. Volatilidade móvel de 10 dias defasada: std dos retornos [t-10 : t-1]
            idx_10d = max(0, t - 10)
            window_rets = daily_returns[idx_10d:t]
            f2 = float(np.std(window_rets)) if len(window_rets) > 1 else 0.0

            # 4. Posição no canal Donchian de 20 dias defasado
            donchian_high = float(np.max(highs[t - warmup_bars:t]))
            donchian_low = float(np.min(lows[t - warmup_bars:t]))
            donchian_range = donchian_high - donchian_low
            f3 = (
                float((closes[t - 1] - donchian_low) / donchian_range)
                if donchian_range > 1e-6
                else 0.5
            )

            features_list.append([round(f0, 6), round(f1, 6), round(f2, 6), round(f3, 6)])

            # Target para o período t: retorno de t-1 para t
            target = 1.0 if closes[t] > closes[t - 1] else 0.0
            targets.append(target)

        return np.array(features_list, dtype=float), np.array(targets, dtype=float)


def load_b3_research_series_from_cotahist(
    export_dir: Path | str,
    ticker: str,
    warmup_bars: int = 20,
) -> Tuple[List[DataPoint], str, str]:
    """
    Carrega série histórica da B3 a partir de diretório exportado pelo minerador COTAHIST.

    Validações:
      1. Presença e integridade do manifest.json.
      2. Status de validação estrutural no manifesto ('passed').
      3. Cálculo de digest SHA-256 do quotes.csv.
      4. Extração de features point-in-time causais sem lookahead.

    Retorna:
      (points, dataset_sha256, dataset_ref)
    """
    dir_path = Path(export_dir)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"directory_not_found: {dir_path}")

    manifest_file = dir_path / "manifest.json"
    quotes_file = dir_path / "quotes.csv"

    if not manifest_file.is_file():
        raise FileNotFoundError(f"manifest_missing_in: {dir_path}")
    if not quotes_file.is_file():
        raise FileNotFoundError(f"quotes_csv_missing_in: {dir_path}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("structural_validation") != "passed":
        raise ValueError(
            f"cotahist_integrity_failed: structural_validation is '{manifest.get('structural_validation')}'"
        )

    # Hash SHA-256 durável do quotes.csv
    with quotes_file.open("rb") as f:
        quotes_sha256 = hashlib.sha256(f.read()).hexdigest()

    # Leitura e filtragem das cotações
    target_ticker = ticker.strip().upper()
    rows = []
    with quotes_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r["ticker"].strip().upper() == target_ticker:
                rows.append(r)

    if not rows:
        raise ValueError(f"ticker_not_found_in_cotahist: {target_ticker}")

    # Ordenação cronológica estrita
    rows.sort(key=lambda x: x["trading_date"])

    dates: List[str] = []
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []

    for r in rows:
        dates.append(r["trading_date"])
        closes.append(float(r["close"]))
        highs.append(float(r["high"]))
        lows.append(float(r["low"]))

    closes_arr = np.array(closes, dtype=float)
    highs_arr = np.array(highs, dtype=float)
    lows_arr = np.array(lows, dtype=float)

    X, y = PointInTimeFeatureExtractor.extract_causal_features(
        closes=closes_arr,
        highs=highs_arr,
        lows=lows_arr,
        warmup_bars=warmup_bars,
    )

    points: List[DataPoint] = []
    for idx, t in enumerate(range(warmup_bars, len(closes))):
        dp = DataPoint(
            date=dates[t],
            features=[float(val) for val in X[idx]],
            target=float(y[idx]),
            price=round(float(closes[t]), 4),
        )
        points.append(dp)

    dataset_ref = f"cotahist://{dir_path.name}/{target_ticker}"
    return points, quotes_sha256, dataset_ref
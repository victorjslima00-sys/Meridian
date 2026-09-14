"""
Testes unitarios para o Motor de Detecao de Anomalias e Qualidade de Dados (Great Expectations Light)
"""
import pandas as pd
import pytest
from trading_bot.data.lakehouse.anomaly_detector import DataQualityAnomalyDetector


def test_anomaly_detector_missing_and_types():
    detector = DataQualityAnomalyDetector()
    
    # DataFrame valido
    df_clean = pd.DataFrame({
        "ts": ["2026-09-10", "2026-09-11"],
        "close": [35.5, 35.8],
        "volume": [1000, 2000],
    })
    report = detector.audit_dataframe(df_clean, required_cols=["ts", "close", "volume"])
    assert report["is_valid"] is True
    assert len(report["anomalies"]) == 0


def test_anomaly_detector_price_spike_and_negative_values():
    detector = DataQualityAnomalyDetector(max_allowed_daily_return=0.30)
    
    # DataFrame com preco negativo e salto de 100% no mesmo dia (spike anomalo)
    df_dirty = pd.DataFrame({
        "ts": ["2026-09-10", "2026-09-11", "2026-09-12"],
        "close": [30.0, -5.0, 65.0],
        "volume": [1000, 0, 5000],
    })
    
    report = detector.audit_dataframe(df_dirty, required_cols=["ts", "close", "volume"])
    assert report["is_valid"] is False
    assert len(report["anomalies"]) >= 2

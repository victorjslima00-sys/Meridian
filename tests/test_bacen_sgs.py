"""
Testes unitarios para o Minerador Bacen SGS — Orion Data Engineering
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from trading_bot.data.miners.bacen_sgs import (
    BacenSgsMiner,
    BacenSeriesConfig,
    SGS_SERIES,
)


def test_sgs_series_registry():
    """Valida se as series fundamentais estao registradas."""
    assert "selic_daily" in SGS_SERIES
    assert "cdi_daily" in SGS_SERIES
    assert "ipca_monthly" in SGS_SERIES
    assert SGS_SERIES["selic_daily"].code == 11
    assert SGS_SERIES["cdi_daily"].code == 12


@patch("urllib.request.urlopen")
def test_fetch_series_success(mock_urlopen):
    """Testa busca bem-sucedida com parsing de JSON e enriquecimento."""
    mock_data = [
        {"data": "01/09/2026", "valor": "0.045231"},
        {"data": "02/09/2026", "valor": "0.045231"},
    ]
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    miner = BacenSgsMiner()
    df = miner.fetch_series(series_code=11, start_date="01/09/2026", end_date="02/09/2026")

    assert not df.empty
    assert len(df) == 2
    assert "valor" in df.columns
    assert "data" in df.columns
    assert "taxa_anual_estimada" in df.columns
    assert df["valor"].iloc[0] == pytest.approx(0.045231)
    assert df["taxa_anual_estimada"].iloc[0] > 10.0


@patch("urllib.request.urlopen")
def test_fetch_macro_snapshot(mock_urlopen):
    """Testa geracao do snapshot macro consolidado."""
    mock_data = [{"data": "11/09/2026", "valor": "0.045231"}]
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    miner = BacenSgsMiner()
    snapshot = miner.get_macro_snapshot()

    assert "selic_daily" in snapshot
    assert "cdi_daily" in snapshot
    assert "timestamp_utc" in snapshot
    assert "manifest_sha256" in snapshot
    assert len(snapshot["manifest_sha256"]) == 64

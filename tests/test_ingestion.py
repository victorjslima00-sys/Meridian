import pytest
import pandas as pd
from datetime import date
import yaml
from trading_bot.data.ingestion import _normalize, _load_settings, _load_universe

def test_load_settings(tmp_path):
    settings_file = tmp_path / "settings.yaml"
    settings_content = {"data": {"brapi_token": "fake_token"}}
    with open(settings_file, "w") as f:
        yaml.dump(settings_content, f)
    
    loaded = _load_settings(str(settings_file))
    assert loaded["data"]["brapi_token"] == "fake_token"

def test_load_universe(tmp_path):
    universe_file = tmp_path / "universe.yaml"
    universe_content = {"universe": {"tickers": ["PETR4", "VALE3"]}}
    with open(universe_file, "w") as f:
        yaml.dump(universe_content, f)
        
    tickers = _load_universe(str(universe_file))
    assert "PETR4" in tickers
    assert "VALE3" in tickers

def test_normalize():
    # Test _normalize with standard columns
    raw_data = pd.DataFrame([
        {"Date": "2023-01-01", "Open": 100, "High": 105, "Low": 95, "Close": 100, "Volume": 1000}
    ])
    
    normalized = _normalize(raw_data, "TEST3")
    
    assert list(normalized.columns) == ["ticker", "ts", "o", "h", "l", "c", "v", "adj_close"]
    assert normalized["ticker"].iloc[0] == "TEST3"
    assert normalized["o"].iloc[0] == 100
    assert normalized["adj_close"].iloc[0] == 100 # Default fallback
    assert normalized["ts"].iloc[0] == date(2023, 1, 1)

def test_normalize_missing_date():
    raw_data = pd.DataFrame([
        {"Open": 100, "Close": 100}
    ])
    with pytest.raises(ValueError):
        _normalize(raw_data, "TEST3")

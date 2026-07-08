import pytest
import yaml
from trading_bot.core.config import AppConfig, setup_logging

def test_appconfig_load(tmp_path):
    settings_file = tmp_path / "settings.yaml"
    universe_file = tmp_path / "universe.yaml"
    
    with open(settings_file, "w") as f:
        yaml.dump({"data": {"token": "123"}, "logging": {"level": "DEBUG"}}, f)
        
    with open(universe_file, "w") as f:
        yaml.dump({"universe": {"tickers": ["A", "B"]}}, f)
        
    cfg = AppConfig.load(str(settings_file), str(universe_file))
    assert cfg.get("data", "token") == "123"
    assert cfg.get("logging", "level") == "DEBUG"
    assert cfg.get("_universe", "tickers") == ["A", "B"]
    assert cfg.get("missing", "key", default="fallback") == "fallback"

def test_setup_logging(tmp_path):
    log_file = tmp_path / "test.log"
    cfg = AppConfig(raw={"logging": {"level": "DEBUG", "path": str(log_file)}})
    setup_logging(cfg)
    assert log_file.parent.exists()

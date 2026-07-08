import os
import sys

# Add project root to sys.path to avoid ModuleNotFoundError
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import json
import yaml
import pytest
import pandas as pd
import requests
from datetime import datetime, date, timedelta
from types import ModuleType
from trading_bot.core.config import AppConfig

# ---------------------------------------------------------------------------
# Auto-generate mock data at session start
# ---------------------------------------------------------------------------

MOCK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_data"))
os.makedirs(MOCK_DIR, exist_ok=True)

# Generate yf_PETR4.csv if not exists
petr4_csv = os.path.join(MOCK_DIR, "yf_PETR4.csv")
if not os.path.exists(petr4_csv):
    start_date = date(2019, 1, 1)
    end_date = date(2024, 7, 1)
    dates = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() < 5:
            dates.append(curr)
        curr += timedelta(days=1)
    n_days = len(dates)
    prices = [20.0 + (i * 0.02) for i in range(n_days)]
    df = pd.DataFrame({
        "Open": prices,
        "High": [p + 0.5 for p in prices],
        "Low": [p - 0.5 for p in prices],
        "Close": [p + 0.1 for p in prices],
        "Volume": [10000000] * n_days
    }, index=pd.to_datetime(dates))
    df.index.name = "Date"
    df.to_csv(petr4_csv)

# Generate yf_BVSP.csv if not exists
bvsp_csv = os.path.join(MOCK_DIR, "yf_BVSP.csv")
if not os.path.exists(bvsp_csv):
    start_date = date(2019, 1, 1)
    end_date = date(2024, 7, 1)
    dates = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() < 5:
            dates.append(curr)
        curr += timedelta(days=1)
    n_days = len(dates)
    prices = [90000.0 + (i * 20.0) for i in range(n_days)]
    df = pd.DataFrame({
        "Open": prices,
        "High": [p + 200.0 for p in prices],
        "Low": [p - 200.0 for p in prices],
        "Close": [p + 50.0 for p in prices],
        "Volume": [5000000] * n_days
    }, index=pd.to_datetime(dates))
    df.index.name = "Date"
    df.to_csv(bvsp_csv)

# Generate brapi_PETR4.json if not exists
petr4_json = os.path.join(MOCK_DIR, "brapi_PETR4.json")
if not os.path.exists(petr4_json):
    brapi_payload = {
        "results": [
            {
                "symbol": "PETR4",
                "regularMarketOpen": 35.0,
                "regularMarketDayHigh": 36.0,
                "regularMarketDayLow": 34.5,
                "regularMarketPrice": 35.5,
                "regularMarketVolume": 10000000,
                "historicalDataPrice": [
                    {
                        "date": int(datetime(2024, 6, 30).timestamp()),
                        "open": 35.0,
                        "high": 36.0,
                        "low": 34.5,
                        "close": 35.5,
                        "volume": 10000000,
                        "adjustedClose": 35.5
                    }
                ]
            }
        ]
    }
    with open(petr4_json, "w") as f:
        json.dump(brapi_payload, f, indent=2)

# ---------------------------------------------------------------------------
# Mock/Stub classes for Telegram and Cedro Client
# ---------------------------------------------------------------------------

class MockTelegramClient:
    send_calls = []
    poll_calls = []

    def __init__(self, token=None, chat_id=None, **kwargs):
        self.token = token
        self.chat_id = chat_id

    @classmethod
    def reset(cls):
        cls.send_calls.clear()
        cls.poll_calls.clear()

    def send_message(self, message: str) -> bool:
        self.send_calls.append(message)
        return True

    def poll_updates(self) -> list:
        self.poll_calls.append("poll")
        return []

class MockCedroClient:
    order_calls = []

    def __init__(self, api_key=None, api_secret=None, base_url=None, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url

    @classmethod
    def reset(cls):
        cls.order_calls.clear()

    def execute_order(self, ticker: str, side: str, qty: int, price: float, **kwargs) -> dict:
        call_info = {
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "price": price,
            "kwargs": kwargs
        }
        self.order_calls.append(call_info)
        return {"status": "executed", "order_id": "mock_order_123"}

# Register mock modules dynamically in sys.modules
if "trading_bot.core.telegram" not in sys.modules:
    telegram_mod = ModuleType("trading_bot.core.telegram")
    telegram_mod.TelegramClient = MockTelegramClient
    sys.modules["trading_bot.core.telegram"] = telegram_mod

if "trading_bot.broker.cedro" not in sys.modules:
    cedro_mod = ModuleType("trading_bot.broker.cedro")
    cedro_mod.CedroClient = MockCedroClient
    cedro_mod.Cedro = MockCedroClient
    sys.modules["trading_bot.broker.cedro"] = cedro_mod

# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sandbox_config(tmp_path, monkeypatch):
    """Automatically overrides AppConfig.load to point to sandboxed config and temp db."""
    settings_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "settings.yaml"))
    universe_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "config", "universe.yaml"))
    
    with open(settings_path) as f:
        settings = yaml.safe_load(f)
    with open(universe_path) as f:
        universe = yaml.safe_load(f)
    settings["_universe"] = universe["universe"]
    
    # Redirect db_path to a temporary file
    db_file = tmp_path / "test_trading_bot.db"
    settings["data"]["db_path"] = str(db_file)
    
    cfg = AppConfig(raw=settings)
    monkeypatch.setattr(AppConfig, "load", lambda *args, **kwargs: cfg)
    return cfg

@pytest.fixture
def mock_b3_clock(monkeypatch):
    """Fixture to return a fixed date (2024-06-30)."""
    fixed_date = date(2024, 6, 30)
    monkeypatch.setattr("trading_bot.core.clock.today_b3", lambda: fixed_date)
    return fixed_date

@pytest.fixture
def mock_yfinance(monkeypatch):
    """Fixture to patch yfinance.download to read from mock CSV files."""
    def _mock_download(tickers, start=None, end=None, *args, **kwargs):
        if isinstance(tickers, str):
            ticker_list = tickers.split()
        else:
            ticker_list = tickers
            
        ticker = ticker_list[0] if len(ticker_list) == 1 else tickers
        clean_ticker = ticker.replace(".SA", "")
        
        if clean_ticker == "^BVSP":
            csv_file = os.path.join(MOCK_DIR, "yf_BVSP.csv")
        elif clean_ticker == "PETR4":
            csv_file = os.path.join(MOCK_DIR, "yf_PETR4.csv")
        else:
            csv_file = os.path.join(MOCK_DIR, "yf_PETR4.csv")
            
        if not os.path.exists(csv_file):
            return pd.DataFrame()
            
        df = pd.read_csv(csv_file, parse_dates=["Date"])
        df.set_index("Date", inplace=True)
        
        if start:
            df = df[df.index >= pd.to_datetime(start)]
        if end:
            df = df[df.index <= pd.to_datetime(end)]
            
        return df

    import yfinance as yf
    monkeypatch.setattr(yf, "download", _mock_download)
    return _mock_download

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(f"Mock HTTP Error {self.status_code}")

@pytest.fixture
def mock_brapi_api(monkeypatch):
    """Fixture to patch requests.get for Brapi API."""
    def _mock_get(url, params=None, **kwargs):
        if "brapi.dev/api/quote" in url:
            ticker = url.split("/quote/")[-1].split("?")[0]
            json_file = os.path.join(MOCK_DIR, f"brapi_{ticker}.json")
            if os.path.exists(json_file):
                with open(json_file) as f:
                    data = json.load(f)
                return MockResponse(data, 200)
            else:
                return MockResponse({"error": True, "message": f"Ticker {ticker} not found"}, 404)
        return MockResponse({}, 404)

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get

@pytest.fixture
def mock_telegram_client():
    """Fixture to return the MockTelegramClient and reset call logs."""
    MockTelegramClient.reset()
    return MockTelegramClient

@pytest.fixture
def mock_cedro_client():
    """Fixture to return the MockCedroClient and reset call logs."""
    MockCedroClient.reset()
    return MockCedroClient

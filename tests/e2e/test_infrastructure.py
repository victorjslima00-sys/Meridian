import pytest
from datetime import date
from trading_bot.core.config import AppConfig
from trading_bot.core import clock
import yfinance as yf
import requests

def test_sandbox_config(sandbox_config):
    # Verify that loading AppConfig returns the sandbox config
    cfg = AppConfig.load()
    assert cfg.get("data", "brapi_token") == "MOCK_TOKEN"
    assert "test_trading_bot.db" in cfg.get("data", "db_path")
    assert cfg.get("_universe", "tickers") == ["PETR4"]

def test_mock_b3_clock(mock_b3_clock):
    # Verify that clock returns fixed date
    assert clock.today_b3() == date(2024, 6, 30)

def test_mock_yfinance(mock_yfinance):
    # Verify that yfinance downloads from mock data
    df_petr4 = yf.download("PETR4.SA", start="2024-06-01", end="2024-06-05")
    assert not df_petr4.empty
    assert "Close" in df_petr4.columns
    assert df_petr4.index[0].date() == date(2024, 6, 3)  # First weekday after June 1st, 2024

    df_bvsp = yf.download("^BVSP", start="2024-06-01", end="2024-06-05")
    assert not df_bvsp.empty
    assert "Close" in df_bvsp.columns

def test_mock_brapi_api(mock_brapi_api):
    # Verify that Brapi API is mocked and returns mock payload
    resp = requests.get("https://brapi.dev/api/quote/PETR4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["symbol"] == "PETR4"
    assert data["results"][0]["historicalDataPrice"][0]["close"] == 35.5

def test_mock_telegram_client(mock_telegram_client):
    # Verify import and usage of dynamic MockTelegramClient
    from trading_bot.core.telegram import TelegramClient
    client = TelegramClient(token="abc", chat_id="123")
    assert client.send_message("Hello World") is True
    assert "Hello World" in mock_telegram_client.send_calls

def test_mock_cedro_client(mock_cedro_client):
    # Verify import and usage of dynamic MockCedroClient
    from trading_bot.broker.cedro import CedroClient
    client = CedroClient(api_key="key", api_secret="sec")
    res = client.execute_order("PETR4", "BUY", 100, 35.5)
    assert res["status"] == "executed"
    assert len(mock_cedro_client.order_calls) == 1
    assert mock_cedro_client.order_calls[0]["ticker"] == "PETR4"

# E2E Test Runner Design Recommendation for Meridian

## 1. Executive Summary
To enable reliable, deterministic, and opaque-box end-to-end (E2E) testing of the Meridian trading system in a restricted `CODE_ONLY` environment, we recommend an **in-process script execution runner** powered by `pytest`. By importing the `main()` functions of the entry point scripts (`fase0_validate_data.py` and `fase1_backtest.py`) and utilizing pytest's `monkeypatch` and `unittest.mock` fixtures, we can comprehensively mock external network calls (Yahoo Finance and Brapi.dev) and system clocks, redirect database paths, and inspect outputs without altering the production source code.

---

## 2. Investigation of Existing Testing Setup

### 2.1 Current Test Layout and Execution
* **Structure**: Existing unit/integration tests are located under the `tests/` directory (e.g., `test_engine.py`, `test_metrics.py`, `test_risk.py`, `test_signals.py`).
* **Execution**: Run locally using the command `pytest`.
* **State**: There are 18 passing tests covering risk management (circuit breakers, correlation), signals (RSI, SMA, volume ratio), and metrics calculations (Sharpe ratio, max drawdown).
* **Code Layout Compliance**: Tests are currently flat under `tests/`. No tests are located in `.agents/`.

### 2.2 External Dependencies & Current Mocking
1. **Market Data (Yahoo Finance & Brapi.dev)**:
   * Location: `trading_bot/data/ingestion.py`
   * **Yahoo Finance**: `fetch_yfinance` calls `yf.download(...)` directly using the external `yfinance` library.
   * **Brapi.dev**: `fetch_brapi` performs HTTP GET requests using `requests.get` to `https://brapi.dev/api`.
   * **Current Mocks**: The integration tests (`tests/test_engine.py`) contain skeleton fixtures that patch `trading_bot.backtest.engine.get_ibov_data` and signals but are not fully populated. There are no active mocks for `yf.download` or `requests.get` in the current test suite.
2. **Telegram Bot Client**:
   * Location: Planned for `trading_bot/core/telegram.py` (Milestone M2).
   * **Current State**: The module `core/telegram.py` does not exist yet. It is currently planned to export `TelegramClient`.
3. **Cedro Technologies Broker Execution**:
   * Location: Planned for `trading_bot/broker/` and `trading_bot/execution/` (Milestone M2/M3).
   * **Current State**: The directories contain only empty `__init__.py` files. No actual execution client is present.
4. **System Clock**:
   * Location: `trading_bot/core/clock.py` -> `today_b3()`
   * **Mechanism**: Calls `datetime.now(ZoneInfo("America/Sao_Paulo")).date()`. E2E tests run on different days would yield non-deterministic results when computing historical dates or limits, requiring the clock to be mocked.

---

## 3. Recommended E2E Test Runner Design

### 3.1 Design Rationale: In-Process vs. Subprocess
We recommend running E2E tests **in-process** via `pytest` over running them as external subprocesses (e.g., `subprocess.run(["python", "scripts/fase1_backtest.py"])`):

| Aspect | Subprocess Runner | In-Process Pytest Runner (Recommended) |
|---|---|---|
| **API Mocking** | Extremely complex. Requires a local mock HTTP server and env variables (`HTTP_PROXY`, `HTTPS_PROXY`) to intercept `yfinance` and `requests`. | Extremely simple. Python's `monkeypatch` intercepts `yf.download` and `requests.get` at the module level. |
| **State Inspection** | Limited to log scraping and database querying. | Direct verification of function returns, captured Telegram messages, and memory state. |
| **Clock control** | Difficult (requires setting system time or complex native library shims like `libfaketime`). | Simple monkeypatch of `trading_bot.core.clock.today_b3`. |
| **Config Redirection** | Requires editing physical files on disk before running. | Clean in-memory overriding of configuration loading paths. |

### 3.2 Directory Layout
To keep E2E tests segregated from unit/integration tests while respecting layout constraints, we propose the following structure:

```text
tests/
├── conftest.py                   # Shared global fixtures
├── test_engine.py
├── test_metrics.py
├── test_risk.py
├── test_signals.py
└── e2e/                           # Dedicated E2E directory
    ├── __init__.py
    ├── conftest.py               # E2E-specific fixtures (AppConfig mock, network mocks)
    ├── test_e2e_fase0.py         # E2E validation tests (Fase 0)
    ├── test_e2e_fase1.py         # E2E backtest tests (Fase 1)
    ├── config/                   # Sandboxed configuration files
    │   ├── settings.yaml
    │   └── universe.yaml
    └── data/                     # Offline test data
        ├── b3_test_universe.csv  # Mock B3 OHLCV prices
        └── test_trading_bot.db   # Temp SQLite database path
```

---

## 4. E2E Mocking and Stubbing Strategy

### 4.1 Sandboxing Configuration & DB
A fixture in `tests/e2e/conftest.py` will patch `AppConfig.load` so that any test execution automatically redirects to the E2E config folder and uses a sandboxed SQLite database:

```python
# tests/e2e/conftest.py
import pytest
from pathlib import Path
from trading_bot.core.config import AppConfig

@pytest.fixture(autouse=True)
def sandbox_config(monkeypatch, tmp_path):
    # Setup paths to E2E test configs
    test_config_dir = Path(__file__).parent / "config"
    test_settings = test_config_dir / "settings.yaml"
    test_universe = test_config_dir / "universe.yaml"
    
    # Overwrite the AppConfig.load defaults using monkeypatch
    original_load = AppConfig.load
    def mocked_load(cls, settings_path=None, universe_path=None):
        settings = str(test_settings) if settings_path is None else settings_path
        universe = str(test_universe) if universe_path is None else universe_path
        # We can also dynamically point settings DB path to tmp_path / "test.db"
        cfg = original_load(settings_path=settings, universe_path=universe)
        cfg.raw["data"]["db_path"] = str(tmp_path / "test_trading_bot.db")
        return cfg
        
    monkeypatch.setattr(AppConfig, "load", classmethod(mocked_load))
```

### 4.2 System Clock Mocking
To decouple tests from execution time, we patch the clock to return a fixed date (e.g., `2024-06-30`, which is the end of the lateral recovery regime):

```python
# tests/e2e/conftest.py
import datetime

@pytest.fixture(autouse=True)
def mock_b3_clock(monkeypatch):
    fixed_date = datetime.date(2024, 6, 30)
    monkeypatch.setattr("trading_bot.core.clock.today_b3", lambda: fixed_date)
```

### 4.3 Yahoo Finance Mocking
`fetch_universe_yfinance` iterates and calls `fetch_yfinance` which downloads ticker data using `yf.download`. We patch `yf.download` to return simulated DataFrame data read from local CSVs:

```python
# tests/e2e/conftest.py
import pandas as pd

@pytest.fixture
def mock_yfinance(monkeypatch):
    def fake_download(tickers, start=None, end=None, **kwargs):
        # yf.download is always called with a single ticker string (e.g., "PETR4.SA")
        # Load local mock market data CSV
        data_path = Path(__file__).parent / "data/b3_test_universe.csv"
        df_all = pd.read_csv(data_path)
        
        # Filter for the requested ticker and date range
        clean_ticker = tickers.replace(".SA", "")
        df_ticker = df_all[df_all["ticker"] == clean_ticker].copy()
        df_ticker["Date"] = pd.to_datetime(df_ticker["Date"])
        
        if start:
            df_ticker = df_ticker[df_ticker["Date"] >= pd.to_datetime(start)]
        if end:
            df_ticker = df_ticker[df_ticker["Date"] <= pd.to_datetime(end)]
            
        df_ticker = df_ticker.set_index("Date")
        # Structure matches standard yfinance layout
        return df_ticker[["Open", "High", "Low", "Close", "Volume"]]

    monkeypatch.setattr("trading_bot.data.ingestion.yf.download", fake_download)
```

### 4.4 Brapi Mocking
`fetch_brapi` makes calls to the Brapi quote endpoint. We mock `requests.get` to return expected JSON quotes:

```python
# tests/e2e/conftest.py
from unittest.mock import MagicMock

@pytest.fixture
def mock_brapi_api(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if "brapi.dev/api/quote" in url:
            ticker = url.split("/")[-1]
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "results": [{
                    "symbol": ticker,
                    "regularMarketOpen": 30.0,
                    "regularMarketDayHigh": 31.5,
                    "regularMarketDayLow": 29.8,
                    "regularMarketPrice": 31.0,
                    "regularMarketVolume": 1000000,
                }]
            }
            return mock_resp
        raise RuntimeError(f"Unexpected external request to {url}")
        
    monkeypatch.setattr("trading_bot.data.ingestion.requests.get", fake_get)
```

### 4.5 Telegram Bot Client stubbing
When `TelegramClient` is added under M2, E2E tests can patch its message dispatcher or instantiate it in "test mode" to verify alerts:

```python
# tests/e2e/test_e2e_fase1.py
def test_fase1_circuit_breaker_telegram_alert(monkeypatch, mock_yfinance):
    sent_messages = []
    
    # Stub TelegramClient.send_message
    monkeypatch.setattr(
        "trading_bot.core.telegram.TelegramClient.send_message",
        lambda self, text: sent_messages.append(text)
    )
    
    # Run backtest with parameters engineered to trigger the daily loss limit circuit breaker
    # (e.g. sharp market drop in mock data)
    from scripts.fase1_backtest import main
    main()
    
    # Assert circuit breaker message was dispatched
    assert any("Circuit Breaker" in msg for msg in sent_messages)
```

### 4.6 Cedro Technologies Broker execution stubbing
We mock order execution to test paper trading logic, latency, slippage, and rejections:

```python
# tests/e2e/conftest.py
@pytest.fixture
def mock_cedro_broker(monkeypatch):
    # Mocking order placement endpoint or client method
    def fake_send_order(self, ticker, qty, price, order_type):
        return {"status": "success", "order_id": "mock_12345", "filled_qty": qty}
    
    # Will apply monkeypatch to CedroClient.send_order once implemented in M2/M3
```

---

## 5. Execution Commands and Integration

### 5.1 Pytest Configuration
To configure pytest to recognize and execute the test runner suite, create `pytest.ini` in the workspace root:

```ini
# pytest.ini
[pytest]
pythonpath = .
markers =
    unit: Fast unit tests
    integration: Integration tests
    e2e: Slow E2E flow tests
```

### 5.2 Execution Commands
1. **Run Unit and Integration Tests**:
   ```bash
   pytest -m "not e2e"
   ```
2. **Run E2E Suite only**:
   ```bash
   pytest tests/e2e/ -v
   ```
3. **Run All Tests**:
   ```bash
   pytest -v
   ```

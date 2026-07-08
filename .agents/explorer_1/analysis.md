# Meridian System Analysis Report

## 1. Executive Summary

This report presents a thorough static analysis of the Meridian codebase to determine the requirements and plan for Tasks A, B, C, D, and E.

### Status Table of Requirements

| Requirement | Task | Status | Finding / Action Required |
| :--- | :--- | :--- | :--- |
| **R1. Correções Críticas & CI** | Task A | ❌ Failed | `ROUND_TRIP` NameError present in engine; CI workflow file missing. |
| **R2. Cobertura de Testes** | Task B | ❌ Failed | Main modules have 0% coverage; `tests/test_engine.py` stubs are empty (`pass`). |
| **R3. Documentação** | Task C | ⚠️ Outdated | `README.md` contains outdated instructions and lacks a test coverage matrix. |
| **R4. Gestão de Risco & Infra** | Task D | ❌ Missing | Kelly sizing is embedded, not isolated. Matrix generator is missing. Logger, Telegram, and scheduler are missing in `core/`. |
| **R5. Limpeza de Código** | Task E | ⚠️ Warnings | Deprecation warnings, unused imports, and redundant global declarations exist. |

---

## 2. Task A — Critical Corrections & CI (R1)

### 2.1. The `ROUND_TRIP` NameError Bug
In `trading_bot/backtest/engine.py` at line 345, the engine calculates the transaction fee penalty when closing out positions at the end of the backtest period:
```python
pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
```
This raises a `NameError: name 'ROUND_TRIP' is not defined` because the variable `ROUND_TRIP` is not defined globally. 

**Proposed Fix:**
Change line 345 to use the lowercase variable `round_trip` defined on line 122 inside `run_regime_backtest`:
```python
pnl_pct = (float(last["c"]) / pos.entry_price - 1) - round_trip
```

### 2.2. CI Workflow Configuration
The `.github/workflows/` directory does not exist. We propose creating `.github/workflows/ci.yml` as follows:

```yaml
name: CI Pipeline

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install flake8 pytest pytest-cov

      - name: Run flake8 (critical checks)
        run: |
          flake8 . --select=E9,F63,F7,F82

      - name: Run pytest with coverage
        run: |
          pytest tests/ --cov=trading_bot --cov-report=term-missing -v
```

---

## 3. Task B — Test Coverage & Stubs (R2)

### 3.1. Test Coverage Gaps
The current codebase has major test gaps:
- `data/validator.py`: 0% coverage.
- `data/cross_validation.py`: 0% coverage.
- `data/ingestion.py`: 0% coverage.
- `core/config.py`: 0% coverage.
- `core/clock.py`: 0% coverage.
- `backtest/metrics.py`: Partial coverage (only `_trade_sharpe` and `_max_drawdown` tested in `tests/test_metrics.py`).

### 3.2. Implementation of Empty Stubs in `tests/test_engine.py`

#### 3.2.1. `test_engine_gap_abort`
Implement logic that mocks `get_ibov_data` and `compute_signal` to simulate a gap down.
```python
def test_engine_gap_abort(monkeypatch):
    monkeypatch.setattr("trading_bot.backtest.engine.get_ibov_data", lambda x: None)
    
    # We mock compute_signal to return a Candidate with an entry price of 100 and stop at 95.
    called = 0
    def mock_compute_signal(df, ticker, **kwargs):
        nonlocal called
        called += 1
        return Candidate(
            ticker=ticker,
            score=0.8,
            entry_price=100.0,
            stop=95.0,
            target=110.0,
            signal_ts=df["ts"].iloc[-1],
            rsi=60.0,
            volume_ratio=2.5,
            near_support=False,
            signal_details={}
        )
    monkeypatch.setattr("trading_bot.backtest.engine.compute_signal", mock_compute_signal)

    # Provide 200 rows of dummy data to pass the length checks (min_rows/SMA-200)
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(200)]
    prices = [100.0] * 200
    df_data = pd.DataFrame({"ts": dates, "o": prices, "h": prices, "l": prices, "c": prices, "v": [1000]*200})
    
    # Change the 200th day data (entry day) to have a gap down: open=94, stop=95
    df_data.loc[199, "o"] = 94.0
    df_data.loc[199, "l"] = 90.0
    df_data.loc[199, "c"] = 92.0

    data = {"A": df_data}
    
    result = run_regime_backtest(
        data=data,
        regime_name="test_gap",
        start=dates[198],
        end=dates[199],
        capital=1000.0,
        ibov_filter=False
    )
    # The entry should have been aborted because open_price (94) <= stop (95)
    assert len(result.trades) == 0
```

#### 3.2.2. `test_engine_max_positions`
Verify that the engine limits the number of open positions to `max_positions` even if more signals are generated.
```python
def test_engine_max_positions(monkeypatch):
    monkeypatch.setattr("trading_bot.backtest.engine.get_ibov_data", lambda x: None)
    
    def mock_compute_signal(df, ticker, **kwargs):
        return Candidate(
            ticker=ticker,
            score=0.8,
            entry_price=100.0,
            stop=95.0,
            target=110.0,
            signal_ts=df["ts"].iloc[-1],
            rsi=60.0,
            volume_ratio=2.5,
            near_support=False,
            signal_details={}
        )
    monkeypatch.setattr("trading_bot.backtest.engine.compute_signal", mock_compute_signal)

    # Create historical data with 200 rows for 4 tickers
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(200)]
    prices = [100.0] * 200
    df_data = pd.DataFrame({"ts": dates, "o": prices, "h": prices, "l": prices, "c": prices, "v": [1000]*200})
    
    data = {"A": df_data.copy(), "B": df_data.copy(), "C": df_data.copy(), "D": df_data.copy()}
    
    result = run_regime_backtest(
        data=data,
        regime_name="test_max_pos",
        start=dates[198],
        end=dates[199],
        capital=1000.0,
        max_positions=3,
        ibov_filter=False
    )
    # Total active positions should be limited to 3
    # Check open positions inside run_regime_backtest logic:
    # Under test conditions, only 3 trades can exist or be open
    assert len(result.trades) <= 3
```

---

## 4. Task C — Documentation Updates (R3)

We propose the following edits in `README.md`:
1. Correct the installation command on line 12: change `cd trading-bot` to `cd meridian` or root.
2. Remove the outdated pending item: "⚠️ Pendente: informar capital inicial..." on line 25.
3. Append a structured **Test Coverage Table** under a new section "Test Coverage Status".

---

## 5. Task D — Risk Management and Infrastructure (R4)

### 5.1. Isolated Kelly Position Sizer
Currently, position sizing is hardcoded inside `trading_bot/backtest/engine.py`. We propose implementing `trading_bot/risk/position_sizer.py` containing a standard fractional Kelly sizing class:

```python
# trading_bot/risk/position_sizer.py
import logging

logger = logging.getLogger(__name__)

class KellyPositionSizer:
    def __init__(self, kelly_fraction: float = 0.25, max_positions: int = 3):
        self.kelly_fraction = kelly_fraction
        self.max_positions = max_positions

    def calculate_position_size(
        self,
        current_equity: float,
        available_cash: float,
        win_rate: float = 0.40,
        win_loss_ratio: float = 2.0,
    ) -> float:
        """
        Calculates position size using fractional Kelly formula.
        Formula: f* = p - (q / r)
          p = win_rate
          q = 1 - win_rate
          r = win_loss_ratio
        """
        if win_loss_ratio <= 0:
            return 0.0
            
        p = win_rate
        q = 1.0 - p
        r = win_loss_ratio
        
        raw_kelly = p - (q / r)
        fractional_kelly = max(0.0, raw_kelly * self.kelly_fraction)
        
        # Determine slot allocation
        pos_size = current_equity * fractional_kelly
        
        # Bound limits
        max_slot_size = current_equity / self.max_positions
        pos_size = min(pos_size, max_slot_size)
        pos_size = min(pos_size, available_cash)
        
        logger.info(
            "Kelly calculation: raw=%.2f, fractional=%.2f, size=R$%.2f",
            raw_kelly, fractional_kelly, pos_size
        )
        return max(0.0, pos_size)
```

### 5.2. Correlation Returns Matrix Generator
We propose implementing the missing returns matrix generator in `trading_bot/risk/circuit_breaker.py` or `trading_bot/risk/correlation.py`:

```python
# Proposed in trading_bot/risk/circuit_breaker.py
from trading_bot.data.storage import load_ohlcv
from datetime import date, timedelta

def generate_returns_matrix(
    tickers: list[str],
    db_path: str,
    window_days: int = 60,
) -> dict[str, list[float]]:
    """
    Generates a returns matrix dict {ticker: [returns]} for the correlation filter.
    Loads prices from the SQLite database.
    """
    returns_matrix = {}
    end = date.today()
    start = end - timedelta(days=window_days + 20) # pull extra days for window size
    
    for ticker in tickers:
        try:
            df = load_ohlcv(ticker, start=start, end=end, db_path=db_path)
            if df.empty or len(df) < 2:
                continue
            df = df.sort_values("ts")
            # Calculate daily returns %
            pct_returns = df["adj_close"].pct_change().dropna().tolist()
            # Keep only the last window_days elements
            returns_matrix[ticker] = pct_returns[-window_days:]
        except Exception as e:
            logger.error("Failed to generate returns for %s: %s", ticker, e)
            
    return returns_matrix
```

### 5.3. Infrastructure (Logger, Telegram, Scheduler)

We propose adding these modules to `trading_bot/core/`:

- **Structured Logger (`trading_bot/core/logger.py`)**:
  Wraps standard Python logging to format logs as structured JSON lines when configured.
- **Telegram Client (`trading_bot/core/telegram.py`)**:
  Implements standard synchronous/asynchronous sending using `requests` or `python-telegram-bot` to trigger manual confirmations.
- **Scheduler (`trading_bot/core/scheduler.py`)**:
  Using the `schedule` library to manage tasks on cron-like schedules.

---

## 6. Task E — Code Cleanups & Minor Warnings (R5)

1. **SQLite3 PARSE_DECLTYPES Deprecation Warning**:
   In `trading_bot/data/storage.py` at line 45:
   ```python
   conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
   ```
   **Fix:** Remove `detect_types=sqlite3.PARSE_DECLTYPES` and convert timestamp strings manually during database loading using `pd.to_datetime`.
2. **Unused Imports**:
   - `trading_bot/risk/circuit_breaker.py:4`: `from datetime import date`
   - `scripts/fase0_validate_data.py:18`: `import os`
   - `scripts/fase1_backtest.py:10`: `import yaml`
   **Fix:** Remove these lines.
3. **Global Cache Variable in IBOV Cache**:
   In `trading_bot/signals/engine.py` line 89:
   ```python
   global _ibov_cache
   ```
   **Fix:** Remove this line since `_ibov_cache` is a mutable dictionary at module level and only key insertions and lookups are performed, not variable rebinding.

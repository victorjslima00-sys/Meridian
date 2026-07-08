# Analysis and Test Case Design: Meridian Swing Trading System E2E Suite

This document presents a read-only architectural investigation and comprehensive end-to-end (E2E) test case design for the Meridian swing trading system's entry points. It covers codebase entry point analysis, 50 detailed test cases divided into Feature Coverage (Tier 1) and Boundary/Corner cases (Tier 2), and a complete specification of the E2E test infrastructure, mocking mechanisms, and validation criteria.

---

## 1. Codebase Entry Points Analysis

We investigated the two primary system entry points located in the `scripts/` directory:
- `scripts/fase0_validate_data.py` (Data validation and collection)
- `scripts/fase1_backtest.py` (Backtesting simulation engine)

Below is the detailed breakdown of their inputs, arguments, configurations, external dependencies, and outputs.

### 1.1. Script `scripts/fase0_validate_data.py`

#### Purpose
Executes historical data collection, local SQLite database storage, data quality checks, and cross-source validation before any trading simulation runs.

#### Inputs and CLI Arguments
- `--token` (default: `""`): Brapi.dev API token. If not provided via CLI, it falls back to the `brapi_token` in `settings.yaml`.
- `--skip-brapi` (flag): Skip the cross-source validation against the `brapi.dev` API (reducing the security gate confidence).
- `--years` (default: `5`): Integer indicating how many years of historical data to fetch from Yahoo Finance.

#### Configurations (Loaded via `AppConfig.load()`)
- `universe.yaml`: Ticker symbols of the B3 universe (50 active, liquid B3 tickers).
- `settings.yaml`:
  - `data.db_path` (default: `data/trading_bot.db`): Filepath of the local SQLite database.
  - `data.cross_validation.overlap_days` (default: `90`): Window length for Yahoo Finance vs. Brapi overlap.
  - `data.cross_validation.max_divergence_pct` (default: `0.5%`): Allowed divergence in adjusted close price.

#### External Dependencies
- **yfinance** (Web fetching): Fetches years of historical daily candles.
- **brapi.dev** (Web HTTP API): Fetches the most recent daily quote to cross-validate with `yfinance`'s last candle.
- *Note:* It does not connect to Telegram or Cedro, as it only handles database ingestion and data checks.

#### Outputs & Behavior
- **Local DB:** Populates/updates SQLite tables (`ohlcv` schema) with columns: `ticker`, `ts`, `o`, `h`, `l`, `c`, `v`, `adj_close`, `source`.
- **Cross-Validation Logs:** Stores execution reports in `logs/data_validation/cross_validation_YYYYMMDD.json`.
- **Exit Code logic:**
  - Returns `0` (Success) if `gates_ok` is `True`. This requires:
    - At least 90% of configured tickers have retrieved data.
    - Total data quality errors $\le 2$.
    - `cross_status == "passed"` (requires successful API check against Brapi without skipping).
  - Returns `1` (Failure) if any of the above conditions fail (including if `--skip-brapi` was used, which flags `cross_status = "skipped"`).

---

### 1.2. Script `scripts/fase1_backtest.py`

#### Purpose
Executes a multi-regime backtesting simulation for the Donchian Breakout trading strategy, using cached SQLite data, and calculates exit gate metrics.

#### Inputs and CLI Arguments
- No custom arguments parsed (only standard help command support).

#### Configurations (Loaded via `AppConfig.load()`)
- `universe.yaml`: Tick symbols of the B3 universe.
- `settings.yaml`:
  - `signals` section: Breakout period (20d), volume multiplier (2.0x), trend period (SMA-200), RSI maximum limit (75.0), static stop-loss (4%), take-profit target (10%), max holding days (15), and IBOV trend filter (True).
  - `risk` section: Initial capital (R$300.00), Kelly fraction size (0.25), maximum simultaneous positions (3), brokerage costs (0.03%), and spread estimate (0.02%).
  - `backtest` section: The definition of the 3 mandatory historical market regimes:
    - `crise_volatilidade` (2020-03-01 to 2020-09-30) - COVID shock.
    - `alta_juros` (2021-06-01 to 2022-12-31) - Selic hiking cycle.
    - `recuperacao_lateral` (2023-01-01 to 2024-06-30) - Lateral recovery.
    - Gate thresholds: `min_sharpe_per_regime` (0.5) and `min_sharpe_aggregate` (1.0).

#### External Dependencies
- **yfinance** (Web fetching): Specifically called to download IBOVESPA index data (`^BVSP`) to run the trend filter.
- *Note:* Pure historical simulation; no live Telegram confirmation or Cedro broker execution calls occur in this phase.

#### Outputs & Behavior
- **CLI Stdout:** Prints step-by-step logs, regime trade breakdowns, and overall gate results.
- **Exit Code logic:**
  - Always returns `0` (Success) regardless of whether the strategy passed the Sharpe gates (`overall_pass` True/False). To evaluate backtest success, E2E runners must capture stdout and search for the string `"✅ PASSA"` vs `"❌ REPROVA"`.

---

## 2. Test Case Design (Tiers 1 & 2)

We defined 5 distinct core features of the system and drafted 5 Feature Coverage (Tier 1) and 5 Boundary/Corner (Tier 2) test cases for each, totaling 50 E2E test cases.

### Feature A: Historical Data Ingestion & Storage (`fase0` Ingest/Storage)
*Responsible for downloading historical data, normalizing schemas, and writing to the local SQLite DB.*

#### Tier 1: Feature Coverage
1. **DB Schema Creation:** Running `fase0_validate_data.py` on an empty directory successfully creates a valid database file at `data/trading_bot.db` containing the `ohlcv` table with a primary key constraint on `(ticker, ts)`.
2. **Normal Yahoo Ingestion:** Ingesting a standard stock symbol (e.g., `"PETR4"`) retrieves all historic columns and saves rows with source label `"yfinance"`.
3. **Database Insert or Ignore:** Re-running ingestion for already cached date ranges does not throw SQLite integrity/duplicate key errors.
4. **Cache Delta-Start Detection:** Ingesting a ticker that has data stored up to `2026-07-01` verifies that `get_delta_start()` evaluates to `2026-07-02`, requesting only the delta from `yfinance`.
5. **yfinance Column Flattening:** Validates that the ingestion function flattens Yahoo Finance's multi-index DataFrame structures (often returned in newer `yfinance` versions when fetching single tickers) into standard flat columns.

#### Tier 2: Boundary/Corner Cases
6. **Delisted/Empty Ticker Response:** If `yfinance` returns an empty DataFrame (delisted ticker or offline network), the ingestion module handles the empty set cleanly, logging a warning and saving 0 rows without throwing a `TypeError`.
7. **Malformed Source Schema:** Inputting a DataFrame with missing date/timestamp indices or columns raises a clear, caught `ValueError` with a descriptive message rather than failing with an unhandled exception.
8. **Missing Adjusted Close Column:** If `adj_close` or `Adj Close` is completely missing from the raw payload, the system falls back to using `c` (close) as the adjusted close and prints a warning.
9. **Invalid/Negative Years Input:** Running the validate script with `--years -1` or `--years 0` is caught by argument validation or yields a calculated start date equal to today's date, preventing subtraction issues.
10. **Locked SQLite database:** If the database file is write-locked (e.g. accessed by another process), the context manager `_db_connection` rolls back transaction logs safely and prints a clean database lock error.

---

### Feature B: Data Quality Validation (`fase0` Quality Gates)
*Responsible for auditing incoming datasets to spot gaps, splits, or zero-volume anomalies.*

#### Tier 1: Feature Coverage
1. **Clean Quality Audit:** An anomaly-free data series returns `ValidationReport.ok == True` with 0 errors and 0 warnings.
2. **Date Gap (Warning range):** A date gap between 6 and 10 consecutive trading days generates a warning issue in the validation report.
3. **Date Gap (Error range):** A gap greater than 10 consecutive days creates an error issue, flagging `ValidationReport.ok == False`.
4. **Zero Volume Audit:** A trading day with volume `v == 0` generates a warning issue.
5. **Large Price Movement Auditing:** A daily return change between 20% and 40% triggers a `warning`, whereas a change exceeding 40% triggers an `error` flag.

#### Tier 2: Boundary/Corner Cases
6. **Completely Empty Audit Input:** Passing an empty DataFrame to `validate_ohlcv()` returns a validation report containing a single error of type `empty` with severity `error`.
7. **Single-Row Dataset Audit:** Auditing a dataset containing exactly one row does not crash when computing percentage differences or shifting series, returning a clean pass report.
8. **Duplicate Timestamps:** If duplicate rows exist for the same timestamp, the validator sorts them, handles duplicates gracefully without infinite recursion, and triggers a warning or error.
9. **Zero Close Price Handling:** If a price value is `0.0` or negative in the dataset, the daily return percentage check replaces/drops the values safely, avoiding `ZeroDivisionError`.
10. **Weekend/Holiday Boundary:** Verifies that typical 2-day weekend gaps and 1-day B3 market holidays are ignored and do not trigger a date gap warning (since threshold is 5 days).

---

### Feature C: Source Cross-Validation (`fase0` Cross-Source Verification)
*Cross-validates yfinance data against brapi.dev to prevent bad backtests.*

#### Tier 1: Feature Coverage
1. **Cross-Validation Pass:** When last-day close prices from yfinance and brapi.dev are within 0.5% divergence, the validation passes, and the JSON output logs `"status": "passed"`.
2. **Cross-Validation Failure:** If prices diverge by > 0.5%, the system logs `"status": "failed"`, which causes the script to return exit code `1`.
3. **Brapi Validation Skip:** Supplying `--skip-brapi` skips Brapi calls, sets `cross_status = "skipped"`, prints a confidence reduction warning, and exits with `1` (unless manually configured otherwise).
4. **Known Dividend Ex-Date check:** The script checks known historic ex-dates (e.g. PETR4 on 2023-08-14) to confirm that the implied price adjustment is within 15% of the expected dividend (1.337).
5. **JSON Report Generation:** Validates that the report is written to `logs/data_validation/cross_validation_YYYYMMDD.json` containing detailed keys: `passed`, `failed`, `total`, and `results`.

#### Tier 2: Boundary/Corner Cases
6. **Missing Brapi Token in Settings:** If `--token` is empty and `brapi_token` in `settings.yaml` is empty, the script logs a warning and sets `cross_status = "skipped"` instead of crashing.
7. **Brapi Server Timeout:** When Brapi is offline or times out, the exponential backoff mechanism retries up to 3 times before raising a RequestException.
8. **Rate Limiting (429 HTTP Code):** If Brapi responds with HTTP status 429, the retry logic intercepts the error, waits for backoff duration, and logs a clear rate limit exceeded error.
9. **Ticker Mismatch / Not Found:** If a ticker symbol exists on Yahoo but is invalid on Brapi, the cross-validation reports an `"error"` status specifically for that ticker and overall failure, without crashing the run.
10. **yfinance Mismatched Settings Failure:** If downloading the unadjusted yfinance data for consistency check fails (e.g. connection drops), the script catches the error, marks the ticker status as `"error"`, and lists the exception.

---

### Feature D: Backtest Trade Execution Engine (`fase1` Execution/Accounting)
*Simulates the historical trade entries, exits, stop/targets, and capital flows.*

#### Tier 1: Feature Coverage
1. **Breakout Signal Verification:** If price exceeds the 20-day Donchian channel, volume > 2.0x, price > SMA-200, and 50 < RSI < 75, a `Candidate` signal is generated.
2. **Next-Day Entry Fill:** Signals generate orders filled at the next day's open price, initiating an open position.
3. **Take Profit (Target Hit):** An open position closes when the high price matches or exceeds the target price.
4. **Stop Loss (Stop Hit):** An open position closes when the low price falls below or equal to the stop price.
5. **Timeout Exit:** If a position is held for 15 days without hitting stop or target, it is liquidated at the 15th day's close price.

#### Tier 2: Boundary/Corner Cases
6. **Opening Gap Down below Stop:** If a stock opens below the planned stop price on the entry day, the trade is aborted immediately, preventing catastrophic unmanaged losses.
7. **Intraday Double Trigger (Stop vs Target):** If a single day's high is $\ge$ target AND low is $\le$ stop, the system executes the stop-loss conservatively to model the worst-case scenario.
8. **Same-Day Entry and Exit:** If the stop or target price is touched on the day of entry, the trade is recorded as entered and exited on the same day, calculating PnL correctly.
9. **No Available Cash (Sizing Exhaustion):** If `capital_cash` is low (e.g. < R$10.00), the sizing logic blocks new entries even if breakout signals are present.
10. **Corrupt IBOV Index Data:** If IBOV index data fails to load, the trend filter defaults to `True` (unblocked) and logs a warning, rather than halting execution.

---

### Feature E: Performance Metrics & Gate Evaluations (`fase1` Post-Backtest Metrics)
*Evaluates Sharpe ratios, drawdowns, and verifies process exit gates.*

#### Tier 1: Feature Coverage
1. **Aggregate Sharpe Calculation:** Computes the trade-based Sharpe ratio across all combined trades using a 10% risk-free rate.
2. **Maximum Drawdown and Duration:** Tracks the daily MTM equity curve to find the peak-to-trough drop percentage and the recovery period.
3. **Profit Factor Calculation:** Divides the sum of absolute returns from positive trades by the absolute returns from negative trades.
4. **Stress Gap Simulation:** Models the capital impact of an overnight -10% or -15% price gap across all active end-of-period positions.
5. **Sharpe Gate Pass/Fail evaluation:** Validates `overall_pass = True` only if Sharpe aggregate $\ge 1.0$ AND every regime's Sharpe $\ge 0.5$.

#### Tier 2: Boundary/Corner Cases
6. **Statistically Insufficient Trades:** If a backtest regime executes fewer than 3 trades, the calculated Sharpe ratio returns `0.0` to avoid division-by-zero or mathematical distortion.
7. **Zero Variance in Trade Returns:** If all trades return the exact same percentage (zero variance), standard deviation division is bypassed, returning `0.0` safely.
8. **Account Bankruptcy:** If equity falls to $\le 0$, the system records absolute drawdown (100%), halts calculations, and terminates without crashing.
9. **Zero Duration Regime:** If a regime start and end dates are identical, the years divisor is capped at `0.01` to prevent division by zero.
10. **Zero Positions at End of Period:** If no positions are open at the end of a backtest regime, the overnight stress gap test returns `0.0` instead of `NaN`.

---

## 3. Proposed Test Infrastructure

### 3.1. Directory Structure

E2E testing files should be placed under a dedicated directory structure inside `tests/` to separate them from unit tests:

```
tests/
├── e2e/
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures (temporary databases, configs)
│   ├── test_fase0_runner.py    # E2E validation script runner and exit gate checks
│   ├── test_fase1_runner.py    # E2E backtest script runner and stdout parser
│   ├── mock_data/
│   │   ├── yfinance_petr4.csv  # Mock CSV raw files to simulate web downloads
│   │   ├── yfinance_ibov.csv
│   │   └── brapi_petr4.json    # Mock Brapi API responses
│   └── test_live_invariants.py # E2E test suite for live trading safety features
```

### 3.2. Mocking External APIs

#### Mocking yfinance and brapi.dev (Fase 0 & 1)
- We must intercept internet-facing requests during E2E runs.
- **Implementation:** Use the `responses` library or `unittest.mock` to monkeypatch `requests.get` (for Brapi) and `yfinance.download` (for Yahoo).
- Mocks should load static local CSV/JSON files from `tests/e2e/mock_data/` to provide repeatable market price structures.

#### Mocking Telegram (`trading_bot/core/telegram.py`)
Live trading (planned in M2) will implement manual order confirmation.
- **Mocking Strategy:**
  - Mock the `TelegramClient` class methods (e.g. `send_message` and `poll_updates`) using a mock class.
  - Instead of calling the Telegram Bot API, the mock client writes outgoing messages to an internal queue or a local test file (`tests/e2e/telegram_outbox.json`).
  - **Simulating Approvals:** The test runner registers a callback or sets a mock state:
    - *Scenario 1 (Approval):* The mock client returns a simulated user reply containing `"YES"` or `/approve` after a mock order message is received, verifying the broker execution trigger.
    - *Scenario 2 (Rejection):* The mock returns `"NO"` or `/reject`, verifying that the order status transitions to rejected and no trade occurs.
    - *Scenario 3 (Timeout):* The mock does not send a reply. The test runner advances the mock system clock by 10 minutes (matching `confirmation_timeout_minutes`) and verifies that the order is rejected automatically.

#### Mocking Cedro Technologies API
Live trading execution connects to the Cedro API.
- **Mocking Strategy:**
  - Use `responses` to capture HTTP calls directed at `https://cedrotech.com/apis/api-trading`.
  - Simulate the authentication handshake (`api_key` and `api_secret` checks).
  - Return mocked JSON responses for:
    - Order submission (`buy`, `sell` with stop/target bounds).
    - native STOP orders.
    - order status polls (e.g. `"FILLED"`, `"REJECTED"`, `"PENDING"`).
    - Ticker conversions (e.g., matching standard ticker `PETR4` to fractional `PETR4F` when order size requires odd-lot fills).
  - Verify that the broker stubs (`trading_bot/broker/mock.py` or the live adapter) handle HTTP timeout errors, connection breaks, and API-returned errors without crashing.

### 3.3. Verifying Exit Codes and Outputs

The E2E test runner should execute scripts as subprocesses using a helper function in `conftest.py`:

```python
import subprocess
import sys

def run_script(script_name, args=[]):
    cmd = [sys.executable, f"scripts/{script_name}"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "."} # ensures module resolve
    )
    return result
```

#### Verification Criteria for Fase 0
- **Pass Case:** Run `run_script("fase0_validate_data.py", ["--token", "MOCK_TOKEN"])`. Verify that:
  - `result.returncode == 0`.
  - `result.stdout` contains `"✅ FASE 0 CONCLUÍDA"`.
  - The SQLite file is created and populated.
- **Fail Case:** Run `run_script("fase0_validate_data.py", ["--skip-brapi"])`. Verify that:
  - `result.returncode == 1` (since skipping Brapi marks validation as failed/confidence-reduced).
  - `result.stderr` or `result.stdout` contains `"❌ FASE 0 COM PROBLEMAS"` or indicates cross-validation was skipped.

#### Verification Criteria for Fase 1
- **Process execution:** Run `run_script("fase1_backtest.py")`. Verify that:
  - `result.returncode == 0` (always, due to script design).
- **Gate Performance Check:**
  - Parse `result.stdout` to retrieve the performance gates.
  - If target Sharpe ratios are met: verify `result.stdout` contains `"Sharpe Agregado: ... (✅ PASSA)"`.
  - If target Sharpe ratios fail: verify `result.stdout` contains `"Sharpe Agregado: ... (❌ REPROVA)"`.

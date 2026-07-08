# Meridian Swing Trading System: Integration & End-to-End Test Suite Design

## 1. Executive Summary
This report analyzes the core entry points of the Meridian swing trading system (`fase0_validate_data.py` and `fase1_backtest.py`), details their parameters, external dependencies, and execution logic, and provides a comprehensive design for Tier 3 (Cross-Feature Combinations) and Tier 4 (Real-World Application Scenarios) integration test cases. It also outlines robust structuring and mocking methodologies to achieve opaque-box end-to-end test execution.

---

## 2. Codebase Investigation & Entry Points

### 2.1. Fase 0: Data Ingestion and Quality Validation (`scripts/fase0_validate_data.py`)
This script serves as the gatekeeper for data quality before any backtesting or trading occurs. It initializes the local database, ingests historical OHLCV data, performs quality checks, and optionally cross-validates against an external source.

* **Inputs & Arguments**:
  * `--token` (default: `""`): API token for `brapi.dev` quote validation. Can also be set in `config/settings.yaml` under `data.brapi_token`.
  * `--skip-brapi` (action: `store_true`): Skip cross-validation against `brapi.dev` (uses only historical `yfinance` data).
  * `--years` (default: `5`): Length of historical data to download in years.
* **Configurations**:
  * Loaded from `config/settings.yaml` and `config/universe.yaml` via `AppConfig.load()`.
  * Target universe is parsed from `universe.yaml` and injected into the config's `_universe` key.
  * DB location is loaded from `data.db_path` (default: `data/trading_bot.db`).
  * Cross-validation parameters: `data.cross_validation.overlap_days` (default: `90`) and `data.cross_validation.max_divergence_pct` (default: `0.5%`).
* **External Dependencies**:
  * **yfinance**: Fetches historical OHLCV data for all tickers via `fetch_universe_yfinance` starting from $today - years$.
  * **brapi.dev**: Fetches the daily candle for cross-validation via `run_cross_validation` if `--skip-brapi` is not set and a token is provided.
  * **SQLite Database**: Local SQLite connection managed via `trading_bot.data.storage`.
  * **Clock**: Uses Brasília time zone via `today_b3()` in `trading_bot.core.clock`.
* **Outputs**:
  * SQLite DB file containing populated `ohlcv` table with schema: `(ticker, ts, o, h, l, c, v, adj_close, source, created_at)`.
  * Multi-level execution log printed to console and saved (if configured).
  * A JSON report file in `logs/data_validation/cross_validation_YYYYMMDD.json` summarizing the results.
  * **Exit Code**: `0` if quality gates are passed, `1` if they fail.
* **Quality Gates (Blocking Rules)**:
  * For the script to succeed (returning exit code `0`), `gates_ok` must be `True`, which requires:
    1. **Data Completeness**: Data must be retrieved for at least 90% of the universe tickers (`len(data) >= int(len(tickers) * 0.9)`).
    2. **Data Quality**: Total quality errors must be $\le 2$ (allowing minor corp events).
    3. **Cross-Validation Status**: `cross_status` must equal `"passed"`.
  * *Critical Observation*: If `--skip-brapi` is used or no token is provided, `cross_status` becomes `"skipped"`, which causes `gates_ok` to evaluate to `False`, forcing the script to exit with code `1`.

### 2.2. Fase 1: Backtesting Engine (`scripts/fase1_backtest.py`)
This script executes the backtest engine across three distinct historical market regimes, evaluates trade metrics, and prints an aggregated scorecard.

* **Inputs & Arguments**:
  * Accepts standard arguments, but does not use custom CLI options (only basic configuration parsing).
* **Configurations**:
  * Loaded via `AppConfig.load()`.
  * `signals`: breakout parameters (`breakout_period`, `volume_multiplier`, `sma_trend_period`, `rsi_max`, `stop_pct`, `target_pct`, `ibov_filter`, `max_hold_days`).
  * `risk`: capital allocations (`capital_initial` default: `300.00`, `kelly_fraction` default: `0.25`, `max_positions` default: `3`, transaction costs: `brokerage_pct`, `spread_est_pct`).
  * `backtest`: market regimes list, Sharpe thresholds (`min_sharpe_per_regime`, `min_sharpe_aggregate`).
* **External Dependencies**:
  * **yfinance**: Dynamically downloads historical OHLCV data for universe tickers starting from `2019-01-01` (to allow indicators to warm up) and download `^BVSP` (IBOV) data for macro filtering.
* **Outputs**:
  * Detailed print of strategy performance across three regimes:
    1. `crise_volatilidade` (2020-03-01 to 2020-09-30)
    2. `alta_juros` (2021-06-01 to 2022-12-31)
    3. `recuperacao_lateral` (2023-01-01 to 2024-06-30)
  * Scores on Sharpe ratio per regime and aggregated.
* **Known Codebase Issues**:
  * **NameError in `trading_bot/backtest/engine.py:345`**: In the regime cleanup block, the code references `ROUND_TRIP` (uppercase) which is undefined in that scope. The local variable defined on line 122 is lowercase `round_trip`. This causes the script to crash at the end of a backtest run if there are any open positions left.

---

## 3. Tier 3: Cross-Feature Combinations (Pairwise Coverage Design)

Pairwise testing ensures that every pair of feature states is combined in at least one test case, detecting integration bugs caused by unexpected interactions.

### 3.1. Parameter Space Definition
The integration test suite identifies 6 critical variables:

1. **Market Trend (`M`)**:
   * `UP`: IBOV is above SMA-50 (trading allowed).
   * `DOWN`: IBOV is below SMA-50 (trading blocked).
   * `TRANS`: IBOV crosses SMA-50 mid-period (regime shift).
2. **Signal Conditions (`S`)**:
   * `NONE`: No stock signals generated.
   * `SINGLE`: Exactly one stock generates a signal.
   * `MULTI`: Multiple stocks generate signals (exceeding available slots).
3. **Correlation Limit (`C`)**:
   * `PASS`: Candidate has correlation $\le 0.70$ with existing positions.
   * `FAIL`: Candidate has correlation $> 0.70$ with existing positions.
4. **Position Sizing (`P`)**:
   * `NORM`: Normal Kelly fraction allocation within available cash.
   * `CAP`: Kelly demands more than available cash; allocation must cap at cash.
5. **Execution Fill (`E`)**:
   * `CLEAN`: Next-day Open price is above stop price (successful entry).
   * `ABORT`: Next-day Open price is below stop price (slippage/gap abort).
   * `INTRADAY`: High/Low hits target or stop on the entry day itself.
6. **Account Risk / Circuit Breaker (`R`)**:
   * `SAFE`: Normal operations (no circuit breakers triggered).
   * `CB_DAY`: Daily loss limit is breached.
   * `CB_INC`: Inception drawdown limit is breached.

### 3.2. Pairwise Test Case Matrix
Using orthogonal/all-pairs methodology, the following 15 test configurations provide 100% coverage of all pairwise combinations:

| Test ID | Market Trend (`M`) | Signals (`S`) | Correlation (`C`) | Sizing (`P`) | Execution Fill (`E`) | Account Risk (`R`) | Expected Behavioral Result / Assertion |
|---|---|---|---|---|---|---|---|
| **T3-01** | `UP` | `NONE` | `PASS` | `NORM` | `CLEAN` | `SAFE` | No positions opened. Cash remains unchanged. |
| **T3-02** | `UP` | `SINGLE` | `PASS` | `CAP` | `ABORT` | `CB_DAY` | Order generated, but execution is aborted due to gap down. Circuit breaker triggers due to other losses. |
| **T3-03** | `UP` | `MULTI` | `FAIL` | `NORM` | `INTRADAY` | `CB_INC` | High score signals evaluated, blocked by correlation. Inception drawdown triggers, blocking future signals. |
| **T3-04** | `DOWN` | `NONE` | `FAIL` | `CAP` | `INTRADAY` | `CB_DAY` | IBOV filter blocks execution. No positions evaluated. Daily loss CB active. |
| **T3-05** | `DOWN` | `SINGLE` | `PASS` | `NORM` | `ABORT` | `CB_INC` | IBOV filter blocks execution. Single signal ignored. Inception CB active. |
| **T3-06** | `DOWN` | `MULTI` | `PASS` | `CAP` | `CLEAN` | `SAFE` | IBOV filter blocks execution. Portfolio remains empty despite multiple valid signals. |
| **T3-07** | `TRANS` | `NONE` | `PASS` | `CAP` | `INTRADAY` | `CB_INC` | Transition from uptrend to downtrend. New entries blocked post-transition. |
| **T3-08** | `TRANS` | `SINGLE` | `FAIL` | `NORM` | `CLEAN` | `CB_DAY` | Single signal generated during uptrend is blocked due to high correlation. Daily loss CB triggers. |
| **T3-09** | `TRANS` | `MULTI` | `PASS` | `NORM` | `ABORT` | `SAFE` | Multiple signals during uptrend. Order execution aborted due to gap down. |
| **T3-10** | `UP` | `SINGLE` | `FAIL` | `NORM` | `INTRADAY` | `SAFE` | Single signal blocked by correlation check. Cash remains unallocated. |
| **T3-11** | `UP` | `MULTI` | `PASS` | `CAP` | `CLEAN` | `SAFE` | Multiple signals, top scores selected, sized up to cash limits, filled cleanly. |
| **T3-12** | `DOWN` | `SINGLE` | `FAIL` | `NORM` | `INTRADAY` | `SAFE` | Blocked by IBOV trend. |
| **T3-13** | `TRANS` | `MULTI` | `FAIL` | `CAP` | `CLEAN` | `SAFE` | Top signals filtered by correlation. Surviving signals filled cleanly during uptrend phase. |
| **T3-14** | `UP` | `MULTI` | `PASS` | `NORM` | `ABORT` | `CB_DAY` | Signals generated, aborted on gap down. Daily loss limit evaluated and triggered on existing assets. |
| **T3-15** | `TRANS` | `SINGLE` | `PASS` | `CAP` | `INTRADAY` | `SAFE` | Transition to uptrend. Position sized to cash, filled, and exited intraday. |

---

## 4. Tier 4: Real-World Application Scenarios (End-to-End Scenarios)

These five integration scenarios simulate B3 microstructures, risk limits, and network anomalies.

### Scenario 1: Sudden Market Crash & Multi-Level Circuit Breakers
* **Objective**: Verify that rapid portfolio devaluation triggers daily loss, rolling 30d, and inception drawdown circuit breakers in sequence, halting trading and sending Telegram notifications.
* **Prerequisites**: Initial capital R$ 300.00. Configuration loaded with `daily_loss_limit = -0.03`, `drawdown_rolling_30d = -0.06`, and `drawdown_inception = -0.08`. Portfolio holds PETR4, VALE3, ITUB4.
* **Execution Steps**:
  1. Set base date to `2026-07-06`. Equity is R$ 300.00.
  2. Mock `yfinance` to simulate a systemic gap down on `2026-07-07` where all 3 assets open 5% lower.
  3. Run intraday price ticks that drop asset values further, pushing equity to R$ 290.00 (a 3.3% loss).
  4. Trigger a price recovery, then drop again on `2026-07-08` to R$ 280.00 (cumulative 6.6% loss).
  5. Mock another drop on `2026-07-09` to R$ 274.00 (cumulative 8.6% loss).
* **Expected Outcomes**:
  * On `2026-07-07` at R$ 290.00, the **Daily Loss Circuit Breaker** triggers. A warning log is generated, and a Telegram alert is sent. New order generation is disabled.
  * On `2026-07-08` at R$ 280.00, the **30-day Rolling Drawdown Circuit Breaker** triggers (loss > 6.0%).
  * On `2026-07-09` at R$ 274.00, the **Inception Drawdown Circuit Breaker** triggers (loss > 8.0%).
* **Verification Criteria**:
  * Verify that `CircuitBreaker.check` returns `triggered=True` with the exact breach reason.
  * Confirm that the backtest engine does not accept new candidates once any circuit breaker is triggered.
  * Verify that a Telegram alert mock captures the outgoing warning message for each trigger.

### Scenario 2: High Correlation Sector Clustering & Sizing Blocks
* **Objective**: Validate that the system correctly blocks candidates in the same sector (e.g., Finance) to avoid risk concentration, using correlation matrix evaluations over a 60-day window.
* **Prerequisites**: The bot currently holds ITUB4. The `universe.yaml` sectors are loaded (ITUB4, BBDC4, BBAS3 are all labeled `financeiro`). `correlation_max` is set to `0.70`.
* **Execution Steps**:
  1. Mock daily return series for the past 60 days where ITUB4, BBDC4, and BBAS3 have a correlation coefficient of `0.85`.
  2. Simulate the current day where BBDC4 (Score: `0.88`) and BBAS3 (Score: `0.82`) both generate breakout buy signals.
  3. Feed these candidates into the risk control module.
* **Expected Outcomes**:
  * The signal scan prioritizes BBDC4.
  * The correlation check calculates Pearson correlation between BBDC4 and the open position ITUB4.
  * Since $0.85 > 0.70$, BBDC4 is blocked, and an info log is written: `"Candidato BBDC4 bloqueado por alta correlação (0.85) com ITUB4"`.
  * The system then evaluates BBAS3. Since its correlation with ITUB4 is also $0.85 > 0.70$, it is also blocked.
* **Verification Criteria**:
  * Assert that `check_correlation` returns `False` for both BBDC4 and BBAS3.
  * Assert that no buy order is dispatched for BBDC4 or BBAS3.
  * Verify the portfolio contains only ITUB4 at the end of the step.

### Scenario 3: Portfolio Sizing under Cash Constraints (Kelly vs. Available Cash)
* **Objective**: Verify that the position sizer caps trades correctly when the Kelly sizing request exceeds the available cash in the account, preventing negative cash errors.
* **Prerequisites**: Portfolio capital is R$ 300.00. Sizer configured with `kelly_fraction = 0.25`, `max_positions = 3`. Account has R$ 260.00 allocated across two positions (PETR4, VALE3), leaving R$ 40.00 in cash.
* **Execution Steps**:
  1. Generate a strong buy signal for WEGE3 (Score: `0.90`).
  2. Run the position sizer logic:
     $$\text{Position Size} = \text{Total Equity} \times \frac{\text{Kelly Fraction}}{\text{Max Positions}} = 300 \times \frac{0.25}{3} = \text{R\$ } 25.00$$
  3. Validate that R$ 25.00 is less than R$ 40.00 available cash. Order should execute with R$ 25.00.
  4. Now, simulate a scenario where `kelly_fraction = 0.50`.
     $$\text{Position Size} = 300 \times \frac{0.50}{3} = \text{R\$ } 50.00$$
  5. Since R$ 50.00 exceeds the R$ 40.00 available cash, the position size must be capped at exactly R$ 40.00 (the cash constraint).
* **Expected Outcomes**:
  * In the first case, WEGE3 is opened with R$ 25.00 allocated cash (leaving R$ 15.00).
  * In the second case, WEGE3 is opened with R$ 40.00 allocated cash (leaving R$ 0.00).
  * If cash is below the minimum allocation threshold (e.g., R$ 5.00), the position entry must be aborted entirely.
* **Verification Criteria**:
  * Assert that post-trade cash is never negative.
  * Confirm that allocations match the expected capped cash value.

### Scenario 4: Corporate Actions (Ex-Dividend) & Historical Adjustments (Fase 0 & Fase 1)
* **Objective**: Confirm that the data ingestion and validation pipelines correctly handle corporate actions, preventing fake "large move" triggers in Fase 0 and false stop-loss exits in Fase 1.
* **Prerequisites**: PETR4 historical data contains a R$ 3.35 dividend payout on `2022-12-01`.
* **Execution Steps**:
  1. Run `fase0_validate_data.py` on PETR4 using `auto_adjust=False` (unadjusted prices) vs `auto_adjust=True` (adjusted prices).
  2. In the unadjusted price series, PETR4 drops from R$ 30.00 (on `2022-11-30`) to R$ 26.65 (on `2022-12-01`), representing an unadjusted drop of 11.16%.
  3. Run the validation checks on this series.
  4. Run `fase1_backtest.py` across `alta_juros` (which covers 2022-12-01).
* **Expected Outcomes**:
  * In Fase 0, the unadjusted series should raise a quality warning for `large_move` if it exceeds the daily threshold.
  * In the adjusted series (where the pre-dividend price is adjusted down to R$ 26.65, resulting in a 0% return), no warning should be raised.
  * In Fase 1, the backtest must run on adjusted data so that the dividend drop does not trigger a false stop-loss exit (since the stop is set at 4%).
* **Verification Criteria**:
  * Assert that the validation report (`ValidationReport`) has `ok=True` when running on adjusted data.
  * Confirm that the PETR4 trade in the backtest does not exit on `2022-12-01` due to a "stop" event.
  * Verify that the implied dividend check in `validate_ticker_adjustment_consistency` matches the expected payout of R$ 3.35 within 15% tolerance.

### Scenario 5: Scheduler Lifecycle, Manual Approvals, and Notification Outages
* **Objective**: Test the production lifecycle loop, verifying that if the Telegram notification service is down, orders in `manual` confirmation mode fail-safe (abort/expire) rather than executing automatically.
* **Prerequisites**: System configured with `execution.mode = "manual"` and `confirmation_timeout_minutes = 10`.
* **Execution Steps**:
  1. Trigger the scheduler at post-market time `18:00`.
  2. Scan the universe and generate a buy signal for VALE3.
  3. Mock the Telegram API to return an HTTP `503 Service Unavailable` error, simulating a network outage.
  4. Wait for 10 virtual minutes to elapse without user confirmation.
* **Expected Outcomes**:
  * The system attempts to send a confirmation prompt via Telegram.
  * Upon failure, the system logs a critical error, retries up to 3 times, and then halts the message queue.
  * Because the execution mode is `manual`, the order is held in a `pending_approval` state.
  * Once the 10-minute timeout is reached, the order is marked `expired` and discarded. No trade is executed.
* **Verification Criteria**:
  * Assert that no order is sent to the broker mock (Cedro).
  * Assert that the order state transition is: `created` $\to$ `pending` $\to$ `expired`.
  * Confirm that the log files contain the Telegram client exceptions and the final timeout expiry event.

---

## 5. Structuring and Mocking Strategies

To implement these integration tests as opaque-box verification scripts, we will use a structured mocking architecture.

```
tests/
├── E2E/
│   ├── conftest.py               # Shared fixtures, global configuration mocks, DB hooks
│   ├── test_e2e_fase0.py         # Opaque-box testing of scripts/fase0_validate_data.py
│   ├── test_e2e_fase1.py         # Opaque-box testing of scripts/fase1_backtest.py
│   ├── test_e2e_scenarios.py     # Tier 4 real-world integration scenarios
│   └── test_e2e_pairwise.py      # Tier 3 pairwise combination matrix runner
```

### 5.1. Mocking External APIs

#### 1. Mocking `yfinance`
`yfinance` downloads data from Yahoo Finance. We can mock its `download` method to return pre-configured pandas DataFrames containing our specific scenario prices:

```python
import pytest
import pandas as pd
from datetime import date

@pytest.fixture
def mock_yf_download(monkeypatch):
    def _mock_download(ticker, start, end, **kwargs):
        # Generate dummy dataframe matching the expected schema
        dates = pd.date_range(start=start, end=end, freq='B')
        df = pd.DataFrame({
            "Open": 100.0,
            "High": 102.0,
            "Low": 98.0,
            "Close": 100.0,
            "Volume": 10000,
            "Adj Close": 100.0
        }, index=dates)
        df.index.name = "Date"
        return df
    
    monkeypatch.setattr("yfinance.download", _mock_download)
```

#### 2. Mocking `brapi.dev` Quotes
`brapi.dev` quotes are retrieved using `requests.get`. We mock the `requests.get` response:

```python
class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code
    
    def json(self):
        return self.json_data
    
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP Error")

@pytest.fixture
def mock_brapi_api(monkeypatch):
    def _mock_get(url, params=None, **kwargs):
        ticker = url.split("/")[-1]
        dummy_response = {
            "results": [{
                "symbol": ticker,
                "regularMarketPrice": 100.0,
                "regularMarketOpen": 100.0,
                "regularMarketDayHigh": 102.0,
                "regularMarketDayLow": 98.0,
                "regularMarketVolume": 10000,
                "historicalDataPrice": [{
                    "date": 1782384000,  # timestamp
                    "open": 100.0,
                    "high": 102.0,
                    "low": 98.0,
                    "close": 100.0,
                    "volume": 10000,
                    "adjustedClose": 100.0
                }]
            }]
        }
        return MockResponse(dummy_response)
    
    monkeypatch.setattr("requests.get", _mock_get)
```

#### 3. Mocking Telegram Notifications
We mock `TelegramClient` to record outgoing messages in a list for assertions:

```python
class MockTelegramClient:
    def __init__(self, token=None, chat_id=None):
        self.sent_messages = []

    def send_message(self, message: str) -> bool:
        self.sent_messages.append(message)
        return True

@pytest.fixture
def mock_telegram(monkeypatch):
    # Patch the export in trading_bot.core.telegram if it exists
    # or monkeypatch during execution
    pass
```

### 5.2. Mocking Database & Filesystem Control
For isolated execution, tests should not overwrite production databases. We use `tmp_path` to write configuration overrides:

```python
@pytest.fixture
def temp_settings(tmp_path):
    # Create copy of settings pointing to a temporary DB path
    temp_db = tmp_path / "test_trading_bot.db"
    settings_content = f"""
    data:
      db_path: "{temp_db}"
      brapi_token: "MOCK_TOKEN"
      cross_validation:
        overlap_days: 10
        max_divergence_pct: 0.5
    """
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(settings_content)
    return settings_file, temp_db
```

### 5.3. Time Travel (Clock Control)
To simulate the progression of days (e.g. testing the 15-day timeout or the rolling 30d drawdown), we mock `today_b3` to return controlled dates:

```python
class MockClock:
    def __init__(self, start_date):
        self.current_date = start_date

    def today(self):
        return self.current_date

    def advance_days(self, days):
        self.current_date += timedelta(days=days)

@pytest.fixture
def mock_clock(monkeypatch):
    clock = MockClock(date(2026, 7, 7))
    monkeypatch.setattr("trading_bot.core.clock.today_b3", clock.today)
    return clock
```

# Handoff Report - E2E Test Runner Design Recommendation

## 1. Observation
1. **Scope and Entry Points**: In `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/sub_orch_e2e/SCOPE.md`, the E2E milestone specifies:
   * "Opaque-box entry points: `python scripts/fase1_backtest.py` and `python scripts/fase0_validate_data.py`." (line 17)
   * "Verification of safety invariants (Telegram verification, circuit breaker, timeout, paper trading mode)." (line 6)
2. **Current Test Framework**: 
   * Running `pytest` in `/Users/mac/.gemini/antigravity/scratch/meridian/` collects 18 tests flat under `tests/` which pass:
     `============================== 18 passed in 0.83s ==============================`
   * There are no active E2E or network-mocking tests present under `tests/`.
3. **API Hardcoding**: In `/Users/mac/.gemini/antigravity/scratch/meridian/trading_bot/data/ingestion.py`:
   * Yahoo Finance API is called via `yf.download(yf_ticker, ...)` on lines 119-126.
   * Brapi.dev API is called via `requests.get(url, params=params, timeout=10)` on line 180.
4. **Dynamic Clock**: In `/Users/mac/.gemini/antigravity/scratch/meridian/trading_bot/core/clock.py` line 4, `today_b3()` dynamically returns the system day:
   `return datetime.now(ZoneInfo("America/Sao_Paulo")).date()`
5. **Config Parsing**: Configuration is loaded in `trading_bot/core/config.py` using `AppConfig.load()` which defaults to relative paths `"config/settings.yaml"` and `"config/universe.yaml"`.

---

## 2. Logic Chain
1. To run opaque-box E2E tests in a `CODE_ONLY` environment, we must prevent the application from making real network requests to `yfinance` and `brapi.dev` (from Obs 3) and prevent it from altering the main SQLite database.
2. If we execute the scripts via python subprocesses (`subprocess.run`), we would need to mock network calls by hosting a local HTTP mock server and proxying traffic, which is highly complex and brittle.
3. However, if we execute the entry points in-process under `pytest` by importing their `main()` functions, we can leverage `monkeypatch` to directly intercept `yf.download` and `requests.get` at the import module level (from Obs 3).
4. Since `today_b3()` relies on system time (from Obs 4), tests executed on different dates would result in different window starts and data ranges. Monkeypatching `today_b3` to a constant test date solves this and guarantees reproducibility.
5. In-process execution also allows us to mock config loaders (from Obs 5) to redirect file loads to sandboxed configuration/database directories, ensuring that test runs do not contaminate production databases.

---

## 3. Caveats
* **External Implementations**: M2 is planned to implement `TelegramClient` (`trading_bot/core/telegram.py`) and Cedro broker integration stubs (`trading_bot/broker/mock.py`). Our E2E mocking design relies on the assumption that these modules will exist when M2 begins implementation.
* **NameError in Backtest**: We observed a capitalization error `ROUND_TRIP` (instead of `round_trip`) on line 345 of `trading_bot/backtest/engine.py`. This issue is already listed under Milestone M1 and must be resolved by the M1 implementer before E2E tests for the backtest engine can run.

---

## 4. Conclusion
We recommend an **in-process E2E test runner design using pytest** placed under `tests/e2e/`. By mocking `yf.download` and `requests.get` globally in `conftest.py`, E2E tests can run offline with mock B3 market CSV data. Safety invariants (Telegram alerts, circuit breakers) can be tested by engineering specific market scenarios in the mock CSV data and intercepting message payloads.

---

## 5. Verification Method
1. Inspect the detailed design and implementation details written in `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_e1_3/analysis.md`.
2. Confirm the existing test suite continues to pass by running:
   ```bash
   pytest
   ```
3. Verify that the proposed folder structure fits under the standard layout:
   * Source files reside under `trading_bot/`
   * Tests reside under `tests/`
   * No codebase or test files are placed under `.agents/`.

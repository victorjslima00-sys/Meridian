# Handoff Report - Meridian Codebase Analysis

## 1. Observation

- **pytest output**:
  The command `pytest tests/ -v` returned 18 passing tests:
  ```
  tests/test_engine.py::test_engine_gap_abort PASSED
  tests/test_engine.py::test_engine_max_positions PASSED
  ...
  ============================= 18 passed in 11.33s ==============================
  ```
- **Empty test stubs in `tests/test_engine.py`**:
  Line 51 contains:
  ```python
  pass # Esqueleto para desenvolvimento futuro de testes avançados
  ```
  Line 55 contains:
  ```python
  pass
  ```
- **Undefined variable `ROUND_TRIP` in `trading_bot/backtest/engine.py`**:
  Line 345 contains:
  ```python
  pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
  ```
  There is no variable named `ROUND_TRIP` defined globally or imported in `trading_bot/backtest/engine.py`. The variable defined at the function start is `round_trip` (lowercase, line 122).
- **Position Sizing implementation**:
  In `trading_bot/backtest/engine.py` line 270-272:
  ```python
  equity_now = capital_cash + sum(p.capital for p in open_positions.values())
  pos_size = equity_now * kelly_fraction / max_positions
  ```
  There is no position sizer class or function in `risk/` or `execution/`.
- **Correlation matrix check**:
  In `trading_bot/risk/circuit_breaker.py` line 70:
  ```python
  def check_correlation(
      candidate_ticker: str,
      open_tickers: list[str],
      returns_matrix: dict[str, list[float]],
      correlation_max: float = 0.7
  ) -> bool:
  ```
  There is no code in the `trading_bot/` codebase that computes or generates the `returns_matrix` argument.
- **Unused modules in `core/`**:
  `trading_bot/core/` contains only `__init__.py`, `clock.py`, and `config.py`. Logger, Telegram, and scheduler modules are missing.
- **SQLite3 deprecation warning**:
  In `trading_bot/data/storage.py` line 45:
  ```python
  conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
  ```
- **Unused imports**:
  - `trading_bot/risk/circuit_breaker.py` line 4: `from datetime import date`
  - `scripts/fase0_validate_data.py` line 18: `import os`
  - `scripts/fase1_backtest.py` line 10: `import yaml`
- **Global cache keyword**:
  In `trading_bot/signals/engine.py` line 89:
  ```python
  global _ibov_cache
  ```

---

## 2. Logic Chain

1. **`ROUND_TRIP` Bug**:
   Because `ROUND_TRIP` (uppercase) is used in line 345 but never defined in the module, any backtest run that closes positions via the `end_of_period` exit reason will crash with a `NameError`. The correct variable name is `round_trip` (lowercase, defined on line 122).
2. **Empty Test Stubs**:
   Because `test_engine_gap_abort` and `test_engine_max_positions` only contain `pass`, they pass the test suite successfully without asserting any actual engine behavior. Implementing actual logic is necessary to elevate coverage and guarantee code correctness.
3. **Test Gaps**:
   No test files exist for `validator.py`, `cross_validation.py`, `ingestion.py`, `config.py`, and `clock.py`. Thus, these modules have 0% test coverage.
4. **Position Sizing and Correlation**:
   The current Kelly sizing is actually a flat fractional allocation and is embedded inside `backtest/engine.py`, which violates the requirement of being decoupled for live execution. Additionally, `check_correlation` cannot be used in a live environment without a returns matrix generator.
5. **Warnings**:
   `sqlite3.PARSE_DECLTYPES` is deprecated starting with Python 3.12 and triggers runtime warnings. Unused imports and redundant `global` keywords pollute the namespace and trigger lint warnings.

---

## 3. Caveats

- We assumed that the local SQLite database `/Users/mac/.gemini/antigravity/scratch/meridian/data/trading_bot.db` is populated with correct, clean data for all 50 tickers from B3.
- We did not verify the integration of Cedro Technologies broker APIs because no commercial credentials or API urls were supplied.

---

## 4. Conclusion

The Meridian automated trading system has functional breakout signals but is hindered by critical bugs (the `ROUND_TRIP` NameError), missing risk/infrastructure components (Kelly sizer, returns matrix generator, Telegram/scheduler in `core/`), and 0% test coverage across multiple critical modules. Correcting these errors and implementing the proposed architectures is required to safely run the bot.

---

## 5. Verification Method

To verify the codebase status:
1. Run `pytest tests/ -v` to ensure the current tests pass.
2. Confirm the `NameError` by calling `python scripts/fase1_backtest.py` (which will fail if any open positions exist at the end of a backtest regime).
3. Inspect `trading_bot/backtest/engine.py:345` to verify the uppercase `ROUND_TRIP` variable name.
4. Check coverage reports (using `pytest --cov=trading_bot tests/` once `pytest-cov` is installed) to confirm 0% coverage on `validator.py`, `cross_validation.py`, `ingestion.py`, `config.py`, and `clock.py`.

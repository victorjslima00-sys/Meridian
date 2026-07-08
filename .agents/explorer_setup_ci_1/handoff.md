# Handoff Report - Milestone 1: Setup & CI

## 1. Observation
- Inspected file `/Users/mac/.gemini/antigravity/scratch/meridian/trading_bot/backtest/engine.py` (lines 320 to 370).
- Observed the following verbatim code snippet at lines 341-347:
```python
    for ticker, pos in open_positions.items():
        df_t = regime_data.get(ticker)
        if df_t is not None and not df_t.empty:
            last = df_t.iloc[-1]
            pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
            pnl_abs = pos.capital * pnl_pct
            capital_cash += pos.capital + pnl_abs   # ← devolve capital
```
- Inspected lines 100 to 130 of the same file and observed the following local variable definition on line 122:
```python
    round_trip = (brokerage_pct + spread_pct) * 2
```
- Ran `pytest` locally which successfully collected and passed 18 tests:
```
tests/test_engine.py ..                                                  [ 11%]
tests/test_metrics.py ....                                               [ 33%]
tests/test_risk.py .......                                               [ 72%]
tests/test_signals.py .....                                              [100%]
============================== 18 passed in 2.86s ==============================
```

## 2. Logic Chain
1. At line 345 in `trading_bot/backtest/engine.py`, the variable `ROUND_TRIP` (uppercase) is used in the calculation of `pnl_pct`.
2. A search across the `trading_bot/backtest/engine.py` file indicates that `ROUND_TRIP` (uppercase) is not defined anywhere, neither globally nor inside the `run_backtest` function scope.
3. However, inside the `run_backtest` function at line 122, `round_trip` (lowercase) is defined as `round_trip = (brokerage_pct + spread_pct) * 2`.
4. Therefore, the use of `ROUND_TRIP` on line 345 will raise a `NameError: name 'ROUND_TRIP' is not defined` when Python attempts to execute that line during backtest finalization.
5. Changing `ROUND_TRIP` to `round_trip` resolves the reference error.

## 3. Caveats
- The current test suite (`tests/test_engine.py`) consists of skeletons/pass placeholders and does not execute the actual backtest execution loop that triggers line 345. Thus, the existing test suite does not catch this NameError.
- The workflow strategy assumes GitHub Actions will run on a standard `ubuntu-latest` image.
- Flake8 and pytest-cov need to be installed in the CI virtual environment as they are not currently listed in `requirements.txt`.

## 4. Conclusion
- A `NameError` exists at line 345 of `trading_bot/backtest/engine.py` due to the capitalization of `ROUND_TRIP`.
- Changing `ROUND_TRIP` to `round_trip` on line 345 resolves the bug. A patch has been generated in `.agents/explorer_setup_ci_1/engine_name_error.patch`.
- The CI configuration should be created as `.github/workflows/ci.yml` using the workflow defined in `.agents/explorer_setup_ci_1/proposed_ci.yml` targeting Python 3.11/3.12, running flake8 linting (specifically error codes `E9,F63,F7,F82`), and executing pytest with coverage reports.

## 5. Verification Method
- Apply the patch locally:
  `git apply .agents/explorer_setup_ci_1/engine_name_error.patch`
- Run `flake8` checks:
  `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
- Run the full test suite with coverage:
  `pytest --cov=trading_bot --cov-report=term-missing`

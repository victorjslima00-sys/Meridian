# Handoff Report — Setup & CI Investigation (Milestone 1)

## 1. Observation
- **File Checked**: `trading_bot/backtest/engine.py` (specifically lines 122, 199, 292, and 345)
- **Line 122**:
  ```python
  round_trip = (brokerage_pct + spread_pct) * 2
  ```
- **Line 199**:
  ```python
  pnl_pct = (exit_price / pos.entry_price - 1) - round_trip
  ```
- **Line 292**:
  ```python
  pnl_pct = (exit_price / entry_price_real - 1) - round_trip
  ```
- **Line 345**:
  ```python
  pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
  ```
- **File Checked**: `tests/test_engine.py`
  - Shows that `test_engine_gap_abort` and `test_engine_max_positions` only contain `pass` placeholders and do not execute or assert against the end-of-period loop in `run_regime_backtest`.
- **Command Executed**: `pytest` in the project root:
  - Passed all 18 existing tests, demonstrating that existing unit tests do not cover/trigger the `ROUND_TRIP` `NameError`.
- **Missing File**: `.github/workflows/ci.yml` does not exist in the workspace.

## 2. Logic Chain
1. In `trading_bot/backtest/engine.py`, the function `run_regime_backtest` defines the local variable `round_trip` in lowercase on line 122.
2. On line 345, inside the loop closing open positions at the end of the backtest period, the code references `ROUND_TRIP` in uppercase.
3. Because Python is case-sensitive and `ROUND_TRIP` is not defined anywhere in the global scope or function scope, executing line 345 will result in a `NameError: name 'ROUND_TRIP' is not defined`.
4. Therefore, changing `ROUND_TRIP` to `round_trip` on line 345 directly resolves the NameError.
5. In addition, since `pytest-cov` is needed to generate coverage reports in the CI workflow, it must be installed alongside the dependencies.
6. The CI workflow should run `flake8` with `--select=E9,F63,F7,F82` to ensure syntax, undefined names, and other critical errors are caught. It should also run `pytest --cov=trading_bot` to check tests and coverage.

## 3. Caveats
- No caveats. The NameError is direct and the proposed fixes are standard and clean.

## 4. Conclusion
- **NameError Fix**: The uppercase `ROUND_TRIP` on line 345 must be replaced with the lowercase `round_trip`.
- **Proposed Patch**: A diff patch file has been generated as `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_setup_ci_3/proposed_engine.patch`.
- **CI Workflow File**: `.github/workflows/ci.yml` should be created with the contents specified in `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_setup_ci_3/proposed_ci.yml` which targets Python versions 3.11 and 3.12, uses `flake8` syntax validation, and runs `pytest` with coverage.

## 5. Verification Method
1. **NameError Verification**:
   - To verify the bug is present before the fix, write a test in `tests/test_engine.py` that ends a backtest period with an open position. It will raise `NameError: name 'ROUND_TRIP' is not defined`.
   - Apply the patch `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_setup_ci_3/proposed_engine.patch`.
   - Run `pytest` to verify the new test passes and no name errors are raised.
2. **CI Workflow Verification**:
   - Copy `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_setup_ci_3/proposed_ci.yml` to `.github/workflows/ci.yml`.
   - Run flake8 locally to ensure compliance: `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`.
   - Run pytest with coverage: `pytest --cov=trading_bot --cov-report=term-missing tests/`.

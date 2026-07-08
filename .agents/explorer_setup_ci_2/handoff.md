# Handoff Report — Explorer 2 (Setup & CI)

## 1. Observation
- **ROUND_TRIP Variable Issue**:
  - Exact file path: `trading_bot/backtest/engine.py`
  - In function `run_regime_backtest` (starting at line 96), a local variable `round_trip` is defined at line 122:
    ```python
    122:     round_trip = (brokerage_pct + spread_pct) * 2
    ```
  - Near the end of the function, at line 345, the code attempts to compute `pnl_pct` for remaining open positions:
    ```python
    345:             pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
    ```
  - Variable `ROUND_TRIP` (uppercase) is not defined anywhere in the scope of `trading_bot/backtest/engine.py`, which leads to a `NameError: name 'ROUND_TRIP' is not defined` if a backtest finishes with open positions.
- **CI Workflow File**:
  - List directory command (`list_dir`) for root `/Users/mac/.gemini/antigravity/scratch/meridian/` showed that `.github/` and `.github/workflows/ci.yml` do not exist.
- **Project Test Execution**:
  - Executed `pytest` from the root directory. Command output returned:
    ```
    collected 18 items
    tests/test_engine.py ..                                                  [ 11%]
    tests/test_metrics.py ....                                               [ 33%]
    tests/test_risk.py .......                                               [ 72%]
    tests/test_signals.py .....                                              [100%]
    ============================== 18 passed in 3.19s ==============================
    ```
  - In `tests/test_engine.py`, the test cases are currently placeholder skeletons using `pass` (lines 51, 55). Thus, the backtest engine is not fully exercised under normal test suites, hiding the runtime `NameError`.

## 2. Logic Chain
- **ROUND_TRIP Bug Logic**:
  1. Python is case-sensitive, so the variable `round_trip` defined on line 122 does not match the reference `ROUND_TRIP` on line 345.
  2. Because `ROUND_TRIP` is not defined globally, accessing it on line 345 causes a `NameError`.
  3. Changing `ROUND_TRIP` on line 345 to lowercase `round_trip` aligns with the local definition on line 122.
- **CI Pipeline Design Logic**:
  1. To comply with requirements in `SCOPE.md` and `PROJECT.md`, a pipeline file `.github/workflows/ci.yml` needs to be created.
  2. Running the pipeline across Python `3.11` and `3.12` matrices ensures multi-version support.
  3. Configuring `flake8` with the option `--select=E9,F63,F7,F82` specifically isolates critical failures (e.g. syntax, undefined names like `ROUND_TRIP`).
  4. Running `pytest --cov=trading_bot --cov-report=term-missing tests/` tests the codebase and reports coverage to verify target requirements.

## 3. Caveats
- No caveats. The investigation is based on explicit code inspection and matching requirements.

## 4. Conclusion
- **Actionable Fix for NameError**: Apply the patch `engine.patch` changing `ROUND_TRIP` to `round_trip` on line 345 of `trading_bot/backtest/engine.py`.
- **Actionable Setup for CI**: Create `.github/workflows/ci.yml` with the contents specified in `proposed_ci.yml`.

## 5. Verification Method
- **Bug Fix Verification**:
  1. Apply the patch: `git apply .agents/explorer_setup_ci_2/engine.patch`
  2. Run `flake8` with:
     ```bash
     flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
     ```
     Ensure that flake8 reports `0` errors (the undefined name F82 for `ROUND_TRIP` will disappear).
- **CI Pipeline Verification**:
  1. Create the directories and workflow file using `proposed_ci.yml`.
  2. Push the changes to GitHub and check the Actions run output.

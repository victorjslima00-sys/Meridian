# Handoff Report — Reviewer 2 (Setup & CI)

This handoff report contains the observations, reasoning, and final review verdicts for Milestone 1 (Setup & CI).

---

## 1. Observation

- **Engine Modification**: In `trading_bot/backtest/engine.py` on line 345, the uppercase `ROUND_TRIP` was replaced with lowercase `round_trip`:
  ```python
  pnl_pct = (float(last["c"]) / pos.entry_price - 1) - round_trip
  ```
  And `round_trip` is defined locally on line 122 of `trading_bot/backtest/engine.py` as:
  ```python
  round_trip = (brokerage_pct + spread_pct) * 2
  ```
- **CI Workflow**: `.github/workflows/ci.yml` was successfully created. It contains setup for:
  - Python matrix: `["3.11", "3.12"]`
  - Flake8 linting: `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
  - Pytest with coverage: `pytest --cov=trading_bot --cov-report=term-missing tests/`
- **Test Executions**:
  - Running `pytest` in the root `/Users/mac/.gemini/antigravity/scratch/meridian` collects 25 tests, resulting in **2 failures** (both inside `tests/e2e/test_infrastructure.py`):
    1. `test_sandbox_config`:
       ```
       E       AssertionError: assert {'tickers': ['PETR4'], 'sectors': {'PETR4': 'energia'}} == ['PETR4']
       ```
    2. `test_mock_b3_clock`:
       ```
       E       assert datetime.date(2026, 7, 7) == datetime.date(2024, 6, 30)
       ```
  - Running pytest excluding e2e (`pytest tests/test_engine.py tests/test_lint.py tests/test_metrics.py tests/test_risk.py tests/test_signals.py`) yields **19 passed** tests out of 19.
  - The programmatic lint check `tests/test_lint.py` passes successfully, verifying 0 flake8 errors for E9, F63, F7, and F82.

---

## 2. Logic Chain

1. Worker 1 correctly addressed the `ROUND_TRIP` name error in `trading_bot/backtest/engine.py` by changing it to `round_trip`, aligning with the local definition on line 122.
2. Worker 1 correctly implemented `.github/workflows/ci.yml` with the specified Python matrices, lint select rules, and pytest coverage.
3. However, since the parallel E2E track (Milestone E1) added `tests/e2e/test_infrastructure.py` and the CI pipeline runs `pytest` on all tests, the CI run is currently broken due to test failures.
4. Specifically:
   - `test_sandbox_config` asserts `cfg.get("_universe") == ["PETR4"]`, but `_universe` contains a dictionary `{"tickers": ["PETR4"], "sectors": {"PETR4": "energia"}}`.
   - `test_mock_b3_clock` imports `today_b3` at import time in `test_infrastructure.py`, which bypasses the monkeypatch in `conftest.py`.
5. Therefore, the overall repository tests do not pass successfully. The final verdict must be `REQUEST_CHANGES` to fix the broken test cases in the test suite so CI can pass.

---

## 3. Caveats

- The failing tests are in `tests/e2e/`, which belongs to Milestone E1 (E2E Test Suite) and not directly to Worker 1's scope. However, since they block the main test execution and break CI, they must be fixed.
- Flake8 shell command execution was not run directly due to permission timeouts, but lint cleanliness is validated via `tests/test_lint.py`.

---

## 4. Conclusion

- **Verdict**: **REQUEST_CHANGES**
- The setup and CI components created by Worker 1 are technically correct, but the project test suite is currently failing. We cannot approve while tests are failing.

---

## 5. Verification Method

To verify the findings:
1. Run `pytest` at the root directory `/Users/mac/.gemini/antigravity/scratch/meridian`. Observe the 2 failures in `tests/e2e/test_infrastructure.py`.
2. Inspect `trading_bot/backtest/engine.py` line 345 to verify `round_trip` is lowercase.
3. Inspect `.github/workflows/ci.yml` to verify workflow configuration details.

---

## 6. Quality Review

### Verdict
**REQUEST_CHANGES**

### Findings

#### [Major] Finding 1: Broken E2E Test Suite
- **What**: E2E test cases `test_sandbox_config` and `test_mock_b3_clock` are failing.
- **Where**: `tests/e2e/test_infrastructure.py`
- **Why**:
  - `test_sandbox_config` expects a list `["PETR4"]` for key `_universe`, but receives the full dictionary: `{'tickers': ['PETR4'], 'sectors': {'PETR4': 'energia'}}`.
  - `test_mock_b3_clock` fails to apply the date mock because `today_b3` is imported at the module level prior to the monkeypatch hook.
- **Suggestion**: 
  - Fix the assertion in `test_sandbox_config` to check `cfg.get("_universe", "tickers")`.
  - Fix the mock in `test_mock_b3_clock` by importing inside the test function or patching the test module's imported attribute directly (`tests.e2e.test_infrastructure.today_b3`).

### Verified Claims
- `ROUND_TRIP` replaced with `round_trip` in `trading_bot/backtest/engine.py` → Verified via file inspection and git diff → **PASS**
- `.github/workflows/ci.yml` is created and correctly configured → Verified via file inspection → **PASS**
- Flake8 lint clean for `E9,F63,F7,F82` → Verified via `tests/test_lint.py` execution → **PASS**
- Base unit tests (19 tests) pass → Verified via pytest execution excluding e2e → **PASS**

### Coverage Gaps
- None.

---

## 7. Adversarial Review

### Challenge Summary
- **Overall risk assessment**: **MEDIUM**

### Challenges

#### [Medium] Challenge 1: CI Pipeline Breakage
- **Assumption challenged**: The test suite remains green as new code tracks are merged or added.
- **Attack scenario**: Adding untracked or unverified tests to the repository breaks the global `pytest` runner, which immediately breaks CI for all developers.
- **Blast radius**: Prevents merging any branch because the matrix builds will always fail.
- **Mitigation**: Configure the CI workflow or pytest config (`pytest.ini`) to allow ignoring or warning on E2E tests if they are not ready, or implement strict validation gates before committing new tests.

#### [Low] Challenge 2: Clock Mocking Fragility
- **Assumption challenged**: `monkeypatch.setattr("trading_bot.core.clock.today_b3", ...)` is robust enough to mock the clock everywhere.
- **Attack scenario**: Any module that performs `from trading_bot.core.clock import today_b3` at import time will bypass the monkeypatch, resulting in real system dates being used. This could trigger unexpected trade executions in staging or tests.
- **Blast radius**: Test environment behaves non-deterministically based on the actual system date.
- **Mitigation**: Enforce importing the parent module `from trading_bot.core import clock` or import the function locally within testing hooks/methods.

### Stress Test Results
- Run `pytest` on entire workspace → Expected: PASS → Actual: FAIL (2 failures) → **FAIL**

### Untested Angles
- Behavior under actual runner matrix (GitHub runners) — not testable locally in the review workspace.

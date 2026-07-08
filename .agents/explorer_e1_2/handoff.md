# Handoff Report - Explorer 2

## 1. Observation
* **Fase 0 Exit Gate Constraint**:
  In `/Users/mac/.gemini/antigravity/scratch/meridian/scripts/fase0_validate_data.py` lines 119-123:
  ```python
  gates_ok = (
      len(data) >= int(len(tickers) * 0.9) and   # 90%+ dos ativos com dados
      errors_total <= 2 and                        # Até 2 erros tolerados (eventos corporativos legítimos)
      cross_status == "passed"
  )
  ```
  If `--skip-brapi` is active or no token is provided, `cross_status` becomes `"skipped"`, making `gates_ok = False`, which returns exit code `1` (line 142).
* **Backtest Engine Undefined Variable**:
  In `/Users/mac/.gemini/antigravity/scratch/meridian/trading_bot/backtest/engine.py` line 345:
  ```python
  pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
  ```
  However, `ROUND_TRIP` is not defined globally or in that scope. A lowercase `round_trip` variable is defined on line 122:
  ```python
  round_trip = (brokerage_pct + spread_pct) * 2
  ```
  This will trigger a `NameError: name 'ROUND_TRIP' is not defined` whenever there are open positions left at the end of a backtest period regime.
* **Lack of Core Risk Integrations in Backtest**:
  In `trading_bot/backtest/engine.py`, there is no usage or import of the `CircuitBreaker` class or the `check_correlation` function from `trading_bot/risk/circuit_breaker.py`. They exist as standalone logic and are only covered by unit tests in `tests/test_risk.py`.
* **Missing Target Files**:
  File paths `trading_bot/risk/position_sizer.py`, `trading_bot/core/logger.py`, `trading_bot/core/telegram.py`, and `trading_bot/core/scheduler.py` do not exist in the codebase yet. They are part of planned milestones (M2 onwards).

## 2. Logic Chain
1. Under standard CLI execution, running `python scripts/fase0_validate_data.py --skip-brapi` or running it without providing a valid `brapi_token` in `settings.yaml` will always return exit code `1` because `cross_status` is `"skipped"`. Therefore, any E2E orchestrator or pipeline expecting a `0` exit code from Fase 0 must mock or supply a valid Brapi token and verify cross-validation passes.
2. In the backtest script (`scripts/fase1_backtest.py`), if any regimes (e.g., `crise_volatilidade`) end with active open positions, the regime cleanup block on lines 341-362 of `trading_bot/backtest/engine.py` is invoked. Because of the `ROUND_TRIP` NameError at line 345, the execution will crash mid-run.
3. Since critical safety invariants (Daily Loss limit, Inception/30d Drawdown, Pearson Correlation check) are not yet integrated into the backtest engine itself, the E2E test runner must mock and test these components at the module boundary level or structure integrated scenarios where they are explicitly imported and called to verify their math.
4. Designing E2E and integration tests for Tiers 3 (Pairwise) and 4 (Real-World Application) requires a framework of mocked APIs (`yfinance`, `brapi.dev`, `Telegram`, and `broker`) to decouple execution from external network requests, adhering to the `CODE_ONLY` network restriction.

## 3. Caveats
* **Codebase State**: The codebase is in the middle of development (Milestone M1/E1 in progress, M2 planned). The analysis is based on the current snapshot. Future code changes may resolve the `ROUND_TRIP` NameError and integrate the `CircuitBreaker` and `PositionSizer` into `engine.py`.
* **Network Restrictions**: The E2E tests designed in this report are strictly offline (mock-reliant) due to the `CODE_ONLY` execution restrictions of the system. In a live environment, the mocks would be replaced by actual sandbox environments.

## 4. Conclusion
The E2E integration test suite for Meridian must be structured to mock out all external data suppliers (Yahoo Finance and Brapi.dev API) and message alerts (Telegram). To verify Tier 3 and Tier 4 scenarios, we designed:
1. A **15-case Pairwise Coverage Matrix** targeting the combinations of Market Trend, Signals, Sector Correlation, Cash Sizing, Execution Slippage, and Circuit Breakers.
2. **5 Real-World Scenarios** simulating B3 market shocks, sector correlation blocking, sizer limits, ex-dividend corporate action smoothing, and Telegram outage fail-safes.
The findings and complete blueprints have been successfully written to `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_e1_2/analysis.md`.

## 5. Verification Method
* To check the test designs and reports:
  Inspect `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_e1_2/analysis.md`.
* To run the current suite of unit tests:
  Execute `pytest` from the root directory `/Users/mac/.gemini/antigravity/scratch/meridian/` using `run_command`.

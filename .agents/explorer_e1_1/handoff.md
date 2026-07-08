# E2E Test Case Design Handoff Report

## 1. Observation
We investigated the codebase and observed the following:
- **`scripts/fase0_validate_data.py`**:
  - Arguments parsed: `--token` (default `""`), `--skip-brapi` (flag), and `--years` (default `5`) at lines 38-42.
  - Returns `0` if `gates_ok` is `True` and `1` otherwise:
    ```python
    142:     return 0 if gates_ok else 1
    ```
  - `gates_ok` check at lines 119-123:
    ```python
    119:     gates_ok = (
    120:         len(data) >= int(len(tickers) * 0.9) and   # 90%+ dos ativos com dados
    121:         errors_total <= 2 and                        # Até 2 erros tolerados (eventos corporativos legítimos)
    122:         cross_status == "passed"
    123:     )
    ```
- **`scripts/fase1_backtest.py`**:
  - Runs backtest engine across defined regimes (lines 50-61).
  - No system exit wrappers or exit status returns are present:
    ```python
    85: if __name__ == "__main__":
    86:     main()
    ```
    This means the script exit code is always `0` in Python when executed successfully, regardless of gate status.
  - The gate status is printed directly to stdout at lines 73-74:
    ```python
    73:     gate_status = "✅ PASSA" if agg.overall_pass else "❌ REPROVA"
    74:     print(f"Sharpe Agregado: {agg.sharpe_aggregate:.2f} ({gate_status})")
    ```
- **`trading_bot/backtest/engine.py`**:
  - An uppercase variable name error is observed at line 345:
    ```python
    345:             pnl_pct = (float(last["c"]) / pos.entry_price - 1) - ROUND_TRIP
    ```
    This conflicts with the lowercase local variable `round_trip` defined at line 122.
- **`tests/test_engine.py`**:
  - The engine tests are skeletons containing only pass statements (lines 25-51, 53-55):
    ```python
    51:     pass # Esqueleto para desenvolvimento futuro de testes avançados
    ```
- **`tests/` test results**:
  - Running `pytest` collects and passes 18 existing tests in `2.10s`.

---

## 2. Logic Chain
1. We parsed the inputs, configuration paths, CLI arguments, and output schemas of both entry points (`scripts/fase0_validate_data.py` and `scripts/fase1_backtest.py`) to map their functional flow.
2. Based on this mapping, we identified the lack of direct test validation files in `tests/` for multiple core modules (e.g., validator, cross-validation, and engine execution).
3. We categorized the features into 5 logical groups: historical ingestion/storage, data quality validation, cross-source validation, backtest trade execution, and performance metrics/gates.
4. For each feature, we designed 5 Tier 1 (Feature Coverage) and 5 Tier 2 (Boundary/Corner cases) test cases, providing a complete 50 test case matrix.
5. We determined that the test runner must handle exit codes differently for each script: `fase0_validate_data.py` can be verified by its exit status (`0` vs `1`), while `fase1_backtest.py` must be verified by parsing its console stdout for `"✅ PASSA"` vs `"❌ REPROVA"` since its exit status is always `0`.
6. We designed the mocking architecture for the external APIs (yfinance, brapi.dev) using local CSV/JSON files, and for Telegram (manual confirmation flows: approve, reject, timeout) and Cedro broker stubs (authentication, stop orders, fractional odd-lot conversions, network exceptions).

---

## 3. Caveats
- Since this is a read-only investigation, no test code was implemented. The actual test files and runner must be coded by the implementer.
- The `ROUND_TRIP` NameError at line 345 of `trading_bot/backtest/engine.py` will cause a runtime crash if any positions are left open at the end of a backtest regime. This must be fixed in implementation before the E2E runner executes.
- Telegram and Cedro integrations are not yet present in the current `core/` or `broker/` modules, so the mock structures are designed based on contract definitions, configuration files, and `PROJECT.md` stubs.

---

## 4. Conclusion
The Meridian E2E test suite can be safely and comprehensively constructed around the entry points `scripts/fase0_validate_data.py` and `scripts/fase1_backtest.py`. We have established a detailed test design document (`analysis.md`) containing 50 specific test cases across 5 features (Feature Coverage & Boundary cases), along with mocking guidelines for yfinance, brapi, Telegram, and Cedro APIs.

---

## 5. Verification Method
To independently verify the investigation findings:
1. Review the generated `analysis.md` report at: `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/explorer_e1_1/analysis.md`.
2. Inspect the codebase files:
   - `scripts/fase0_validate_data.py` lines 119-142 to verify exit code logic.
   - `scripts/fase1_backtest.py` lines 73-86 to verify always-zero exit code behavior.
   - `trading_bot/backtest/engine.py` line 345 to verify the `ROUND_TRIP` NameError.
3. Invalidation conditions: The design is invalidated if the entry points are refactored to parse arguments differently or if exit codes are updated before the E2E implementation starts.

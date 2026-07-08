## 2026-07-07T22:02:47-03:00
You are Worker 2. Your working directory is `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/worker_e1_2/`.
Your role is teamwork_preview_worker.
Your task:
1. Initialize your BRIEFING.md and progress.md.
2. Implement 50 end-to-end and integration test cases covering Tier 1 (Feature Coverage) and Tier 2 (Boundary/Corner cases) for features A, B, C, D, E under `/Users/mac/.gemini/antigravity/scratch/meridian/tests/e2e/test_tier1_tier2.py`.
   - Feature A: Ingestion & Storage. (T1: db creation, normal ingestion, duplicate ignoring, delta start, yf index flattening. T2: delisted/empty response, malformed input schema, missing adj close, negative years, locked db).
   - Feature B: Quality Validation. (T1: clean data validation, gap warning, gap error, zero volume warning, large price move warning/error. T2: empty validation input, single-row input, duplicate timestamps, zero price division safety, weekends/holidays exclusion).
   - Feature C: Source Cross-Validation. (T1: successful check <0.5%, failed check >0.5%, skip-brapi status check, ex-dividend check within 15%, JSON report validation. T2: missing token warning, brapi timeout retries, 429 rate limit backoff, invalid/mismatched ticker on Brapi, yfinance download failure recovery).
   - Feature D: Backtest Trade Execution. (T1: breakout signal trigger, next-day open fill, take profit target hit, stop loss hit, 15-day timeout exit. T2: gap down below stop abort, intraday stop/target double trigger conservative check, same-day entry/exit, cash exhaustion sizing block, corrupt/missing IBOV index trend filter default).
   - Feature E: Performance Metrics & Gates. (T1: aggregate Sharpe ratio computation, max drawdown/duration calculation, profit factor calculation, overnight stress gap impact, Sharpe gate evaluation. T2: insufficient trades Sharpe default, zero-variance standard deviation division safety, account bankruptcy, zero-duration regime division safety, zero positions stress gap default).
3. Use the fixtures already defined in `tests/e2e/conftest.py` (sandbox_config, mock_b3_clock, mock_yfinance, mock_brapi_api, mock_telegram_client, mock_cedro_client) to run these tests offline.
4. Run `PYTHONPATH=. pytest tests/e2e/test_tier1_tier2.py` and verify that all 50 tests pass successfully.
5. Write your handoff.md detailing what you implemented, and send a completion message to the parent (conversation ID: db120891-f6fe-43db-955f-f9837a91ea57) referencing the path to your handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

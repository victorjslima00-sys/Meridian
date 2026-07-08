## 2026-07-08T01:02:47Z
You are Worker 3. Your working directory is `/Users/mac/.gemini/antigravity/scratch/meridian/.agents/worker_e1_3/`.
Your role is teamwork_preview_worker.
Your task:
1. Initialize your BRIEFING.md and progress.md.
2. Implement E2E and integration tests covering Tier 3 (Cross-Feature Combinations / Pairwise) and Tier 4 (Real-World Application Scenarios) under `/Users/mac/.gemini/antigravity/scratch/meridian/tests/e2e/test_tier3_tier4.py`.
   - Tier 3: Implement at least 5 pairwise combination tests (e.g. varying trend uptrend/downtrend/transition, signals none/single/multi, correlation limits pass/fail, sizing norm/cap, execution fill clean/abort, risk safe/circuit breaker).
   - Tier 4: Implement 5 realistic application-level scenarios:
     1. Scenario 1: Sudden Market Crash & Multi-Level Circuit Breakers (Daily Loss, Rolling 30d, Inception drawdown triggers, blocking orders, and sending Telegram alerts).
     2. Scenario 2: High Correlation Sector Clustering (blocking candidates in the same sector with correlation > 0.70).
     3. Scenario 3: Position Sizing Capping under Cash Constraints (Kelly sizing vs. available cash, verifying cash never goes negative and aborts when below minimum threshold).
     4. Scenario 4: Corporate Actions Ex-Dividend adjustment checks (verifying that validation report is ok on adjusted data and stop-loss isn't triggered falsely on ex-dividend price drops).
     5. Scenario 5: Scheduler Lifecycle, Manual Approvals, and Telegram/Notification Outage Fail-Safe (verifying that when Telegram client fails, orders in manual mode expire rather than executing automatically).
3. Use the fixtures already defined in `tests/e2e/conftest.py` and mock inputs. Test the entry points by importing and executing the `main()` functions of `scripts/fase0_validate_data.py` and `scripts/fase1_backtest.py` under the mocked environment (redirecting `sys.argv` as needed to control arguments).
4. Run `PYTHONPATH=. pytest tests/e2e/test_tier3_tier4.py` and verify all tests pass successfully.
5. Write your handoff.md detailing what you implemented, and send a completion message to the parent (conversation ID: db120891-f6fe-43db-955f-f9837a91ea57) referencing the path to your handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

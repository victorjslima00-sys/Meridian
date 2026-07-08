# Plan - Milestone 1: Setup & CI

## Objectives
1. Fix uppercase `ROUND_TRIP` to lowercase `round_trip` on line 345 of `trading_bot/backtest/engine.py`.
2. Create `.github/workflows/ci.yml` configured with Python 3.11/3.12, flake8 (E9, F63, F7, F82) and pytest with coverage.

## Decomposed Steps
1. **Initialize Workspace Metadata** (Done)
   - Initialize BRIEFING.md, progress.md, plan.md, context.md, ORIGINAL_REQUEST.md.
2. **Start Liveness Heartbeat**
   - Start recurring heartbeat cron (every 10 minutes).
3. **Exploration Phase**
   - Spawn 3 Explorer agents to locate the files, identify the codebase layout/dependencies, analyze the requirements, and suggest fix/implementation strategies.
4. **Implementation Phase**
   - Spawn 1 Worker agent with explorer findings to apply the fixes, configure CI, run pytest and flake8 locally, and report.
5. **Review Phase**
   - Spawn 2 Reviewer agents to verify correctness, interface conformance, and adherence to requirements.
6. **Challenge Phase**
   - Spawn 2 Challenger agents to run tests and aggressively stress-test/validate the behavior.
7. **Audit Phase**
   - Spawn 1 Forensic Auditor agent to verify integrity and ensure no cheating/facade/mocking of results occurred.
8. **Gate Check & Progression**
   - Evaluate outputs. If successful, write handoff.md, message the parent, and complete milestone.

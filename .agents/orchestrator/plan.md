# Meridian Swing Trading System Implementation Plan

## Overview
This plan orchestrates the implementation, testing, and consolidation of the Meridian Swing Trading System on B3 with execution via the Cedro broker.

## Milestones

### Milestone 1: Exploration & Project Setup (PROJECT.md and initial analysis)
- **Objective**: Explore the codebase, determine structure, runs tests (via Explorer), and create the global project scope document (`PROJECT.md`).
- **Input**: Workspace codebase, user requirements.
- **Output**: Initial analysis report from Explorer, `PROJECT.md` created.

### Milestone 2: Task A (R1) - Critical Corrections & CI Setup
- **Objective**: Fix backtest engine bugs (specifically the `ROUND_TRIP` bug), configure `.github/workflows/ci.yml` with Python 3.11/3.12, `flake8` and `pytest` with coverage.
- **Verification**: Run pytest and flake8 locally via subagents.

### Milestone 3: Task B (R2) - Test Coverage Expansion (to >= 70%)
- **Objective**: Raise test coverage to at least 70% in main modules (`tests/test_engine.py`, `data/validator.py`, `data/cross_validation.py`, `data/ingestion.py`, `backtest/metrics.py`, `core/config.py`, `core/clock.py`). No empty test stubs.
- **Verification**: `pytest tests/ --cov=trading_bot --cov-report=term-missing` showing >= 70% coverage.

### Milestone 4: Task D (R4) - Risk Management & Live Readiness
- **Objective**: Isolate Kelly position sizing in `risk/` or `execution/` for live use. Verify return matrix generator for correlation checks. Implement logger, Telegram, and scheduler in `core/` if missing. Ensure security invariants (Telegram confirmation, timeout, circuit breaker, paper trading mode).
- **Verification**: Tests checking live execution rules, Telegram confirmation mock flow, circuit breaker activation.

### Milestone 5: Task E (R5) - Code Cleanup & Warning Resolution
- **Objective**: Resolve minor warnings (SQLite3 deprecation, unused imports, global keyword in IBOV cache).
- **Verification**: Run flake8 and check warnings.

### Milestone 6: Task C (R3) - Documentation Sync
- **Objective**: Sync README with real project state, remove outdated elements, document test coverage per module.

### Milestone 7: Final Verification & Adversarial Hardening
- **Objective**: End-to-end backtest runs (`fase1_backtest.py`), and run Challenger agent to perform adversarial hardening. Run Forensic Auditor to verify integrity.
- **Verification**: Clean audit report and all tests passing.

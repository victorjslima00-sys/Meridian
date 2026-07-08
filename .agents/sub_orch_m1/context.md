# Context - Milestone 1: Setup & CI

## Target Files
1. `trading_bot/backtest/engine.py`
   - Needs uppercase `ROUND_TRIP` on or around line 345 changed to lowercase `round_trip`.
2. `.github/workflows/ci.yml`
   - Needs creation of GitHub Actions workflow file.
   - Configuration requirements:
     - Runs on: `ubuntu-latest`
     - Python versions: `3.11`, `3.12`
     - Linter: `flake8` with options for syntax errors/undefined names (E9, F63, F7, F82)
     - Test runner: `pytest` with code coverage verification.

## Local Environment Context
- Root directory: `/Users/mac/.gemini/antigravity/scratch/meridian/`
- Target project uses pytest for testing and flake8 for linting.
- Virtual environment or package requirements are located in `requirements.txt`.

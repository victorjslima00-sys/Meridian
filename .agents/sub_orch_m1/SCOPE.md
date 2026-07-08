# Scope: Milestone 1 - Setup & CI (Tarefa A)

## Architecture
- Repository CI setup using GitHub Actions workflow `.github/workflows/ci.yml`.
- Backtest engine implementation in `trading_bot/backtest/engine.py`.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1.1 | Fix ROUND_TRIP NameError | Change uppercase `ROUND_TRIP` to lowercase `round_trip` on line 345 of `trading_bot/backtest/engine.py`. | None | PLANNED |
| 1.2 | Create CI Workflow | Create `.github/workflows/ci.yml` configured with Python 3.11/3.12, flake8 (E9, F63, F7, F82) and pytest with coverage. | None | PLANNED |

## Interface Contracts
- Backtest engine exits: must not raise `NameError` on position close.
- CI pipeline: must successfully run pytest and flake8 on push/PR.

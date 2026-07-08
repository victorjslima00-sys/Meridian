# Project: Meridian Swing Trading System

## Architecture
Meridian is an automated swing trading bot for the B3 exchange with execution via Cedro. It consists of the following packages/modules:
- `trading_bot/core/`: Configuration, clock, and core utility infrastructure.
- `trading_bot/data/`: Data ingestion, validation, storage, and cross-validation.
- `trading_bot/signals/`: Technical analysis, break-out breakout, and signal calculation.
- `trading_bot/backtest/`: Backtesting engine and performance metrics calculation.
- `trading_bot/risk/`: Risk management, correlation, and circuit breakers.
- `trading_bot/broker/`: Broker connection and order execution stubs.

## Code Layout
```
/
├── .github/
│   └── workflows/
│       └── ci.yml
├── config/
│   ├── settings.yaml
│   └── universe.yaml
├── data/
│   ├── test.db
│   └── trading_bot.db
├── scripts/
│   ├── fase0_validate_data.py
│   └── fase1_backtest.py
├── tests/
│   ├── __init__.py
│   ├── test_engine.py
│   ├── test_metrics.py
│   ├── test_risk.py
│   ├── test_signals.py
│   ├── test_data_modules.py (new)
│   ├── test_risk_isolated.py (new)
│   └── test_infrastructure.py (new)
└── trading_bot/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── clock.py
    │   ├── config.py
    │   ├── logger.py (new)
    │   ├── telegram.py (new)
    │   └── scheduler.py (new)
    ├── data/
    │   ├── __init__.py
    │   ├── cross_validation.py
    │   ├── ingestion.py
    │   ├── storage.py
    │   └── validator.py
    ├── signals/
    │   ├── __init__.py
    │   └── engine.py
    ├── backtest/
    │   ├── __init__.py
    │   ├── engine.py
    │   └── metrics.py
    ├── risk/
    │   ├── __init__.py
    │   ├── circuit_breaker.py
    │   └── position_sizer.py (new)
    └── broker/
        ├── __init__.py
        └── mock.py
```

## Milestones

### Implementation Track

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Setup & CI (Tarefa A) | Fix `ROUND_TRIP` NameError in `trading_bot/backtest/engine.py`. Implement `.github/workflows/ci.yml`. | None | IN_PROGRESS (Conv ID: b10b1795-22d0-4ad3-9faa-1995857a96e4) |
| M2 | Risk & Infra (Tarefa D) | Implement isolated `KellyPositionSizer` in `risk/position_sizer.py` and returns matrix generator for `check_correlation`. Implement logger, Telegram, and scheduler in `core/`. Ensure security invariants. | M1 | PLANNED |
| M3 | Coverage & Stubs (Tarefa B) | Implement missing test logic for `tests/test_engine.py` (stubs), `validator.py`, `cross_validation.py`, `ingestion.py`, `metrics.py`, `config.py`, `clock.py` to achieve >= 70% coverage. | M2 | PLANNED |
| M4 | Code Cleanup (Tarefa E) | Resolve SQLite3 PARSE_DECLTYPES warning, unused imports, global cache keyword, and other warnings. | M3 | PLANNED |
| M5 | Documentation (Tarefa C) | Update `README.md` to match reality, update installation commands, remove outdated items, and add the test coverage table. | M4 | PLANNED |
| M6 | Final Verification & Hardening | Run all test suites. Perform adversarial testing and challenger validation. | M5 | PLANNED |

### E2E Testing Track

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E1 | E2E Test Suite | Design and implement an E2E testing runner and test cases covering feature validation, boundary cases, cross-features, and workloads. | None | IN_PROGRESS (Conv ID: db120891-f6fe-43db-955f-f9837a91ea57) |

## Interface Contracts
- `KellyPositionSizer.calculate_position_size(current_equity: float, available_cash: float, win_rate: float, win_loss_ratio: float) -> float`
- `generate_returns_matrix(tickers: list[str], db_path: str, window_days: int) -> dict[str, list[float]]`
- `logger.py` exports `setup_logger(level: str)`
- `telegram.py` exports `TelegramClient` with message sending and mock features.
- `scheduler.py` exports `Scheduler` wrapping the scheduler library.

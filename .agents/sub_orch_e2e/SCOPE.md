# Scope: Milestone E1 - E2E Testing Track

## Architecture
- Opaque-box testing of the Meridian swing trading system.
- Test runner executing the end-to-end backtest script and validation routines.
- Verification of safety invariants (Telegram verification, circuit breaker, timeout, paper trading mode).

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E1.1 | Test Infrastructure | Create a test runner and directory structure for E2E tests, verifying features as an end user would. | None | PLANNED |
| E1.2 | Tier 1-4 Test Suite | Implement Category-Partition, BVA, Pairwise, and Workload tests. | E1.1 | PLANNED |
| E1.3 | Publish TEST_READY.md | Synthesize and publish the `TEST_READY.md` containing features checklist, runner command, and coverage summary. | E1.2 | PLANNED |

## Interface Contracts
- Must publish `/Users/mac/.gemini/antigravity/scratch/meridian/TEST_READY.md` when done.
- Opaque-box entry points: `python scripts/fase1_backtest.py` and `python scripts/fase0_validate_data.py`.

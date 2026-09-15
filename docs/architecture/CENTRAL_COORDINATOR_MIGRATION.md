# Central Coordinator Migration Architecture Specification

- **Document Version**: 1.0.0
- **Status**: PROPOSED / ARCHITECTURAL SPECIFICATION
- **Target Component**: Background Worker Supervision & Lifecycle Architecture
- **Applicable Branches**: `team/vulcan-observability`, future unification branches
- **Ratification**: PENDING

---

## 1. Executive Summary

This document specifies the migration plan from the legacy FastAPI-managed ad-hoc background supervisors (`worker_supervisor` and `exit_loop_supervisor`) to the institutional `CentralCoordinator` pattern.

This migration addresses architectural divergence and establishes a unified, observable, and resilient process supervision topology across both web runtime (FastAPI/Uvicorn) and headless CLI execution environments.

---

## 2. Current Runtime Topology

In the current production runtime (`backend/app/main.py`):

```
FastAPI lifespan startup:
├── _b3_market_data_scheduler (APScheduler background thread)
├── asyncio.create_task(worker_supervisor())       [ACTIVE SUPERVISOR #1]
│   └── while True: ai_committee_worker() iteration
├── asyncio.create_task(exit_loop_supervisor())     [ACTIVE SUPERVISOR #2]
│   └── while True: exit_loop() iteration
└── coord = CentralCoordinator()                   [PASSIVE / DECOUPLED]
    ├── coord.register_worker("ai_committee", ...)
    ├── coord.register_worker("exit_loop", ...)
    └── app.state.coordinator = coord
        NOTE: await coord.start() is NEVER invoked!
```

### Key Observation: Registration != Execution

The `CentralCoordinator` is instantiated and registered with worker coroutines in `backend/app/main.py:46-52`, and attached to `app.state.coordinator`. 

However, **registration is decoupled from execution**:
- `coord.start()` is **not** called.
- `coord.is_running` remains `False`.
- The coordinator's internal watchdog loop (`_watchdog_loop`) is **not started**.
- No `asyncio.Task` instances are created or managed by the coordinator in production.
- The coordinator exists purely as a decoupled observational metadata container and telemetry registry for worker state.

### Legacy Supervisors Currently Active

The execution and restart lifecycle of background tasks in production is exclusively driven by the legacy supervisors:
1. `worker_supervisor()` (`backend/app/main.py:766-802`): Runs the continuous scanning loop for market opportunities (`ai_committee_worker`), tracking restarts and backoff in `backend.app.worker_state.state`.
2. `exit_loop_supervisor()` (`backend/app/main.py:804-830`): Runs the high-frequency exit scan (`exit_loop`), tracking restarts in `backend.app.worker_state.state.exit_supervision`.

---

## 3. Duplicate-Worker Risk (Why `coord.start()` Must Not Be Added Now)

Adding `await coord.start()` to the current `lifespan` without simultaneously decommissioning the legacy supervisors would create **critical duplicate worker execution**:

```
UNSAFE TOPOLOGY (CONCURRENT SUPERVISORS):
FastAPI lifespan
├── Legacy worker_supervisor()       ──> executes ai_committee_worker() [INSTANCE 1]
├── Legacy exit_loop_supervisor()    ──> executes exit_loop()           [INSTANCE 1]
└── CentralCoordinator.start()
    ├── coord._run_worker_supervisor() ──> executes ai_committee_worker() [INSTANCE 2: DUPLICATE!]
    └── coord._run_worker_supervisor() ──> executes exit_loop()           [INSTANCE 2: DUPLICATE!]
```

### Catastrophic Failure Modes of Duplicate Execution:
1. **Concurrent Order Generation**: Two parallel instances of `ai_committee_worker` evaluating the same signal could trigger concurrent buy attempts before the database lock or rate limit settles.
2. **Race Conditions in Exit Execution**: Two parallel instances of `exit_loop` scanning open positions simultaneously could attempt double-exit or conflict during trade closure.
3. **Double Balance Deduction**: Concurrent execution risks race conditions against `portfolio` cash balances.
4. **State Desynchronization**: Counter and heartbeat updates would clobber each other in `worker_state.state`.

**Rule**: Under no circumstances should `await coord.start()` be activated while legacy supervisors remain running.

---

## 4. Status of Coordinator Auto-Healing

The auto-healing watchdog logic implemented in `trading_bot/core/coordinator.py`:

```
STATUS: IMPLEMENTED BUT NOT WIRED INTO CURRENT RUNTIME
```

- **In unit tests** (`tests/test_coordinator.py`): The watchdog auto-healing mechanism is verified and tested in isolation where `coord.start()` is explicitly started and stopped.
- **In current runtime** (`backend/app/main.py`): Because `coord.start()` is not invoked during application boot, the auto-healing task `_watchdog_task` is **never scheduled**.
- **Observational Integrity**: The system must NOT claim that automated watchdog restart is active in production until cutover is formally ratified and executed.

---

## 5. Desired Future Topology (Post-Cutover)

Following formal architectural ratification (ADR-002), the target runtime topology will be:

```
TARGET TOPOLOGY (POST-MIGRATION):
FastAPI lifespan startup:
├── _b3_market_data_scheduler
└── coord = CentralCoordinator(...)
    ├── coord.register_worker("ai_committee", ai_committee_worker_iteration, ...)
    ├── coord.register_worker("exit_loop", exit_loop_iteration, ...)
    ├── coord.register_worker("health_monitor", health_monitor_worker, ...)
    └── await coord.start()                       [SOLE SUPERVISOR]
        ├── Managed Task: ai_committee
        ├── Managed Task: exit_loop
        ├── Managed Task: health_monitor
        └── Managed Task: _watchdog_loop (Heartbeat & Auto-Healing)

DECOMMISSIONED & REMOVED:
├── worker_supervisor() [DELETED]
└── exit_loop_supervisor() [DELETED]
```

---

## 6. Migration Prerequisites

Before initiating the cutover to `CentralCoordinator` as the primary supervisor:

1. **ADR-002 Institutional Ratification**: Formal approval from Victor, Astra, Nexus, and Sentinel.
2. **Worker Decomposition into Unit Iterations**: `ai_committee_worker()` and `exit_loop()` must be decomposed from infinite `while True` loops into discrete, cancelable single-cycle coroutines (`_run_one_scan_cycle`, `_run_exit_scan`).
3. **Telemetry Parity**: Verify that `coord.get_status()` provides all fields consumed by `/api/status` and the React frontend dashboard (`worker_alive`, `consecutive_errors`, `last_scan_at`, `system_health`).
4. **Clean Shutdown Guarantees**: Verify that `await coord.stop(timeout=10.0)` cleanly cancels all child tasks within the Uvicorn shutdown window.

---

## 7. Cutover Criteria

Cutover from legacy supervisors to `CentralCoordinator` will only be authorized when:

1. A dedicated migration branch is created specifically for cutover.
2. Legacy `worker_supervisor` and `exit_loop_supervisor` coroutines are completely removed from `backend/app/main.py` in the same atomic commit that introduces `await coord.start()`.
3. An automated end-to-end test validates that exactly one task instance exists for each registered worker.
4. Zero regressions in the full test suite (all 822+ tests passing).

---

## 8. Rollback Strategy

If anomalies, unhandled exceptions, or performance regressions are observed post-cutover:

1. **Immediate Reversion**: Revert the commit enabling `await coord.start()` and restoring the legacy supervisor tasks.
2. **Fail-Closed Fallback**: In the event of an in-flight crash during rollback, verify that `exit_gate_sticky_block` engages, preserving the financial invariant `real_broker_calls == 0`.
3. **Post-Mortem State Inspection**: Ingest the structured event log (`coord.get_events()`) to analyze failure sequence before re-attempting migration.

---

## 9. Required Tests Before and During Cutover

| Test ID | Objective | Status in Current Code |
| :--- | :--- | :--- |
| **TEST-MIG-01** | Static inspection: verify `main.py` does NOT contain `coord.start()` in current runtime | **PASS** (`test_coordinator_migration_guard.py`) |
| **TEST-MIG-02** | Runtime check: verify `app.state.coordinator.is_running is False` after lifespan setup | **PASS** (`test_coordinator_migration_guard.py`) |
| **TEST-MIG-03** | Auto-healing isolation: verify watchdog task is not running in current startup | **PASS** (`test_coordinator_migration_guard.py`) |
| **TEST-MIG-04** | Isolated lifecycle: verify coordinator starts, restarts, and shuts down cleanly in tests | **PASS** (`tests/test_coordinator.py`) |
| **TEST-MIG-05** | Latency tracking: verify `CycleLatencyTracker` records cycle times without blocking | **PASS** (`tests/test_cycle_tracker.py`) |
| **TEST-MIG-06** | Fail-closed: verify `on_exhausted` hook engages emergency block upon restart exhaustion | **PASS** (`tests/test_coordinator.py`) |

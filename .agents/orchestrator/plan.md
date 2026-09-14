# Meridian P0 Data & Backend Roadmap Plan

## Overview
Orchestration plan to execute the P0 Data & Backend Roadmap from the Meridian Executive Audit:
- R1: Backend API Metric Provenance Integration & Candle Integrity
- R2: Deterministic Multi-Source Data Reconciliation Pipeline
- R3: Walk-Forward Quantitative Model Evaluation Rigor

## Phase 0: Survey & Specification Mapping
- Deploy 3 parallel Explorers / Spec Miners:
  - Explorer 1: Focus on R1 (Backend API Metric Provenance Integration, `MetricProvenanceAgent`, `config/metric_approvals.json`, risk/equity endpoints, HTTP 502/503 for candle history, removal of synthetic balances).
  - Explorer 2: Focus on R2 (Deterministic Multi-Source Data Reconciliation, `DataReconciliationAgent`, B3 COTAHIST vs bar feeds, cent residuals, SHA-256 corporate actions, `MISSING_DATA`, unit/ticker validation).
  - Explorer 3: Focus on R3 (Walk-Forward Quantitative Model Evaluation, `ModelEvaluationAgent`, temporal ordering, leakage detection, cost/slippage, benchmark comparison, `is_approved_for_signals=False`, test suites).
- Consolidate findings into `PROJECT.md` Feature Inventory and Architecture.

## Phase 1: Decomposition into Milestones & Interface Contracts
- Define precise interface contracts between components in `PROJECT.md`.
- Milestone R1: Backend API Metric Provenance Integration
- Milestone R2: Deterministic Multi-Source Data Reconciliation
- Milestone R3: Walk-Forward Quantitative Model Evaluation
- Parallel E2E Testing Track: Design & verify test infrastructure and test suites.

## Phase 2: Implementation Track & Dual Track
- Dispatch sub-orchestrators for milestones.
- Ensure strict adherence to non-cheating, deterministic requirements, fail-closed configs, and no synthetic fallbacks.

## Phase 3: Final Acceptance & Adversarial Hardening
- Run `pytest --basetemp=reports/pytest-test-temp -p no:cacheprovider` to verify all unit and integration tests pass with exit code 0.
- Dispatch Challenger for adversarial testing.
- Dispatch Forensic Auditor for integrity check (binary veto).

## Phase 4: Final Victory Report
- Deliver comprehensive completion report and claim victory to Sentinel.

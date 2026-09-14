# Original User Request

## Initial Request — 2026-07-08T00:49:16Z

# Teamwork Project Prompt — Draft

> Status: Ready for launch — awaiting user approval
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

Sistema de swing trading B3 automatizado (Meridian) com execução via corretora Cedro, exigindo alta cobertura de testes e implementação estrita das regras de gestão de risco.

Working directory: /Users/mac/.gemini/antigravity/scratch/meridian
Integrity mode: development

## Requirements

### R1. Aplicar Correções Críticas e CI (Tarefa A)
Garantir que o repositório passe na integração contínua. Substituir o workflow atual do GitHub Actions por um novo `.github/workflows/ci.yml` configurado com Python 3.11/3.12, `flake8` (erros críticos E9, F63, F7, F82) e `pytest` com cobertura. Confirmar se as correções do motor de backtest (bug do `ROUND_TRIP`) já estão aplicadas.

### R2. Elevar Cobertura de Testes (Tarefa B)
Alcançar pelo menos 70% de cobertura nos módulos principais. Focar nos stubs vazios de `tests/test_engine.py`, em `data/validator.py`, `data/cross_validation.py`, `data/ingestion.py`, `backtest/metrics.py`, `core/config.py` e `core/clock.py`. Não utilizar stubs falsos; escrever validações reais de lógica (ex: mocks para chamadas de API externa).

### R3. Atualizar Documentação (Tarefa C)
Sincronizar o README com o estado real do projeto, removendo pendências já resolvidas (como o capital inicial que já está no settings) e documentar o status da cobertura de testes por módulo.

### R4. Consolidar Gestão de Risco (Tarefa D)
Garantir que o sistema de dimensionamento de posição (Kelly) exista de forma isolada em `risk/` ou `execution/` para ser usado ao vivo, não apenas no engine de backtest. Confirmar a existência de um gerador de matriz de retornos para o `check_correlation`. Implementar logger, integração Telegram e scheduler em `core/` caso estejam faltando.

### R5. Limpeza de Código (Tarefa E)
Resolver avisos menores identificados (ex: uso desnecessário de `global` no cache do IBOV, DeprecationWarnings do SQLite3 e imports não utilizados).

### R6. Invariantes de Segurança
O bot operará com dinheiro real no futuro. Manter estritamente: confirmação manual via Telegram como padrão, timeout gerando rejeição, circuit breaker não-contornável e obrigatoriedade de paper trading. Não mockar credenciais em código.

## Acceptance Criteria

### Verificação Objetiva e Estrita
- [ ] `pytest tests/ --cov=trading_bot --cov-report=term-missing -v` roda com 100% dos testes passando.
- [ ] Nenhum teste consiste apenas em stubs vazios (`pass`).
- [ ] `flake8 . --select=E9,F63,F7,F82` roda sem apontar novos erros (além de possíveis cosméticos).
- [ ] `python scripts/fase1_backtest.py` roda de ponta a ponta sem lançar exceções.
- [ ] Commits realizados são pequenos, descritivos e separados por tarefa (sem "big ball of mud").

## 2026-09-13T23:11:00Z

Execute the P0 Data & Backend Roadmap from the Meridian Executive Audit: connect verified metric provenance contracts to backend endpoints, establish independent data reconciliation between market feeds, and standardize quantitative research models with strict temporal walk-forward evaluation.

Working directory: C:\Users\BIRTUS JANIO\Documents\Codex\2026-09-11\oque\work\Meridian  
Integrity mode: development  

## Requirements

### R1. Backend API Metric Provenance Integration
Every metric returned by backend endpoints (risk metrics, portfolio valuation, equity, and asset indicators) must adhere to the deterministic `MetricProvenanceAgent` verification contract. Metrics lacking valid, independent approval in `config/metric_approvals.json` must return `value: null` with `verification_status: "unavailable"`. Never impute, fallback to arbitrary constants, or fabricate default figures.

### R2. Deterministic Multi-Source Data Reconciliation
Deploy a deterministic reconciliation pipeline using `DataReconciliationAgent` to compare market data observations across distinct sources (e.g. B3 COTAHIST daily files vs historical bar feeds). The system must compute exact residuals cent-by-cent, match corporate actions strictly against documented events with SHA-256 hashes, and flag any missing date as `MISSING_DATA` without silent forward-filling or interpolation.

### R3. Walk-Forward Quantitative Model Evaluation
Standardize quantitative predictive models under `ModelEvaluationAgent`. Enforce strict temporal ordering between train, validation, and out-of-sample test splits ($Train_{end} < Val_{start} < Test_{start}$) with zero lookahead leakage. Deduct transaction costs and slippage, compare against market benchmarks, and faithfully record negative returns. The field `is_approved_for_signals` must remain permanently `false`.

## Acceptance Criteria

### Metric Provenance & API Integrity
- [ ] Backend risk and equity endpoints return `verification_status: "unavailable"` and `value: null` when metric approvals are absent or unverified.
- [ ] Endpoints return HTTP 502/503 for invalid or corrupted candle histories without silent zero-patching.
- [ ] No hardcoded or synthetic portfolio balances (e.g. literal R$ 1.000.000) are emitted as real market data.

### Reconciliation Pipeline
- [ ] Discrepancies between compared feeds are accurately recorded with exact residuals and status `UNEXPLAINED_MISMATCH` unless covered by documented events.
- [ ] Missing dates on either source feed are explicitly categorized as `MISSING_DATA`.
- [ ] Units and tickers are validated; mismatched units raise explicit errors.

### Model Evaluation & Research Rigor
- [ ] Any overlap or inversion between train, validation, and test splits raises `ValueError("temporal_leakage_detected")`.
- [ ] Estimators are fit exclusively on the train split; out-of-sample test splits are strictly out-of-sample.
- [ ] Underperforming strategies faithfully record negative returns and max drawdown without suppression.

### Verification Suite
- [ ] All unit and integration test suites pass with exit code 0 (`pytest --basetemp=reports/pytest-test-temp -p no:cacheprovider`).
- [ ] Existing fail-closed protections in `config/data_approvals.json` remain intact.

---
*Verification Resources:*
- `tests/test_metric_provenance.py`
- `tests/test_data_reconciliation.py`
- `tests/test_model_evaluation.py`
- `tests/test_candle_integrity_api.py`

## 2026-09-13T23:31:36Z

Build and harden the MetaTrader 5 (MT5) Local Bridge & Paper Execution Connector: establish a resilient communication bridge with the local MT5 terminal for routing demo/paper orders, guarantee idempotent order dispatching with persistent SQLite tracking across restarts, and enforce strict RiskManager fail-closed circuit breakers.

Working directory: C:\Users\BIRTUS JANIO\Documents\Codex\2026-09-11\oque\work\Meridian  
Integrity mode: development  

## Requirements

### R1. MetaTrader 5 Communication Bridge & Terminal Adapter
Implement a resilient local adapter to interface with the MetaTrader 5 terminal (using the Python `MetaTrader5` package or local IPC/socket). The adapter must query demo account equity, free margin, and active positions, and route paper/demo market and limit orders. Disconnections, closed terminals, or socket timeouts must be handled gracefully without crashing the bot.

### R2. Idempotent Order Dispatcher with SQLite Persistence
Replace volatile in-memory order tracking with persistent SQLite storage for all MT5 outbound orders and incoming execution reports. Every order must carry a unique, deterministic client order ID (`clord_id`). Rapid retries, network glitches, or bot restarts must never duplicate a live or demo order.

### R3. Strict RiskManager Binding & Fail-Closed Gates
Every order submitted to the MT5 bridge must pass through the official `RiskManager` pre-trade checks (max lot size, daily loss limit, and spread threshold). If any check fails, or if market feeds are marked unverified/unavailable, the bridge must reject the order immediately (*fail-closed*) with an explicit audit log.

## Acceptance Criteria

### MT5 Bridge & Connectivity
- [ ] Terminal connection failures (e.g. MT5 not open) raise structured errors with clean fallback; never crash the execution loop.
- [ ] Account equity, balance, and open position queries return structured, verified records.
- [ ] Orders sent in demo mode are logged with MT5 ticket ID, symbol, volume, fill price, and timestamp.

### Idempotency & Persistence
- [ ] Order states (`PENDING`, `SUBMITTED`, `FILLED`, `REJECTED`, `CANCELLED`) are persisted in SQLite.
- [ ] Resubmitting an identical `clord_id` returns the existing order status without sending a duplicate ticket to MT5.
- [ ] Simulating a process crash and restart preserves order history and reconciles open positions against MT5 custody.

### Risk Controls
- [ ] Orders violating max position size or daily drawdown limits are rejected prior to reaching the MT5 API.
- [ ] Disconnection or unverified market data blocks new order creation automatically.

### Automated Tests
- [ ] Unit and mock integration test suites for the MT5 bridge and SQLite persistence pass with exit code 0.

---
*Verification Resources:*
- `trading_bot/execution/`
- `tests/test_order_manager.py`
- `trading_bot/risk/` or `RiskManager`

## 2026-09-13T23:36:17Z

Build, harden, and verify the Vulcan DevOps Continuous Health & Alerting Engine for Meridian: establish live, verified heartbeat monitoring for local system resources without synthetic constants, implement automated failure injection suites to prove fail-closed resilience, build a verifiable multi-channel alerting dispatcher, and validate seamless state recovery across simulated process crashes.

Working directory: C:\Users\BIRTUS JANIO\Documents\Codex\2026-09-11\oque\work\Meridian  
Integrity mode: development  

## Requirements

### R1. Deterministic System & Process Health Heartbeat Monitor
Upgrade `trading_bot/infra/health_monitor.py`. Completely eradicate synthetic constants (e.g. hardcoded 4096 MB RAM). Implement native Windows resource metrics via `ctypes` (`GlobalMemoryStatusEx` for total/available RAM and memory load percentage) alongside `shutil.disk_usage` and process inspection. Record periodic structured heartbeats with ISO-8601 timestamps, resource exhaustion flags, and process health states.

### R2. Automated Failure Injection Test Harness
Construct a dedicated chaos and failure injection framework (`trading_bot/infra/chaos_injector.py` and `tests/test_chaos_resilience.py`). Simulate deterministic operational stress scenarios:
1. **API / Socket Failure**: simulate sudden network drops and verify that endpoints fail closed (HTTP 502/503) without emitting synthetic prices or balances.
2. **Resource Exhaustion**: simulate disk full (< 1 GB free) and memory pressure (> 95% load), confirming that order dispatching halts immediately and alerts trigger.
3. **Database / SQLite Corruption/Lock**: simulate lock timeouts and verify graceful retry and audit logging.

### R3. Verifiable Multi-Channel Alert Dispatcher & Deduplication
Harden `trading_bot/infra/alert_dispatcher.py` (or consolidate existing notification logic):
1. Support tiered alert priorities: `CRITICAL`, `WARNING`, `INFO`.
2. Implement deterministic deduplication windows (e.g., prevent alert storms during repeated failures).
3. Persist every alert event to an append-only SQLite or structured JSON log with SHA-256 event digest, source module, and timestamp.
4. If external delivery fails (mock Telegram network timeout), fall back cleanly to local audit quarantine without crashing.

### R4. Process Crash & Resilient State Recovery
Demonstrate crash resilience across the bot's stateful components:
1. Validate that killing the process mid-operation preserves pending orders in SQLite.
2. Upon restart, automatically reconcile state against custody or terminal reality without orphan orders or double fills.

## Acceptance Criteria

### Health Monitoring Integrity
- [ ] No hardcoded or synthetic resource metrics exist in `health_monitor.py`.
- [ ] Windows physical memory is queried via native OS APIs (`ctypes.windll.kernel32.GlobalMemoryStatusEx`) returning exact total and available bytes.
- [ ] Disk space and RAM thresholds trigger explicit `WARNING_LOW_DISK` or `CRITICAL_LOW_MEMORY` statuses.

### Chaos & Failure Injection
- [ ] Chaos test suite simulates network drop, terminal shutdown, and disk exhaustion deterministically.
- [ ] In all simulated failures, system exhibits strict fail-closed behavior: halts trading and rejects unverified inputs.

### Alert Dispatcher
- [ ] Alert deduplication suppresses identical alerts within configurable cooldown windows.
- [ ] Alerts are permanently logged with SHA-256 provenance hashes.
- [ ] Alert dispatching never crashes execution if delivery channels fail.

### Test Verification
- [ ] 100% of existing and new test suites pass with exit code 0 (`pytest --basetemp=reports/pytest-test-temp -p no:cacheprovider`).
- [ ] No regression across the existing 595 passing tests.

---
*Verification Resources:*
- `trading_bot/infra/health_monitor.py`
- `tests/test_health_monitor.py`
- `trading_bot/infra/`
- `tests/test_chaos_resilience.py`


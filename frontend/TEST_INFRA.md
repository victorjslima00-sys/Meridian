# TEST_INFRA.md: Meridian Frontend Hardening — Test Infrastructure Specification

**Document Version**: 1.0.0  
**Date**: 2026-09-13  
**Project**: Meridian Institutional React Frontend Reconstruction & Hardening  
**Target Root**: `C:\Users\BIRTUS JANIO\Documents\Codex\2026-09-11\oque\work\Meridian\frontend`  
**Author**: Test Writer E2E 1 (`teamwork_preview_test_writer`) — Dual Track E2E Testing  
**Status**: Authoritative Test Specification  

---

## 1. Test Philosophy & Architecture

### 1.1 Core Principles
1. **Opaque-Box & Requirement-Driven**: Tests are designed strictly against the authoritative requirements in `ORIGINAL_REQUEST.md` and `PROJECT.md`. Tests interact exclusively with observable DOM outputs, ARIA roles, accessible names, text content, and user events. Internal state, component props, and private hooks are never directly spied upon or asserted.
2. **Zero Tolerance for False Zeros**: In institutional finance, presenting a missing, delayed, unverified, or errored metric as `R$ 0,00` or `0.0%` is a critical failure. A false zero masks solvency risks and system disconnections as healthy states. Every test asserting on financial values verifies that missing, null, or errored data yields explicit `"Indisponível"` or `"Não Verificado"` states.
3. **Fail-Closed Verification**: When an API endpoint fails (HTTP 500, 502, 503, network drop, timeout), the frontend must engage the **Fail-Closed Mode**. Tests verify that:
   - High-priority warning banner (`"PROTEÇÃO FAIL-CLOSED ATIVADA"` / `"FAIL-CLOSED ATIVO"`) is rendered prominently.
   - Operational balances are not zeroed out or collapsed.
   - Critical mutation buttons (boleta orders, deposits, withdrawals, margin modifications) are disabled.
4. **Cryptographic Provenance Transparency**: Every verified financial or risk metric must render cryptographic provenance metadata (`source_ref`, 64-character `source_sha256`, `observed_at`). Tests verify that hoverable tooltips open, render accurate monospace hashes, expose one-click copy actions, and display honest unverified badges when provenance records are missing or unapproved.
5. **Deterministic Test Isolation**: Every test is self-contained and independently executable. Tests mock network calls at the HTTP client boundary (`axios` / `fetch`) with deterministic payloads and clean up DOM and timing state after each execution.

---

## 2. Feature Inventory & Mapping to Tiers 1–4

| Feature ID | Feature Name | Description | Source Requirement | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Cross-Feature) | Tier 4 (Scenarios) |
|---|---|---|---|---|---|---|---|
| **F1** | Honest Currency & Numeric Formatting | Formatters strictly return `"Indisponível"` / `"Não Verificado"` on null/undefined/NaN; enforce tabular numerals. | ORIGINAL_REQUEST §R1 | >= 5 tests | >= 5 tests | Pairwise with F4, F8, F9 | Real-World S1, S4 |
| **F2** | Global KPI Honesty (App.jsx) | `Patrimônio Total`, `Reservado`, `Caixa`, `Em Posições`, `PnL Flutuante` never coerce null to R$ 0,00. | ORIGINAL_REQUEST §R1 | >= 5 tests | >= 5 tests | Pairwise with F3, F7 | Real-World S1, S2 |
| **F3** | Fail-Closed Disconnection Pipeline | Captures 502, 503, network drops; renders Fail-Closed warning banner; locks out mutations. | ORIGINAL_REQUEST §R1, R3 | >= 5 tests | >= 5 tests | Pairwise with F2, F8, F10 | Real-World S1, S4 |
| **F4** | Tabular Monospace Typography | Enforces `font-variant-numeric: tabular-nums lining-nums` on all currency, percentage, and ratio cells. | ORIGINAL_REQUEST §R2 | >= 5 tests | >= 5 tests | Pairwise with F1, F6 | Real-World S1, S3 |
| **F5** | Institutional Connection Badges | Renders header badges: `"OPERACIONAL"`, `"FAIL-CLOSED ATIVO"`, `"AUDITORIA CONFORME"`, `"SEM CONEXÃO"`. | ORIGINAL_REQUEST §R2 | >= 5 tests | >= 5 tests | Pairwise with F3, F7 | Real-World S1, S4 |
| **F6** | Cryptographic Provenance Tooltip | Tooltip rendering `source_ref`, 64-char `source_sha256`, `observed_at`, and copy-to-clipboard action. | ORIGINAL_REQUEST §R2 | >= 5 tests | >= 5 tests | Pairwise with F2, F10 | Real-World S2, S3 |
| **F7** | Hardened CapitalVault | Eliminates `saldoOperavel ?? 0`; eliminates false `"sem teto"` on null margin; disables actions on disconnect. | ORIGINAL_REQUEST §R1, R2 | >= 5 tests | >= 5 tests | Pairwise with F1, F3 | Real-World S3, S4 |
| **F8** | Hardened PositionNarrative | Eliminates `(v ?? 0).toFixed(2)`; eliminates false green gain (`+0.00%`) on null PnL; honest empty/offline states. | ORIGINAL_REQUEST §R1, R2 | >= 5 tests | >= 5 tests | Pairwise with F1, F3 | Real-World S1, S4 |
| **F9** | Hardened RiskMetricsPanel | Eliminates infinite hang on 502/503; renders honest `"Indisponível"` on null Sharpe/VaR; surfaces provenance. | ORIGINAL_REQUEST §R1, R2 | >= 5 tests | >= 5 tests | Pairwise with F3, F6 | Real-World S2, S4 |
| **F10** | Elimination of Synthetic Defaults | Purges fabricated approvals (`"Aprovado. Risco avaliado..."`), fake capital fallback (`|| 100`), fake initial WS logs. | ORIGINAL_REQUEST §R1 | >= 5 tests | >= 5 tests | Pairwise with F8, F9 | Real-World S2, S3 |
| **F11** | Production Build & Linter Tooling | Clean `npm.cmd run build` (exit code 0, dist/ output) and `npm.cmd run lint` (zero blocking errors). | ORIGINAL_REQUEST §R3 | >= 5 tests | >= 5 tests | Integrated build verification | CI / Gate |

---

## 3. Test Architecture & Coverage Thresholds

### Tier 1: Feature Coverage (>= 5 test cases per feature)

#### Feature F1: Honest Formatting Engine (`src/utils/formatters.js`)
- **T1.F1.01**: `formatCurrency(1250450.2)` returns string or element containing `"R$ 1.250.450,20"` with tabular styling.
- **T1.F1.02**: `formatCurrency(null)` returns `"Indisponível"` (never `"R$ 0,00"`).
- **T1.F1.03**: `formatCurrency(undefined)` returns `"Indisponível"` (never `"R$ 0,00"`).
- **T1.F1.04**: `formatCurrency(NaN)` returns `"Indisponível"` (never `"R$ NaN"` or `"R$ 0,00"`).
- **T1.F1.05**: `formatPercent(1.25)` returns `"+1,25%"` or `"1,25%"`; `formatPercent(null)` returns `"Indisponível"` (never `"0,00%"` or `"+0.0%"`).
- **T1.F1.06**: `formatCurrency(0)` explicitly returns `"R$ 0,00"` when the input is a genuine verified zero (verifying genuine zeroes are distinguished from null).

#### Feature F2: Global KPI Cards (`src/App.jsx`)
- **T1.F2.01**: Renders verified `patrimonio_total` as formatted BRL with tabular numerics when valid data is supplied.
- **T1.F2.02**: When `capital` object has `patrimonio_total: null`, renders `"Indisponível"` badge in the card value, not `"R$ 0,00"`.
- **T1.F2.03**: When `saldo_livre: null`, renders `"Indisponível"` and does not supply a fallback `100` to sizing calculators.
- **T1.F2.04**: When `active_positions` array is missing or null, PnL Flutuante renders `"Indisponível"`, not `"R$ 0,00"`.
- **T1.F2.05**: KPI card headers contain provenance tooltip triggers (`role="button"` or `aria-label`).

#### Feature F3: Fail-Closed Disconnection Pipeline (`src/App.jsx`)
- **T1.F3.01**: When `/api/status` returns HTTP 502 Bad Gateway, renders top banner containing `"FAIL-CLOSED ATIVO"` or `"PROTEÇÃO FAIL-CLOSED"`.
- **T1.F3.02**: When `/api/positions` returns HTTP 503 Service Unavailable, connection badge updates to `"SEM CONEXÃO"` or `"FAIL-CLOSED"`.
- **T1.F3.03**: During API failure, previously observed capital values are preserved or rendered as unverified, NOT replaced with `"R$ 0,00"`.
- **T1.F3.04**: Boleta and trade execution buttons are disabled (`disabled` attribute present) while fail-closed banner is active.
- **T1.F3.05**: When API recovers (HTTP 200), fail-closed banner clears and status returns to `"OPERACIONAL"`.

#### Feature F4: Tabular Monospace Typography
- **T1.F4.01**: KPI card values have CSS class or style enforcing `tabular-nums` (`font-variant-numeric: tabular-nums`).
- **T1.F4.02**: Trade entry, stop loss, and target prices in narrative cards enforce tabular numerals.
- **T1.F4.03**: Risk metric values in `RiskMetricsPanel` enforce tabular numerals.
- **T1.F4.04**: Capital vault balance amounts enforce tabular numerals.
- **T1.F4.05**: Ticker and percentage changes enforce tabular numerals.

#### Feature F5: Institutional Connection Badges
- **T1.F5.01**: Verified operational state renders badge with text `"OPERACIONAL"` and emerald indicator.
- **T1.F5.02**: Disconnected state renders badge with text `"FAIL-CLOSED ATIVO"` or `"SEM CONEXÃO"` with crimson/warning indicator.
- **T1.F5.03**: Exit gate sticky block renders badge warning with exact sticky block notification.
- **T1.F5.04**: Metric with valid provenance displays `"AUDITORIA CONFORME"`.
- **T1.F5.05**: Metric with missing provenance displays `"NÃO VERIFICADO"`.

#### Feature F6: Cryptographic Provenance Tooltips (`src/components/ProvenanceTooltip.jsx`)
- **T1.F6.01**: Hovering or clicking tooltip trigger renders popover displaying `source_ref`.
- **T1.F6.02**: Popover displays `source_sha256` matching the 64-character hex pattern `^[a-f0-9]{64}$` (or truncated monospace equivalent).
- **T1.F6.03**: Popover displays `observed_at` formatted with UTC/local timestamp.
- **T1.F6.04**: Clicking copy button invokes `navigator.clipboard.writeText` with the full 64-character hash.
- **T1.F6.05**: When `verification_status === "unverified"`, tooltip displays `"Registro descritivo da base local; sem homologação independente"`.

#### Feature F7: Hardened CapitalVault (`src/components/CapitalVault.jsx`)
- **T1.F7.01**: When `saldo_operavel` is 19800, renders `"R$ 19.800,00"` with tabular styling.
- **T1.F7.02**: When `saldo_operavel` is null, renders `"Indisponível"` (never `"R$ 0,00"`).
- **T1.F7.03**: When `margem_operavel` is null and disconnected, does NOT render `"sem teto"`; renders `"Indisponível"`.
- **T1.F7.04**: Deposit and withdraw buttons are disabled when `connected === false`.
- **T1.F7.05**: Margin update button is disabled when `connected === false`.

#### Feature F8: Hardened PositionNarrative (`src/components/PositionNarrative.jsx`)
- **T1.F8.01**: When `pnl_monetario` is null or undefined, renders `"Cotação Indisponível"` or `"Indisponível"`, never `"R$ 0,00"`.
- **T1.F8.02**: When `pnl_pct` is null or undefined, does NOT render a green gain indicator (`+0.00%`) or `<TrendingUp />` icon.
- **T1.F8.03**: When `entry_price` or `shares` is null, does NOT render `"R$ 0,00 alocados"` or `"0.00000 ações"`.
- **T1.F8.04**: When positions array is empty due to API failure, does NOT report `"O robô segue varrendo o mercado..."` as healthy; indicates degraded/offline state.
- **T1.F8.05**: Narrative displays ticker symbol, entry price, stop loss, and target profit correctly when data is valid.

#### Feature F9: Hardened RiskMetricsPanel (`src/components/RiskMetricsPanel.jsx`)
- **T1.F9.01**: When `/api/elite/risk_metrics` returns HTTP 502, panel does not hang on `"Carregando métricas..."`; renders `"Métricas Indisponíveis"`.
- **T1.F9.02**: When `sharpe_ratio` is null, renders `"Indisponível"` badge.
- **T1.F9.03**: When `var_95` is null, renders `"Indisponível"` with tooltip indicating reason (e.g. `"série histórica insuficiente"`).
- **T1.F9.04**: Progress bars do not render a fake 50% fill for null or uncalibrated metrics.
- **T1.F9.05**: Provenance tooltips are accessible on each individual metric card.

#### Feature F10: Elimination of Synthetic Defaults
- **T1.F10.01**: When `ai_rationale` has no Risk Manager note, does NOT fabricate `"Aprovado. Risco avaliado dinamicamente."`. Renders `"Aguardando Parecer do Risk Manager"`.
- **T1.F10.02**: When `saldo_livre` is null, does NOT pass `100` into `PositionSizingCalc`.
- **T1.F10.03**: Initial `DecisionLog` does NOT display hardcoded `"Conexão segura estabelecida."` before WebSocket connection.
- **T1.F10.04**: Supervisor restart count does NOT coerce null to `0` without indicating unverified state.
- **T1.F10.05**: No component contains hardcoded balances (e.g. literal `1000000` or `100.00`).

---

### Tier 2: Boundary & Corner Cases (>= 5 per feature)

#### Boundary Set B1: Numeric & Formatting Boundaries
- **T2.B1.01**: Value is `-0.000001` (micro negative): formats without rendering `"-R$ 0,00"`.
- **T2.B1.02**: Value is `Number.MAX_SAFE_INTEGER` (`9007199254740991`): formats cleanly with BRL separators without crashing.
- **T2.B1.03**: Value is `-Infinity` or `Infinity`: treated as non-finite; formats as `"Indisponível"`.
- **T2.B1.04**: Value is string containing non-numeric data (`"abc"`, `"123foo"`): treated as invalid; formats as `"Indisponível"`.
- **T2.B1.05**: Value is empty string `""`: treated as null/empty; formats as `"Indisponível"`.

#### Boundary Set B2: API Error & Payload Malformation Boundaries
- **T2.B2.01**: Backend returns HTTP 500 with HTML error page (`"<!DOCTYPE html><html>..."`): JSON parsing fails; frontend engages Fail-Closed mode without unhandled crash.
- **T2.B2.02**: Backend returns HTTP 502 Bad Gateway with empty body: engages Fail-Closed banner with `"Erro de Comunicação com Servidor (502)"`.
- **T2.B2.03**: Backend returns HTTP 200 with `{}` (empty JSON object): components render `"Indisponível"` without `TypeError: Cannot read properties of undefined`.
- **T2.B2.04**: Network request aborts with `ECONNABORTED` (timeout after 10,000ms): triggers timeout banner and fail-closed state.
- **T2.B2.05**: Network socket drops abruptly (fetch rejects with `TypeError: Failed to fetch` / `NetworkError`): triggers instant fail-closed state.

#### Boundary Set B3: Provenance & Cryptographic Boundaries
- **T2.B3.01**: `source_sha256` is shorter than 64 characters (e.g. `"abc123"`): flagged as invalid hash; displays warning badge `"Hash Inválido"`.
- **T2.B3.02**: `source_sha256` contains non-hex characters (e.g. `"g"`, `"z"`, `"!"`): flagged as invalid format.
- **T2.B3.03**: `observed_at` is an invalid date string (`"invalid-date"`): does not render `"NaN/NaN/NaN"`; displays `"Data Não Disponível"`.
- **T2.B3.04**: `provenance` object is `null` or `undefined`: tooltip gracefully renders `"Sem Registro de Proveniência"`.
- **T2.B3.05**: Clipboard API fails (`navigator.clipboard.writeText` rejects): displays fallback copy error message rather than crashing.

#### Boundary Set B4: Capital & Balance Extreme Boundaries
- **T2.B4.01**: `patrimonio_total` is 0 and verified: displays `"R$ 0,00"` with verified badge (genuine zero allowed only when explicitly verified).
- **T2.B4.02**: `saldo_operavel` is negative (margin call): displays `-R$ 5.000,00` with crimson alert styling.
- **T2.B4.03**: `margem_operavel` is 0: renders `"R$ 0,00"` (zero margin), distinct from `"Sem teto"` or `"Indisponível"`.
- **T2.B4.04**: Rapid consecutive clicks on deposit button while request is in-flight: ignores extra clicks due to disabled button state.
- **T2.B4.05**: Input contains special characters (`<script>`, commas, negative signs in deposit input): rejects or sanitizes input before API submission.

---

### Tier 3: Cross-Feature Combinations (Pairwise Coverage)

| Combination ID | Feature A | Feature B | Combined Scenario & Expected Behavior |
|---|---|---|---|
| **T3.C01** | F3 (Fail-Closed) | F7 (CapitalVault) | While API returns 502, user attempts to deposit or change margin. All vault action buttons must be disabled (`disabled === true`), preventing orphaned mutations. |
| **T3.C02** | F3 (Fail-Closed) | F2 (Global KPIs) | API times out mid-session. Previously rendered capital does NOT flash or reset to `R$ 0,00`; retains last known state with an overlay or unverified badge. |
| **T3.C03** | F3 (Fail-Closed) | F8 (PositionNarrative) | API 503 during active positions poll. Narrative does NOT display `"Nenhuma posição aberta. O robô segue varrendo..."`; displays `"Dados de posições indisponíveis - Sistema em Fail-Closed"`. |
| **T3.C04** | F3 (Fail-Closed) | F9 (RiskMetricsPanel) | API 502 on `/elite/risk_metrics`. Risk panel displays `"Falha de Conexão com Motor de Risco"` and does NOT keep stale metrics without unverified indicators. |
| **T3.C05** | F6 (Provenance) | F2 (Global KPIs) | Valid `positions` payload arrives with `capital` and `provenance`. KPI cards render formatted BRL, and clicking the card's provenance trigger reveals the verified SHA-256 hash. |
| **T3.C06** | F6 (Provenance) | F9 (RiskMetricsPanel) | Risk metrics arrive with `verification_status: "pending_approval"`. Panel displays metric value alongside amber `"Aguardando Aprovação"` badge and tooltip explaining pending status. |
| **T3.C07** | F1 (Formatters) | F4 (Tabular Typography) | Formatted currency and percentages in KPI cards, position cards, and tables strictly maintain CSS class `font-tabular` / `tabular-nums` even when rendering `"Indisponível"`. |
| **T3.C08** | F10 (No Synthetic Defaults) | F8 (PositionNarrative) | Backend sends position with `ai_rationale: null`. Narrative renders `"Sem Parecer Registrado"`, never fabricating `"Aprovado. Risco avaliado dinamicamente."`. |
| **T3.C09** | F5 (Badges) | F3 (Fail-Closed) | Worker status is `stopped` and `exit_gate_sticky_block: true`. Header displays `"FAIL-CLOSED ATIVO"` badge alongside sticky block alert banner. |
| **T3.C10** | F7 (CapitalVault) | F1 (Formatters) | Capital vault receives `margem_operavel: null` while connected. Formatter renders `"Sem teto definido"` (verified null); when disconnected, renders `"Indisponível"`. |

---

### Tier 4: Real-World Application Scenarios

#### Scenario S1: Market Open Quote Feed Collapse (Fail-Closed & Zero-Masking Prevention)
- **Context**: At 10:00:00 B3 market open, quote feed drops. The backend returns 502 for `/api/positions` and `/api/candles/PETR4`.
- **Workflow**:
  1. User navigates to overview dashboard.
  2. Initial status check succeeds (worker running), but `/api/positions` returns HTTP 502 Bad Gateway.
  3. Frontend immediately engages Fail-Closed Mode.
  4. Top warning banner renders: `"PROTEÇÃO FAIL-CLOSED ATIVADA - DADOS DE MERCADO INDISPONÍVEIS"`.
  5. KPI cards render `"Indisponível"` badges; under NO circumstances do they render `"Patrimônio Total: R$ 0,00"`.
  6. Position narrative renders error placeholder; does NOT report `"O robô segue varrendo o mercado..."`.
  7. Fast execution boleta buttons are disabled.
  8. Freshness tag indicates failure to refresh.

#### Scenario S2: Institutional Risk Audit & Unverified Metrics Inspection
- **Context**: Compliance officer inspects risk metrics in `RiskMetricsPanel` to verify independent risk model signoff.
- **Workflow**:
  1. User navigates to Risk & Metrics panel.
  2. `/api/elite/risk_metrics` returns valid Sharpe ratio (`1.42`) and VaR 95% (`null`), with provenance payload containing 64-character SHA-256 hash.
  3. User hovers over Sharpe ratio provenance icon.
  4. Tooltip renders:
     - `Fonte: data/trading_bot.db`
     - Monospace SHA-256 digest: `3a8f9c2d...4e1b8a7f`
     - Copy button: user clicks, receives `"Copiado!"` feedback; clipboard contains full 64-char hash.
     - Observation time: formatted UTC and BRT.
  5. User inspects VaR 95% card: value displays `"Indisponível"`, with explanatory badge `"Série histórica insuficiente"`.
  6. User verifies no fake 50% progress bar is rendered for the unavailable VaR metric.

#### Scenario S3: Capital Margin Ceiling Enforcement & Disconnection Guardrails
- **Context**: Operator sets operable margin ceiling in `CapitalVault`, then network drops.
- **Workflow**:
  1. Capital vault loads with verified `saldo_operavel: 50000.00` and `margem_operavel: 200000.00`.
  2. User enters `250000` in margin ceiling input and submits.
  3. Mock API returns 200 OK; UI updates to display `"R$ 250.000,00"` with tabular styling.
  4. Next polling cycle triggers a simulated network drop (`TypeError: Failed to fetch`).
  5. System detects disconnection:
     - Vault status renders `"Desconectado"`.
     - Deposit, withdraw, and margin update submit buttons are disabled.
     - Operable margin does NOT flip to `"sem teto"`.
     - Operable balance does NOT coerce to `"R$ 0,00"`.

#### Scenario S4: Intermittent Network Flapping & Recovery Cycle
- **Context**: Unstable Wi-Fi/VPN causes API calls to alternate: 200 OK -> 503 -> 502 -> 200 OK.
- **Workflow**:
  1. Dashboard starts in healthy state (`OPERACIONAL`, valid KPIs).
  2. First poll fails with HTTP 503: Fail-Closed banner triggers, UI actions lock out, values freeze without zeroing.
  3. Second poll fails with HTTP 502: Fail-Closed banner persists, error code updates to 502.
  4. Third poll succeeds with HTTP 200: Fail-Closed banner automatically dismisses, status returns to `"OPERACIONAL"`, action buttons unlock, fresh metrics render with updated freshness timestamp.

---

## 4. Authoritative Sources for Expected Outputs

| Entity / Metric | Authoritative Source | Derivation Method | Expected Formats / Values |
|---|---|---|---|
| Currency Formatting | `ORIGINAL_REQUEST.md` §R1, `PROJECT.md` §Interface Contracts | Valid number: pt-BR currency formatting.<br>Null/undefined/NaN: explicit unavailability. | `R$ 1.234,56` (valid)<br>`Indisponível` (invalid) |
| Percentage Formatting | `ORIGINAL_REQUEST.md` §R1, `PROJECT.md` §Interface Contracts | Valid number: signed percentage with 2 decimals.<br>Null/undefined/NaN: explicit unavailability. | `+1,25%` / `-0,42%` (valid)<br>`Indisponível` (invalid) |
| KPI Balances | `PROJECT.md` §Feature Inventory (F2, F10) | Read directly from `positions.capital` fields without fallback to `0`. | Tabular currency or `Indisponível` badge |
| Fail-Closed Banner | `PROJECT.md` §Interface Contracts (`FailClosedBanner`) | Rendered when `connected === false` or `apiError !== null`. | Banner with `"FAIL-CLOSED"` / `"DADOS INDISPONÍVEIS"` |
| Provenance Digest | `PROJECT.md` §Interface Contracts (`ProvenanceTooltip`) | 64-character lowercase hexadecimal string (`^[a-f0-9]{64}$`). | Truncated `8...8` monospace with full 64-char copy |
| Observation Timestamp | `PROJECT.md` §Interface Contracts (`ProvenanceTooltip`) | ISO-8601 string parsed into UTC and Brasilia (BRT) time. | `DD/MM/YYYY HH:mm:ss UTC` |

---

## 5. Test Suite File Structure & Organization

```
src/tests/
├── setupTests.js                  # Global test harness: JSDOM mocks, clipboard mock, jest-dom
├── e2e_honest_states.test.jsx     # Master E2E suite: 502, 503, network drop, null/empty payloads
├── formatters.test.jsx            # Tier 1 & 2 tests for honest formatting engine
├── CapitalVault.test.jsx          # Tier 1, 2, 3 tests for CapitalVault hardening
├── PositionNarrative.test.jsx     # Tier 1, 2, 3 tests for PositionNarrative hardening
├── RiskMetricsPanel.test.jsx      # Tier 1, 2, 3 tests for RiskMetricsPanel & Provenance
└── AppDisconnection.test.jsx      # Tier 1, 3, 4 tests for App fail-closed pipeline
```

---

## 6. Test Execution & Verification

### Running the Tests
```powershell
# Run the complete test suite
npm.cmd test

# Run tests in watch mode
npm.cmd run test:watch

# Run only E2E honest states test
npx.cmd vitest run src/tests/e2e_honest_states.test.jsx
```

### Coverage Thresholds Required
- **Honest State Coverage**: 100% of primary KPI fields, narrative values, vault balances, and risk metrics verified against null/502/503 coercion.
- **Fail-Closed Verification**: 100% of interactive boleta and capital movement actions verified disabled during disconnection.
- **Provenance Integrity**: 100% of tested provenance tooltips verify 64-character hash pattern, timestamp format, and copy handler.

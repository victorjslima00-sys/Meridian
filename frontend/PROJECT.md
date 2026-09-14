# Project: Meridian Institutional Frontend Reconstruction & Hardening

## Architecture
- **Framework & Build**: React 19 + Vite 8 on Node 24 (Windows PowerShell execution using `npm.cmd`).
- **State & Data Pipeline**: Fail-closed API client (`src/api.js` / `App.jsx`), centralized honest formatters (`src/utils/formatters.js`), resilient component-level error boundaries.
- **Design System**: Bloomberg / BTG Pactual Tier-1 Institutional Brokerage theme. Obsidian dark palette (`#06080C` to `#1F293D`), Imperial Gold / Champagne accents (`#C5A059`, `#DFBF7A`), tabular monospace typography (`JetBrains Mono`, `font-variant-numeric: tabular-nums`).
- **Audit & Provenance**: Cryptographic provenance verification tooltips (`source_ref`, 64-char `source_sha256`, `observed_at`), explicit connection status badges ("FAIL-CLOSED ATIVO", "AUDITORIA CONFORME", "NÃO VERIFICADO", "INDISPONÍVEL").
- **Testing Architecture**: Vitest + React Testing Library + JSDOM for component tests and opaque-box requirement-driven E2E tests (Tiers 1-4).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Dependency Restoration & Build Tooling | Install npm dependencies via `npm.cmd install`, align linter (`oxlint`), configure Vitest test runner in `vite.config.js` | M1 | ORIGINAL_REQUEST §R3 |
| 2 | Honest Formatting Engine | Create `src/utils/formatters.js` returning explicit `"Indisponível"` / `"Não Verificado"` instead of `R$ 0,00` or `0,0%` on null/undefined/NaN | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Disconnection & Fail-Closed State Pipeline | State machine in `App.jsx` capturing API 502/503/timeouts without zeroing balances; renders prominent Fail-Closed warning banner | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Elimination of Synthetic Defaults | Remove fabricated defaults (`capital || 100`, `"Aprovado. Risco avaliado dinamicamente."`, `"Conexão segura estabelecida."`) | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Obsidian Dark Design Tokens | Implement Tier-1 Bloomberg/BTG Obsidian Dark palette (`#06080C` to `#1F293D`) in `src/index.css` replacing ad-hoc cyan/red | M2 | ORIGINAL_REQUEST §R2 |
| 6 | Gold & Champagne Accents | Refined Imperial Gold/Champagne accent system (`#C5A059`, `#DFBF7A`) for borders, focus states, and primary metrics | M2 | ORIGINAL_REQUEST §R2 |
| 7 | Tabular Typography Enforcement | Apply `font-variant-numeric: tabular-nums lining-nums` across all currency, percentages, ratios, and numeric tables | M2 | ORIGINAL_REQUEST §R2 |
| 8 | Institutional Connection Status Badges | Dynamic header status badges: "FAIL-CLOSED ATIVO", "AUDITORIA CONFORME", "NÃO VERIFICADO", "SEM CONEXÃO" | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Cryptographic Provenance Tooltip Component | `ProvenanceTooltip` displaying `source_ref`, 64-char `source_sha256`, `observed_at`, and verification badge with copy action | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Hardened CapitalVault Component | Refactor `CapitalVault.jsx`: eliminate `?? 0`, render honest unavailability badges, integrate provenance tooltips on patrimônio | M2 | ORIGINAL_REQUEST §R1, R2 |
| 11 | Hardened PositionNarrative Component | Refactor `PositionNarrative.jsx`: eliminate `formatMoeda(0)` & false green gains on null PnL; render explicit empty/error states | M2 | ORIGINAL_REQUEST §R1, R2 |
| 12 | Hardened RiskMetricsPanel Component | Refactor `EliteCharts.jsx` / `RiskMetricsPanel`: handle 502/503 without infinite hang, render honest badges & provenance metadata | M2 | ORIGINAL_REQUEST §R1, R2 |
| 13 | Hardened ActiveTradeDetails & DecisionLog | Clean up `ActiveTradeDetails.jsx` and `DecisionLog.jsx`: eliminate synthetic approvals and initial fabricated logs | M2 | ORIGINAL_REQUEST §R1, R2 |
| 14 | Opaque-Box E2E Test Harness & Runner | Standalone test runner and harness deriving test cases from user requirements (Tiers 1-4) | E2E-TEST | ORIGINAL_REQUEST §R3 |
| 15 | Component Disconnection & Empty State Unit Tests | Comprehensive component-level tests verifying no false zeros on null/502/503 states across all cards | E2E-TEST | ORIGINAL_REQUEST §R3 |
| 16 | Production Build Verification (`npm.cmd run build`) | Vite build succeeds cleanly with exit code 0 producing `dist/` bundle without errors | M3 | ORIGINAL_REQUEST §R3 |
| 17 | Code Quality & Linter Compliance (`npm.cmd run lint`) | Clean oxlint run with zero blocking errors across all source files | M3 | ORIGINAL_REQUEST §R3 |
| 18 | Adversarial Coverage Hardening (Tier 5) | White-box adversarial testing with Challenger & Forensic Auditor verifying genuine logic and zero cheating | M3 | ORIGINAL_REQUEST §Audit |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E-TEST | E2E Testing Track | Requirement-driven test suite (Tiers 1-4) + test runner setup, publishing `TEST_READY.md` | none | IN_PROGRESS |
| M1 | Dependencies & Honest State Core | `npm.cmd install`, `src/utils/formatters.js`, API fail-closed error pipeline, eliminate synthetic zero coercions in data model | none | IN_PROGRESS |
| M2 | Institutional Design System & Hardened Components | Obsidian/Gold tokens, tabular typography, badges, `ProvenanceTooltip`, refactor `App.jsx`, `CapitalVault.jsx`, `PositionNarrative.jsx`, `RiskMetricsPanel.jsx` | M1 | PLANNED |
| M3 | Production Build, 100% E2E Pass & Adversarial Hardening | Pass 100% E2E tests, clean `npm.cmd run build` and `npm.cmd run lint`, Tier 5 adversarial stress-testing + Forensic Audit | M2, E2E-TEST | PLANNED |

## Interface Contracts

### Formatters (`src/utils/formatters.js`)
- `formatCurrency(value: number | null | undefined, options?: object): string | JSX.Element`
  - If `value == null` or `isNaN(value)`: returns `<span className="badge-unavailable">Indisponível</span>` (or string `"Indisponível"` depending on mode).
  - If valid: returns formatted `R$ 1.234,56` with tabular digits.
- `formatPercent(value: number | null | undefined, options?: object): string | JSX.Element`
  - If `value == null` or `isNaN(value)`: returns `<span className="badge-unavailable">Indisponível</span>`.
  - If valid: returns formatted `+1,25%` or `-0,42%`.
- `formatMetricValue(record: MetricRecord | null | undefined): JSX.Element`
  - Checks `record?.verification_status`. If `"unverified"` or `"unavailable"`, renders explicit status badge with provenance tooltip.

### Provenance Tooltip Component (`src/components/ProvenanceTooltip.jsx`)
- Props:
  - `provenance`: `{ source_ref?: string, source_sha256?: string, observed_at?: string, verification_status?: string }`
  - `label`: `string`
  - `children`: `ReactNode`
- Renders:
  - Accessible trigger with information icon or status dot.
  - Floating popover/tooltip displaying source ref, truncated SHA256 (with copy-to-clipboard button), ISO and localized timestamp, and verification badge.

### Connection & Fail-Closed Banner (`src/components/FailClosedBanner.jsx` / `App.jsx`)
- Props / State:
  - `connected`: `boolean`
  - `apiError`: `string | null`
  - `isFailClosed`: `boolean`
- Behavior:
  - When disconnected or HTTP 502/503 occurs: displays full-width high-priority warning banner ("PROTEÇÃO FAIL-CLOSED ATIVADA - DADOS DE MERCADO INDISPONÍVEIS").
  - Disables trading buttons and interactive order inputs.

## Code Layout
```
frontend/
├── package.json
├── vite.config.js
├── index.html
├── src/
│   ├── main.jsx
│   ├── App.jsx
│   ├── index.css
│   ├── components/
│   │   ├── CapitalVault.jsx
│   │   ├── PositionNarrative.jsx
│   │   ├── RiskMetricsPanel.jsx
│   │   ├── ProvenanceTooltip.jsx
│   │   ├── FailClosedBanner.jsx
│   │   └── StatusBadges.jsx
│   ├── utils/
│   │   └── formatters.js
│   └── tests/
│       ├── setupTests.js
│       ├── formatters.test.jsx
│       ├── CapitalVault.test.jsx
│       ├── PositionNarrative.test.jsx
│       ├── RiskMetricsPanel.test.jsx
│       ├── AppDisconnection.test.jsx
│       └── e2e_honest_states.test.jsx
```

# Original User Request

## Initial Request — 2026-09-13T23:27:45Z

Reconstruct and harden the Meridian Institutional React Frontend: eliminate all synthetic zero fallbacks that mask API errors as healthy states, render explicit provenance metadata with unverified/unavailable indicators, apply a Tier-1 Institutional Brokerage design system (Bloomberg/BTG-style), and establish clean Vite production build verification.

Working directory: C:\Users\BIRTUS JANIO\Documents\Codex\2026-09-11\oque\work\Meridian\frontend  
Integrity mode: development  

## Requirements

### R1. Elimination of False Zeros & Explicit State Rendering
Refactor `App.jsx`, `CapitalVault.jsx`, `PositionNarrative.jsx`, `RiskMetricsPanel.jsx`, and all formatting utilities. Never coerce missing, unverified, or errored API values (such as `null`, HTTP 502/503 responses, or unapproved metrics) into `0`, `0.0%`, or healthy default numbers. Render explicit "Indisponível" / "Não Verificado" badges and preserve honest disconnection states.

### R2. Institutional Brokerage Design System
Elevate the interface to high-end financial terminal standards: obsidian dark aesthetic with refined gold/champagne accents, tabular typography (`font-variant-numeric: tabular-nums`) for currency and percentages, clear connection status badges (Fail-Closed Ativo, Auditoria Conforme), and hoverable tooltips displaying metric provenance metadata (`source_ref`, `source_sha256`, `observed_at`).

### R3. Production Build & Component Verification
Resolve npm dependencies and ensure the Vite production build compiles with zero errors (`npm.cmd run build`). Implement component-level tests verifying that API disconnections and empty states render appropriate warning banners rather than collapsing or displaying misleading figures.

## Acceptance Criteria

### UI Integrity & Error Handling
- [ ] No API error (502, 503, timeout, or network drop) converts values into healthy zeros (`R$ 0,00` or `0%`).
- [ ] Unverified or unapproved metrics explicitly display "Indisponível" or "Aguardando Aprovação".
- [ ] Verified metrics show provenance tooltips containing source reference, SHA-256 hash, and observation timestamp.
- [ ] No synthetic hardcoded balances (e.g. literal R$ 1.000.000) exist in component state or templates.

### Build & Code Quality
- [ ] `npm.cmd run build` executes cleanly with exit code 0 and produces production artifacts in `dist/`.
- [ ] `npm.cmd run lint` (or project linter) passes without blocking errors.
- [ ] Component rendering is robust against malformed or missing JSON payloads from backend endpoints.

---
*Verification Resources:*
- `frontend/package.json`
- `frontend/src/App.jsx`
- `frontend/src/components/CapitalVault.jsx`
- `frontend/src/components/PositionNarrative.jsx`
- `frontend/src/components/RiskMetricsPanel.jsx`

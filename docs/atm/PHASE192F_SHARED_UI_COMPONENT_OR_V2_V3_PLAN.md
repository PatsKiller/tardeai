# PHASE 192F — Shared UI Component / v2-v3 Plan

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**Decision (operator):** *Backend + v2 now; v3 gets an integration plan + placeholder* (v3 is
actively being rebuilt today — avoid source conflict).

---

## Can it be a single shared component?
**No** — `command-center-v2` and `command-center-v3` are **separate Vite apps** (separate
`node_modules`, builds, and design tokens). A single importable module across them isn't possible
without a shared package. **The API is fully shared** (identical `useApi<T>` + `{ok,data}`), so the
component is **near-identical per app**, differing only in styling tokens.

## Component: `ProtectionAdjustmentPanel`
Implemented for v2 at `apps/command-center-v2/src/components/ProtectionAdjustmentPanel.tsx`.
Displays per open trade:
- current broker stop · whether it locks profit · take-profit missing
- TradeAI recommendation (color by severity) · Hermes second opinion
- proposed adjustment cards: before → after stop / profit-lock / giveback
- quote freshness · **paper-only badge** · "no auto-execution" badge
- buttons: Review Move Stop · Review Add Take-Profit · Review Trailing Stop · Keep Current ·
  Reject Advisory · Needs More Evidence — **disabled/review-gated** (execution via guarded
  `/approve` endpoint only).

Data sources (both apps): `GET /api/v2/atm/profit-protection-advisory` +
`GET /api/v2/atm/protection-adjustment-proposals`.

## v3 equivalent (plan — see 192H)
Add an equivalent panel to `apps/command-center-v3/src/pages/TradingHub.tsx` using the same two
endpoints and the v3 design tokens (`--text3`, `--bg1`, hub card layout). Identical fields, labels,
paper-only badge, and disabled buttons. v3 source intentionally **not** edited this phase to avoid
conflicting with the operator's in-flight v3 rebuild; the exact insertion is specified in 192H.

## Parity guarantee
Because both apps consume the **same** endpoints with the **same** `useApi` contract, parity is
structural: the only per-app work is the presentational component. v2 is shipped; v3 is specified
and route-ready.

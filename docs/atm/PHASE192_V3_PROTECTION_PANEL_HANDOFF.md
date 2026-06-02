# Phase 192 → Command Center v3 Protection Panel — HANDOFF

**For:** the Claude Code session that owns the Command Center **v3** rebuild.
**From:** the Phases 188–192 protection workstream.
**Date:** 2026-06-02 · Alpaca **paper** only.

> **Context:** the doc index now marks **v3 as canonical (source of truth)** and **v2 as frozen**.
> The protection/profit-protection workflow backend is **done and live**; only the v3 UI panel
> remains. v2 has a working reference component to port. **This is a pure frontend task** — no
> backend changes needed (the API is shared and identical between v2 and v3).

---

## TL;DR — what to do
Add a `ProtectionAdjustmentPanel` to **`apps/command-center-v3/src/pages/TradingHub.tsx`** that
renders the profit-protection advisory + adjustment proposals from two **already-live** endpoints,
using v3's existing `useApi` hook and design tokens. Buttons stay **advisory/disabled** (execution
is a separate guarded endpoint). Build v3, verify at `/v3/trading`.

---

## Backend that already exists (live, shared, no changes needed)

| Endpoint | Method | Returns |
|---|---|---|
| `/api/v2/atm/profit-protection-advisory` | GET | per-trade TradeAI action + Hermes opinion + audit |
| `/api/v2/atm/protection-adjustment-proposals` | GET | adjustment candidates grouped by trade |
| `/api/v2/atm/protection-adjustment-proposals/:id` | GET | one proposal detail |
| `/api/v2/atm/protection-adjustment-proposals/:id/approve` | POST | guarded execution (operator only) |
| `/api/v2/atm/protection-coverage` | GET | protection coverage counts (Phase 190) |

All return the standard `{ok, data}` envelope (v3's `useApi` already unwraps it).

### `/api/v2/atm/profit-protection-advisory` data shape
```json
{ "advisories": [ {
    "trade_id": 48, "symbol": "ANY", "data_state": "STRATEGY_METADATA_MISSING",
    "tradeai": { "action": "URGENT_PROTECTION_REVIEW", "reason": "...",
      "supporting": ["TAKE_PROFIT_ADVISORY","LOCK_PROFIT_ADVISORY"],
      "unrealized_pnl": 402.35, "unrealized_pct": 20.1, "current_broker_stop": 3.56,
      "stop_locks_profit": true, "profit_locked_usd": 201.18, "giveback_to_stop_usd": 201.17,
      "take_profit_exists": false, "trailing_threshold_met": false },
    "hermes": { "opinion": "caution", "reason": "..." },
    "operator_action_required": true,
    "decision_support": ["Keep current stop","Move to breakeven review", "..."]
  } ], "action_required_count": 1 }
```

### `/api/v2/atm/protection-adjustment-proposals` data shape
```json
{ "trades": [ { "trade_id": 48, "symbol": "ANY", "candidates": [
    { "id": 21, "action": "MOVE_STOP_TO_PROFIT_LOCK",
      "current_stop": 3.56, "proposed_stop": 3.81,
      "profit_locked_before": 201.18, "profit_locked_after": 360.0,
      "giveback_before": 201.17, "giveback_after": 42.0,
      "tradeai_reason": "Lock ~50% of unrealized gain.", "hermes_reason": "...",
      "alpaca_supported": true, "expected_api": "PATCH /v2/orders/<stop_id> (replace, paper)",
      "status": "PROPOSED" }, ... ] } ],
  "proposal_count": 22, "paper_only": true, "requires_operator_approval": true, "no_live_execution": true }
```

---

## v2 reference implementation (port this to v3)
File: `apps/command-center-v2/src/components/ProtectionAdjustmentPanel.tsx` (committed). It:
- `useApi('/api/v2/atm/profit-protection-advisory', 30000)` + `useApi('/api/v2/atm/protection-adjustment-proposals', 60000)`
- renders per trade: **TradeAI** (action badge colored by severity: URGENT→red, others→amber,
  NO_ACTION→green; P&L, stop, locks-profit, giveback, TP status) and **Hermes** (opinion + reason)
- lists proposal candidates (excluding `KEEP_CURRENT_STOP`) as before→after rows
  (stop / profit-lock / giveback)
- shows **paper-only** + **no-auto-execution** badges
- renders 6 **disabled** buttons: Review Move Stop · Review Add Take-Profit · Review Trailing Stop ·
  Keep Current · Reject Advisory · Needs More Evidence

v3 differences to apply: use v3 CSS tokens (`--text3`, `--bg1`, hub card styling) and the v3
`useApi` (same signature). Place it in `TradingHub.tsx` after the open-trades section. v3's
`TradingHub` already declares "Read-only — no trade controls" — keep the buttons disabled to honor
that until a v3 execution-UX is designed.

### Minimal v3 component skeleton
```tsx
import { useApi } from '../hooks/useApi'
export default function ProtectionAdjustmentPanel() {
  const { data: adv } = useApi<any>('/api/v2/atm/profit-protection-advisory', 30000)
  const { data: props } = useApi<any>('/api/v2/atm/protection-adjustment-proposals', 60000)
  const advisories: any[] = adv?.advisories || []
  const propsFor = (tid: number) =>
    (props?.trades?.find((t: any) => t.trade_id === tid)?.candidates) || []
  if (!advisories.length) return null
  // render TradeAI action + Hermes opinion + propsFor(trade_id) before→after + disabled buttons
}
```
Then in `TradingHub.tsx`: `import ProtectionAdjustmentPanel from '../components/ProtectionAdjustmentPanel'`
and render `<ProtectionAdjustmentPanel />` below the open-trades block. Build:
`cd apps/command-center-v3 && npm run build`. Served by `portfolio_server.py` at `/v3/trading`
(no-cache; no restart needed for the frontend).

---

## Execution path (do NOT wire to live buttons without operator UX)
Execution is the guarded POST `/approve` endpoint, engine `scripts/apply_paper_protection_adjustment.py`:
- paper-only assert, quote-fresh (≤30m), broker-stop-state must match expected, **stop-up-only**,
  **replace-only** (stop never absent), audit before+after, `confirm=false` ⇒ DRY_RUN_PREVIEW.
- Only `MOVE_STOP_TO_PROFIT_LOCK` / `MOVE_STOP_TO_BREAKEVEN` execute this phase.
- If/when v3 adds a live "Apply" button, POST `{operator, reason, confirm:true}` to
  `/api/v2/atm/protection-adjustment-proposals/:id/approve` — but design an explicit confirm modal
  first (this modifies a real paper order).

---

## IMPORTANT — live data has changed (so your panel will look different than the docs)
**ANY's profit-lock was EXECUTED by the operator on 2026-06-02.** ANY's paper stop moved
**3.07 → 3.56** (broker order id `9cb5cb32`), now `stop_locks_profit: true`, `profit_locked_usd ≈ 201`.
So when you render the panel, ANY may show a *reduced* urgency (it now locks profit) and new
proposal candidates relative to the 3.56 stop. This is expected — the workflow round-tripped.

## Guardrails to preserve in v3
Buttons advisory/disabled by default · paper-only badge visible · never auto-execute · all numbers
trace to the real endpoints above (honest placeholders only, per the v3 canonical-doc standard).

## Files to read
- `apps/command-center-v2/src/components/ProtectionAdjustmentPanel.tsx` (reference)
- `apps/command-center-v2/src/pages/PaperStatus.tsx` (wiring example)
- `docs/atm/PHASE192A_COMMAND_CENTER_V2_V3_PARITY_INVENTORY.md` (inventory)
- `docs/atm/PHASE192F_SHARED_UI_COMPONENT_OR_V2_V3_PLAN.md`, `…192H…V3_WIRING_REPORT.md`
- `docs/atm/PHASE191D_TRADEAI_PROFIT_PROTECTION_SCORING_MODEL.md` (what the actions mean)

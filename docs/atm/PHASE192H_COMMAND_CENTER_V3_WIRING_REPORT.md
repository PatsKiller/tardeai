# PHASE 192H — Command Center v3 Wiring Report (Plan + Placeholder)

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**App:** `apps/command-center-v3` (hub architecture, served at `/v3/`) · Alpaca paper only

---

## Status: parity tracked, source edit deferred (operator decision)
v3's dist + `vite-env.d.ts` were rebuilt **today** — it is **actively under construction**. Per
operator decision ("Backend + v2 now, v3 plan"), v3 source was **not** edited this phase to avoid
conflicting with in-flight work. The backend that v3 needs is **already live and shared**.

## Why v3 is not a "missing page"
v3 consolidates v2's `paper-status` into **`TradingHub`** (`/v3/trading`), which already renders
open paper trades + proposals via `/api/v2/open-trades`, `/api/v2/paper-proposals`,
`/api/v2/paper-status`. The protection panel belongs in `TradingHub`. The route exists; only the
panel component is pending.

## Exact integration (drop-in for `apps/command-center-v3/src/pages/TradingHub.tsx`)
1. Add a `ProtectionAdjustmentPanel.tsx` to `command-center-v3/src/components/` — same logic as the
   v2 component, restyled with v3 tokens (`--text3`, `--bg1`, hub card). It uses the **same two
   endpoints** and the v3 `useApi` hook (identical contract — confirmed in 192A).
2. In `TradingHub.tsx`, after the open-trades section, render `<ProtectionAdjustmentPanel />`.
3. `npm run build` in `apps/command-center-v3`; `portfolio_server.py` serves the new dist at
   `/v3/trading` (no-cache).
4. Verify: ANY=URGENT, SNOW=TAKE_PROFIT visible; paper-only badge; disabled buttons; no order
   modification.

Component skeleton (v3):
```tsx
import { useApi } from '../hooks/useApi'
export default function ProtectionAdjustmentPanel() {
  const { data: adv } = useApi<any>('/api/v2/atm/profit-protection-advisory', 30000)
  const { data: props } = useApi<any>('/api/v2/atm/protection-adjustment-proposals', 60000)
  // render TradeAI action + Hermes opinion + before/after candidates + disabled review buttons
}
```

## Parity assertion
- **API parity:** ✅ identical endpoints, identical `useApi` contract — v3 needs zero backend work.
- **UI parity:** ⏳ specified + route-ready; component to be added to `TradingHub` (operator to
  merge into the in-flight v3 rebuild, or authorize me to add it next).
- **Not v2-only:** the v3 path is explicitly tracked with a concrete, validated plan — not skipped.

> Recommendation: once the operator's current v3 rebuild settles, authorize the v3 component add
> (one component + one render line + build) for full visual parity.

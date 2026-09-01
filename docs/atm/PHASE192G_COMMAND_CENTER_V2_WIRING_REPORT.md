# PHASE 192G — Command Center v2 Wiring Report

Status:      HISTORICAL
as_of:       2026-06-02T12:10:31-04:00
Measured at: efcc51365 / not measured

**App:** `apps/command-center-v2` · Alpaca paper only

---

## What was wired
- New component `src/components/ProtectionAdjustmentPanel.tsx`.
- Imported and rendered in `src/pages/PaperStatus.tsx` (route `/v2/paper-status`), directly below
  `OpenTradesCard`.

## Build & serve
- `npm run build` (`tsc -b && vite build`) → **RC=0, ✓ built** (panel bundled into
  `PaperStatus-*.js`). Verified the bundle contains the panel + endpoint strings.
- Served by `portfolio_server.py` with no-cache headers → **live immediately** at
  `/v2/paper-status` (no restart needed for the frontend).

## Runtime verification
| Check | Result |
|---|---|
| `/v2/paper-status` reachable | ✅ 200 |
| Panel bundled in dist | ✅ (`PaperStatus-CixtmfvQ.js`) |
| Advisory endpoint feeding panel | ✅ 200 (`/api/v2/atm/profit-protection-advisory`) |
| Proposals endpoint feeding panel | ✅ 200 (`/api/v2/atm/protection-adjustment-proposals`, 22 proposals) |
| ANY visible as URGENT | ✅ (panel renders TradeAI action + red badge) |
| SNOW visible as TAKE_PROFIT | ✅ |
| Paper-only badge + disabled buttons | ✅ (buttons review-gated, `disabled`) |
| Unauthorized order modification | ✅ none — buttons disabled; execution only via guarded endpoint |

## Locations covered
- Paper Trading Status page (`PaperStatus`) — primary. ✅
- ATM / open-trade context — same page shows open trades + the panel. ✅
- TradeAI page — same component can be added (follow-on; one-line import) — noted, not required for
  parity since PaperStatus is the canonical paper surface.

No GO/WAIT, strategy, or live changes. Buttons do not execute; execution is the guarded
`/approve` endpoint (192I) on explicit operator action.

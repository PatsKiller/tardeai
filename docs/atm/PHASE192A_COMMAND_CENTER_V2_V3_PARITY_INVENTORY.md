# PHASE 192A — Command Center v2 / v3 Parity Inventory

Status:      HISTORICAL
as_of:       2026-06-02T11:52:03-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~11:30 ET · Validation gate for Phase 192 · Alpaca **paper** only

---

## Both Command Centers are REAL and LIVE
Served by `scripts/portfolio_server.py` (the `tradeai-portfolio-server.service` on :7777):
- **v2** at `/v2/` → `apps/command-center-v2/dist` (dist built 2026-06-01 23:19) — `GET /v2/` → 200
- **v3** at `/v3/` → `apps/command-center-v3/dist` (dist built **2026-06-02 11:21 ET — today**) — `GET /v3/` → 200

`/v3/` serving code: `portfolio_server.py:1141-1160`. **v3 is actively under construction** (`vite-env.d.ts`
touched today). This confirms the operator's point: v2-only wiring would be incomplete.

## Command Center v2
- **App path:** `apps/command-center-v2` (Vite + React + TS, 98 pages in `src/pages/`)
- **Routes (App.tsx):** granular — incl. `paper-status` (`PaperStatus`), `trade-ai` (`TradeAI`),
  `paper-proposals`, `paper-review`, `execution-quality`, `broker-reconciliation`, `journal`, `risk`.
- **ATM / open-trade page:** `paper-status` (PaperStatus.tsx) + `trade-ai` (TradeAI.tsx)
- **Paper Trading Status page:** `PaperStatus.tsx` → `useApi('/api/v2/paper-status')` + open-trade-monitor
- **Profit-protection panel location (target):** PaperStatus.tsx / TradeAI.tsx (none today)
- **API calls:** `useApi<T>(path, intervalMs)` (`src/hooks/useApi.ts`) — unwraps `{ok,data}`
- **Component files:** `src/pages/*.tsx`, shared bits in `src/lib/`, `src/hooks/`

## Command Center v3
- **App path:** `apps/command-center-v3` (Vite + React + TS) — **hub architecture, 11 pages**
- **Routes (App.tsx):** consolidated hubs — `portfolio`, `risk`, **`trading`**, `strategy`,
  `agents`, `intelligence`, `hermes`, `retirement`, `journal`, `system`, home.
- **ATM / open-trade page:** **`TradingHub.tsx`** (`/v3/trading`) — already shows open trades +
  paper proposals via `/api/v2/open-trades`, `/api/v2/paper-proposals`, `/api/v2/paper-status`.
  Explicit note in code: *"Read-only — no trade controls."*
- **Paper Trading Status page:** consolidated into `TradingHub` (no separate route)
- **Profit-protection panel equivalent (target):** `TradingHub.tsx` (none today)
- **API calls:** `useApi<T>(path, intervalMs)` (`src/hooks/useApi.ts`) — **same shape as v2**,
  unwraps `{ok,data}`
- **Component files:** `src/pages/*Hub.tsx`, `src/components/`, `src/hooks/useApi.ts`

## Parity assessment
| Question | Answer |
|---|---|
| v2 target component exists | **NO** (must add ProtectionAdjustmentPanel to PaperStatus/TradeAI) |
| v3 target component exists | **NO** (must add to TradingHub) |
| Shared component possible (single file) | **NO** — separate Vite apps, separate builds/styles; **equivalent** component per app instead |
| API shared | **YES** — identical `useApi` + `{ok,data}`; one backend serves both |
| v3 has the same *page*? | **No 1:1** — v3 consolidates paper-status into `TradingHub` (a hub). Not a missing page; a different shape. |

## Parity gap list
1. **Backend (shareable):** new endpoints `/api/v2/atm/protection-adjustment-proposals[/:id]` and the
   guarded approval endpoint serve both apps unchanged. **No parity risk.** ✅ (build once)
2. **UI v2:** add `ProtectionAdjustmentPanel` to `PaperStatus.tsx` (+ TradeAI.tsx).
3. **UI v3:** add equivalent panel to `TradingHub.tsx` (same API, fields, labels, paper-only badge,
   guarded buttons). v3 currently declares "no trade controls" — the panel stays advisory/review-gated.
4. **Shared-source option:** since v2 and v3 are separate builds, the component is duplicated (or a
   tiny shared snippet copied); documented in 192F. Not a single importable module.

## Risk note (operator decision needed before editing v3 source)
v3's dist was **rebuilt today** and `vite-env.d.ts` changed today — v3 is **actively being worked**.
Editing v3 source now could conflict with in-flight work. Recommend confirming whether to (a) add the
panel to v3 `TradingHub` now, or (b) ship backend + v2 now and provide a v3 integration plan +
route/placeholder for the operator to merge. Either way, **v3 parity is tracked, not skipped.**

## Conclusion
Phase 192 backend is **frontend-neutral** and serves both. UI parity requires an equivalent panel in
v2 (`PaperStatus`/`TradeAI`) and v3 (`TradingHub`). v3 is real and live, so v2-only is not acceptable;
the only open question is timing of the v3 source edit given it is actively under construction.

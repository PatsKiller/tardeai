# PHASE 197 — Surface Profit-Protection Outcomes in v3 Journal Hub — CLOSEOUT

Status:      HISTORICAL
as_of:       2026-06-02T13:29:36-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~13:30 ET · Alpaca **paper** only · read-only UI; no execution

---

## What shipped
- **`apps/command-center-v3/src/components/ProtectionOutcomesPanel.tsx`** — consumes the live
  `GET /api/v2/atm/protection-advisory-outcomes` (built in Phase 193/194), matching v3 conventions
  (`useApi`, `fmt$`, `DrillContext`/`onDrill`, hub card styling, Source footer).
- **`JournalHub.tsx`** — new **"Protection"** tab (4th tab) rendering the panel.

## What it shows (all bar-validated, honest)
- KPI strip: **% gave back**, **$ left on table**, **measurable / total**, **operator acted**.
- **Operator-adjusted (in flight):** ANY — `MOVE_STOP_TO_PROFIT_LOCK`, stop 3.07→3.56, locked ~$204,
  giveback avoided.
- Per-trade give-back table (symbol · realized · left-on-table · gave-back), biggest give-back first,
  each row clickable → DetailDrawer.
- Footer notes unmeasurable count (currently 0 — full coverage after Phase 196).

Current live values: **83% gave back, $2,646 left on table, 24/24 measurable.**

## Verification
| Check | Result |
|---|---|
| v3 build (`npm run build`) | ✅ RC=0 (`✓ built`) |
| Panel + endpoint in dist | ✅ |
| `/v3/journal` reachable | ✅ 200 |
| Outcomes endpoint live | ✅ 200 |
| v3 tree clean before edit (no collision with v3 session) | ✅ |

## Closeout fields
- **Phase 197 complete:** ✅ YES
- **v3 Journal Protection tab added:** ✅ YES (built + served, live on `/v3/journal`)
- **Consumes shared endpoint:** ✅ `/api/v2/atm/protection-advisory-outcomes`
- **Honest data:** ✅ give-back scored only on bar-based MFE; unknowns not fabricated
- **No execution / no stop changes / no orders / no backend changes:** ✅ YES (pure v3 frontend)
- **Live trading:** ZERO · **GO/WAIT mutation:** ZERO · **Strategy mutation:** ZERO · **Level 7:** PROHIBITED
- **Next recommended gate:** **Phase 198 — advisory threshold tuning** once ANY/SNOW (and future
  advised trades) close and produce real `confirmed`/`contradicted` accuracy, feeding the 191D
  scoring thresholds; optionally add the same Protection view to the v3 Trading hub for at-a-glance.

## Coordination note
v3 is canonical and actively maintained by a parallel session; this edit was made with a clean v3
working tree to avoid collision. The component is additive (new file + one tab) and consumes only
existing endpoints, so it composes cleanly with the v3 session's work.

## Guardrail attestation
No live account/endpoint/broker mode, no live trades, no holdings mutated, no stops moved, no
strategy/config/GO-WAIT changes, Level 7 not enabled, auto-update not run. Pure additive v3 frontend.

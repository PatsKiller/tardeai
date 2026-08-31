# Reports Command Portal — Phase 2 UX Hardening (2026-06-21)

Status:      HISTORICAL
as_of:       2026-06-21T17:58:04-04:00
Measured at: efcc51365 / not measured

Refined (not rebuilt) the Reports Command Portal into a true operator triage page. Advisory/read-only
throughout — no broker actions, no order execution, no trading-gate or purge-semantics changes.

Files: `scripts/reports_portal.py` (classifier), `apps/command-center-v3/src/pages/ReportsHub.tsx` (UI).

## Phase 1 — Action-extraction false positives (`reports_portal.py`)

The deterministic classifier (`extract_action_items` / `_ACT_RULES`) was over-firing on recovery-watch rows.

- **`stop_triggered`** regex tightened to TRUE trigger language only: `stops triggered`, `N stops triggered`,
  `triggered a stop`, `protective stop filled`, `stop filled`, `stop-loss (order) (was) triggered`,
  `position may be flat`. The bare `stop[\s-]?out` clause — which fired on `Relisted — No Stop-Out` — was
  **removed**.
- **Negation guard** (`_NEG_STOP`, applied per-class in `extract_action_items`): any matched occurrence whose
  surrounding line carries `no stop-out` / `not a stop-out` / `no stop loss triggered` /
  `Relisted — No Stop-Out` is skipped; if every occurrence is negated the class is not emitted.
- **`unprotected_position`** now requires explicit `without stops` / `unprotected` / `no protective stop` /
  `large positions without stops` / `naked stop|position`. The old bare `no stop` clause (which matched
  `No Stop-Out`) was removed.
- "market reconnection" / "relist" / "reentry candidate" do not classify as system_health (the regex never
  matched `event`; confirmed).
- **Verification** — `python3 scripts/reports_portal.py --verify` (`_verify_actions()`), deterministic, no DB/LLM:
  | input | expect |
  |---|---|
  | `Relisted — No Stop-Out` (recovery) | NOT stop_triggered / unprotected |
  | `8 stops triggered` | stop_triggered |
  | `6 large positions without stops` | unprotected_position |
  | `stop FILLED — position may be flat` | stop_triggered |
  | `cron failed` | system_health |
  | `no stop loss triggered` | NOT stop_triggered |
  All pass. Live effect: total extracted actions 489 → 471, **0** No-Stop-Out misclassifications,
  9 legit `stop_triggered` / 7 `unprotected_position` retained.

## Phase 2 — Action Queue usability (`ReportsHub.tsx`)

- The queue now fetches the **full** extracted set and has its **own** tabs (independent of the page
  quick-views, which filter the report list): **Now · Risk · Approvals · System · Research · All**, each with a
  live count.
- Defaults to **Now** — urgent/critical OR today OR risk/approval/system blockers — **capped at 12** (other
  tabs show up to 40), sorted severity-then-recency.
- **Dedup grouping**: one report emitting both `stop_triggered` and `unprotected_position` shows as a single
  card with both pills (`_classes`); recovery items no longer appear twice as Risk and System.
- Compact count: **“Showing 12 priority actions of 471 extracted”** (+ “N more”), not “306 of 489”.
- Each card: class pills · symbol · one-line text · route button · source category · source date.

## Phase 3 — KPI hierarchy

Action-first row: **Needs action now · Critical / urgent · Risk / stops · Approvals · System blockers ·
Reports today**, each with secondary text (7d total / today count). **Risk/stops** and **Approvals** get
persistent visual priority (tinted border + left rail). Clicking a card focuses the report list *and* the
matching Action Queue tab. Dark theme preserved.

## Phase 4 — Selected report reader

Above the full body (which is unchanged and fully rendered): title + timestamp, source/channel/type, the
synthesis strip, **extracted action pills**, and **“Jump to” Key-section anchor chips** for recognized
markdown headers (Executive Summary · Immediate Risk · Steph Review · Recovery Watch · Ranked Next Actions) —
clicking a chip auto-expands and scrolls the body to that section. Full report markdown rendering retained.

## Phase 5 — Visual polish

Sticky right rail (stays in view, scrolls inside the viewport) with a sticky queue header; selected report
highlighted in the list; consistent severity colors; clearer card spacing; no full-page horizontal overflow.

## Verification

- `python3 -m py_compile scripts/reports_portal.py` → OK; `--verify` → all checks pass.
- `GET /api/v2/reports/action-items?days=7` → 471 actions, 0 No-Stop-Out misclassifications.
- `GET /api/v2/reports/portal-summary?days=7` → KPIs present.
- `npm --prefix apps/command-center-v3 run build` → built clean (tsc + vite).
- Playwright: AQ shows “Showing 12 priority actions of 471 extracted”; tabs render with counts; reader has
  Actions pills + Jump-to chips (4 `rsec-` anchors); **no console errors**.

## Known remaining UX gaps

- Quick-views (top) and Action-Queue tabs are now independent by design; a future pass could unify them.
- Key-section chips cover the Aegis morning-brief structure; other report types (weekly/monthly) use different
  headers not yet in the recognized set.
- Action Queue "Now" cap is fixed at 12 (not user-adjustable).

# ActiveTrader — Live Data Architecture (2026-07-28)

Why the ActiveTrader tab showed **DATA STALE / 2026-07-13** while momentum scalps were
demonstrably firing from 7am, and what now feeds it. Read-only surface; no order path.

## Two distinct engines write two distinct tables

| | `scalp_scan_results` | `scalp_ignition_events` |
|---|---|---|
| **Role** | LIVE momentum-scalp **scanner** (discovery + scoring + routing) | IGN/trigger **shadow logger** + setup **taxonomy** |
| **Runs** | ~every 15 min, **6am–noon incl. premarket** (24h scan cadence) | `scalp_shadow_logger.py --live` cron, **RTH only (09:30–16:00)** |
| **Fields** | score, grade, decision (GO/WAIT/AVOID), route (`momentum_scalp`/`meme_squeeze_momentum`/`watch_only`/…), rvol, gap%, change%, float, sector, scout pillars | IGN score, lane (IGN_45/60/75/ACCEL/TRIGGER/BELOW), 6 subscores, entry/stop ref, spread, primary/matched setup, gate, registry_hash |
| **Timestamp** | `scanned_at` (timestamptz) | `fired_at` / `session_date` |

**The disconnect:** the permission queue read *only* `scalp_ignition_events`. That logger's
`--live` path computes `minute = minute_of_session(now, regular_open=09:30)` and hard-returns
`outside RTH; nothing to log` when `minute < 0`. So **every premarket pass was discarded** and the
queue fell back to the most recent alert-worthy session — 2026-07-13 — rendering "DATA STALE" with
empty setup fields (07-13 rows predate the 07-27 taxonomy deploy). The engine that actually fires
premarket (`scalp_scan_results`) was never read.

## Fix (PR #245, deployed 2026-07-28)

- **`scripts/active_trader/read_api.py`** — `_live_scan_signals()` projects **today's**
  `scalp_scan_results` with REAL scanner fields. It does **not** fabricate IGN or subscores — those
  exist only in `scalp_ignition_events` during RTH. `permission_queue()` now returns
  `engine_live_today`, `engine_window` (`06:00-12:00 ET`), and a `live_scan` block; the IGN
  `data_state` (LIVE_DATA/EMPTY_LIVE_QUEUE/DATA_STALE/API_UNAVAILABLE) is kept **distinct** so the
  two sources are never conflated.
- **`apps/command-center-v3/src/pages/ActiveTraderPage.tsx`** — `LiveScanPanel` leads the page when
  the engine is live today; GO / momentum-route rows are highlighted; the header shows
  `ENGINE LIVE · N SCANS` next to a scoped `IGN TAXONOMY: <state>` chip. No fabricated fields.
- **`scripts/active_trader/export_scalp_fires.py`** — verbose exportable fire log (both tables →
  JSONL + CSV + `summary.json` distributions) for offline tuning:
  `python scripts/active_trader/export_scalp_fires.py --start <d> --end <d>` →
  `data/active_trader/fire_exports/<start>_<end>/`.

## Honest current-state notes (not bugs)

- **Setup taxonomy 100% NULL on existing rows** — all 467 rows in `scalp_ignition_events` predate
  the 2026-07-27 taxonomy-writing deploy. `taxonomy_for_symbol` is verified working
  (`setup_state=ARMED`, `market_session=REGULAR` on recent bars); **today's RTH run populates the
  taxonomy columns automatically.** No code fix required.
- **Premarket IGN/taxonomy is NOT logged** — the IGN shadow logger stays RTH-gated by design.
  Correct premarket IGN requires a **premarket volume profile**; the taxonomy rule *premarket and
  regular denominators are never mixed* forbids scoring premarket cumulative volume against the
  regular-session RVOL curve. Until a premarket profile exists, premarket momentum **fails closed**
  in the IGN path. Premarket **visibility** is already delivered by the live scanner above; adding
  premarket IGN shadow rows is a separate, profile-dependent change (do not hack the denominator).

## Safety posture (unchanged)

Read-only. No POST/order/submitOrder in anything above, no live routing, no LLM authority,
`live_session_enabled` = False. SHADOW / MANUAL_PAPER_TEST_ONLY.

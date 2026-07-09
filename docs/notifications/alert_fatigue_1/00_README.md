# ALERT-FATIGUE-1 — Telegram Alert Routing Fix

**Date:** 2026-05-22
**Problem:** Repeated non-actionable proposal alerts every 2-5 minutes
**Fix:** Central router suppresses proposal noise from primary group

## What Changed

1. `telegram_alert_router.py` — Added P2 patterns for ATP REVIEW ALERT,
   STOP_CROSSED_PENDING, LARGE_MOVE_BEFORE_REVIEW, PROPOSAL_REJECTED/DENIED/
   DEFERRED/BLOCKED, dry_run decisions, and "No order submitted" messages

2. `proposal_alerter.py` — Gates send through central router before sending

3. `send_telegram_proposal_alert.py` — Gates send through central router

## Primary Group Now Receives ONLY

- TRADE_OPENED / ENTRY_FILLED
- TRADE_CLOSED / EXIT_FILLED
- STOP_HIT / STOP_FILLED
- TRAILING_STOP_HIT / TRAILING_STOP_FILLED
- CRITICAL_NEWS_AUTO_CLOSE

## Suppressed From Primary

- ATP REVIEW ALERT (all types)
- STOP CROSSED PENDING
- LARGE MOVE BEFORE REVIEW
- Approval: BLOCKED
- PROPOSAL REJECTED/DENIED/DEFERRED/EXPIRED
- dry_run_approved/rejected/deferred
- "No order submitted"
- "Paper mode" status messages

## Simulation: 14/14 passed

---

## Momentum-scalp real-time carve-out (2026-07-08)

**Problem:** Operator stopped receiving live momentum-scalp GO/WAIT alerts (`social_scalp_scanner`)
around 2026-07-01. Root cause: the scanner's social-only + route-actionability gates (added 2026-06-27)
downgrade nearly all setups to WAIT, and the long-standing `suppress_wait: true` then dropped every WAIT
to `P2_DASHBOARD_ONLY` — so the operator saw nothing (GO went 1–6/day through 06-30 → 0 from 07-01).

**Fix:** `telegram_alert_router.classify_alert` now has a scalp carve-out *before* the WAIT sink: a
"Social Scalp Setup"/"Social Mention" message with `Score ≥ scalp_realtime_min_score` (default 25, /55)
returns `P0_INTERRUPT` (real-time); below the floor → dashboard-only. Config
(`operator_alert_policy.yaml → rules`): `scalp_realtime_enabled` (default true), `scalp_realtime_min_score`
(default 25). Scalp messages don't match `_GO_PATTERN`, so the 3/hour GO rate-limit does not apply. Volume
at the default floor is ~1–4 distinct symbols/day (measured), not a flood. Revert with
`scalp_realtime_enabled: false`; raise the floor to reduce volume.

### Catalyst-verification fix + Hermes wiring + health monitor (2026-07-08)

The real reason scalp GO went to 0 (not just suppression): `apply_social_only_cap` read
`catalyst_verified`/`catalyst`/`catalyst_source` — keys `build_catalyst_enrichment` never sets — so
verified/has_news were ALWAYS false and EVERY GO/A+ was capped to WAIT even when real news existed
(FCEL had 5 news rows, still capped). Fixes:
- **Cap wiring** (`social_scalp_scanner.apply_social_only_cap`): read the keys the enrichment actually
  produces — `catalysts` (news_articles rows) → has_news; `rag_catalyst_confirmed` /
  `hermes_catalyst_confirmed` → verified. Pure-social pumps still cap; news/RAG/Hermes-backed reach GO.
- **Hermes wiring** (`load_hermes_catalysts`/`hermes_catalyst_for`): the scanner now reads Hermes
  momentum-catalyst research (`data/hermes/momentum_catalysts/*.jsonl`); a Hermes-confirmed catalyst
  (strength high/medium, ≥2 sources) sets `hermes_catalyst_confirmed` and satisfies the cap. Also stamps
  `catalyst_source` (news/rag/hermes) on `scalp_scan_results` for observability.
- **Health monitor** (`health_agent.collect_scalp_catalyst_health`, policy `scalp_catalyst_health`): fires
  **critical `scalp_catalyst_verification_dead`** when the scanner is active but 0 setups reach GO across
  `window_days` (default 3). Auto-remediated by re-running the scanner (`remediation_map`, allowlisted,
  single-flighted on `/tmp/social_scalp.lock`); circuit-breaker escalates to operator if the retry is futile
  (i.e. a code/data bug, not a stuck cron). This closes the "silently dark for a week" gap.

### Second catalyst gate fixed — route policy (2026-07-08, found via live scan)

A live end-to-end scan revealed the same wrong-key bug in a SECOND place: `social_route_policy.catalyst_is_verified`
(also imported by `social_scout_pillars`) read `catalyst`/`catalyst_source` (never set), so the route
independently downgraded every setup to `SOCIAL_ONLY_UNVERIFIED` → `actionability=SCOUT`, never GO — regardless
of the cap fix. Fixed to read `catalysts` (news) / `rag_catalyst_confirmed` / `hermes_catalyst_confirmed`.
Verified: a catalyzed micro-float candidate now routes `momentum_scalp / GO`; pure-social stays `watch_only /
SCOUT`. Lesson: unit-testing one gate wasn't enough — the live scan surfaced the parallel gate.

---

## continuous_runner NEW GO carve-out + policy tune (2026-07-09)

**Problem:** Morning momentum scalps from `continuous_runner` (`Trade AI LIVE` + `NEW GO`) were classified
`P2_DASHBOARD_ONLY` — same silent path as suppressed WAIT. The existing Social Scalp Setup carve-out did
not match the continuous_runner message format.

**Fix:** `telegram_alert_router.classify_alert` — `NEW GO` carve-out before the generic LIVE sink when
score ≥ `scalp_realtime_min_score` and Critic is not BLOCK/DOWNGRADE. Policy:
`scalp_realtime_min_score: 18` (was 25), `max_trade_ai_live_alerts_per_hour: 10` (was 3).

---

## ATM expiry + Finviz DATA QUALITY noise (2026-07-09)

**ATM duplicates:** Multiple ATM cycles each sent their own expiry Telegram batch for the same symbols.

**Fix:** `atm_auto_approver._telegram_expiry_batch()` — per-symbol 24h dedup; `send_telegram` instead of
raw `_telegram_both`.

**DATA QUALITY:** Finviz pre-market exports `Rel Volume = 0` while Volume + Avg Volume are populated.

**Fix:** `finviz_ingestion.py` backfills `relative_volume = volume / avg_volume`; 1-hour Telegram cooldown
per issue key. Router: `TRADE AI DATA QUALITY ALERT` → `P2_DASHBOARD_ONLY`.

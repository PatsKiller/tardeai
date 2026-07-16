# Watch Desk v3 — From Watching to Learning (2026-07-16 evening)

**Builds on v2.** Diagnosis: `docs/_findings/watch_desk_v3_diagnosis_2026-07-16.md`. Advisory/paper, governed promotion, zero cloud LLM in request paths — v2 constraints verbatim.

## WS-A — Source scoreboard (P0)
`watch_candidate_events` — every candidate emission scored. Backfill 120d: 13,093 events (ai_discovered 10,049 / directive_hit 2,902 / screener_find 92 / operator_add 50); anchors only where first_seen_price is real (unanchored → NOT_EVALUABLE, never guessed; directive hits 95% unanchored — flagged). **Journal hop UNLINKABLE** (trade_journal carries no source keys) — attribution scores directive→promoted and →proposal hops only. Weekly reconciler (`reconcile_watch_outcomes.py`, Sun 09:50, 400-event cap/run): +21d/+63d vs SPY → OUTPERFORM/MARKET/UNDERPERFORM. **First evidence: ai_discovered median 21d α −4.82% (n=385); operator_add −6.67% (n=13).** Surfaces: per-directive `21d α (n)` + `conv %` on review rows; needs-review sort = worst-α-then-coldest; Finds header track record; source-league line in freshness report + Sunday hygiene digest. No culling automation — evidence renders, operator culls.

## WS-B — Operator alerts (P0)
`watch_alerts` + `watch_alerts_eval.py` (*/20 RTH cron, flocked). Conditions: price_cross_above/below, rsi_above/below, directive_hit (52w/ATR/earnings conditions omitted — enrichment columns don't exist; flagged, not faked). Fires alert_events (`watch_alert` type added to the CHECK constraint — migration) + ONE batched Telegram/pass via bypass_router (operator-armed = P1), daily cap 12 (config/watch_alerts.json), overflow noted. One-shot auto-disarms; recurring re-arms after 5-trading-day cooldown. UI: 🔔 on watchlist context strips (composer prompts), armed-count chip at tab level, list/disarm via /api/v2/watch/alerts(/list — note: GET map path split from POST to avoid dispatch collision). **E2E verified:** armed CSCO price_cross_above 1 → fired "🔔 CSCO · price cross above 1 · now 109.27 · open Pullback/Watchlist card" → alert_events row → Telegram → auto-disarmed.

## WS-C — Deterministic context layer
`setup_context` per watchlist row computed in the feed by REUSING the existing server-side `_hermes_setup(rsi, trend)` (spec §8 — extraction requirement satisfied; no duplication). Glyph strip (trend ▲◆▼ · RSI zone · RVOL) + plain-English hint + explicit "deterministic context — not a quality score" label. `setup_quality_prior` untouched (its sample gate is deliberate). Regime chip renders once at Watch-tab level with the honest risk-off sentence. Rendered as a strip ABOVE Card v4 (locked family untouched).

## WS-D — Thin surfaces
D1: Finds tab widened — CIO-qualified band on top, ALL screener+discovery emissions (90d) below with per-row α/verdict/→proposal, and the WS-A track-record header ("Finds last 90d: 10,141 · 21d α median −4.82% (n=385) · 123 converted"). D2: `imports/tos_watchlists/` created with honest "awaiting first export" README — no parser wired blind (no CSV samples exist); UI copy stays downgraded until a real export lands. D3: watchlist/items 1.41MB→1.12MB — conservative cut (snips retained; `hermes_score_components`/`dual_consensus_json` KEPT because the locked Card v4 family reads them — remaining tail flagged as follow-up).

## Gotchas recorded
`percentile_cont(...) FILTER` must wrap the aggregate, not `round()`; paths present in the GET route map swallow POSTs to the same path (split /list); crontab heredocs keep dropping the `cd $PROJ &&` prefix — verify every installed line.

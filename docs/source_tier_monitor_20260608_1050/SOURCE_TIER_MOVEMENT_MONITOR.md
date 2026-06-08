# Source Maturity Tier-Movement Monitor (2026-06-08)
Extends source_attribution_monitor to track maturity TIERS over time as trade outcomes accrue.

- Each daily snapshot now records `tier_counts` (core/trusted/probationary/candidate/demoted) + a full
  per-source `source_tiers` map (148 sources) for diffing.
- Computes `tier_transitions` vs the prior snapshot: each source that changed tier → {from, to, direction
  promotion↑/demotion↓}. Notable demotions (from trusted/core) + promotions are surfaced in status notes.
- Baseline today: core:1 trusted:3 probationary:6 candidate:135 demoted:3; transitions [] (first tiered snapshot).
- v3: /api/v2/hermes/source-maturity → attribution_health adds `tier_trend` (14-day tier_counts) +
  `recent_tier_transitions` (last 10). System→Hermes Source Maturity card shows recent ↑/↓ tier moves.
- As trades settle on news-covered symbols, source win-rates shift maturity scores → sources promote/demote;
  this monitor makes that movement visible day over day. Read-only; no trades/scoring change. Daily cron 06:00.

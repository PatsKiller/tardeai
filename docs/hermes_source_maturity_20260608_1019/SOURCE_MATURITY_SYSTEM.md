# Hermes Source Discovery + Maturity Rating System (Gates 1–5) — 2026-06-08

Enhances Hermes automated source discovery + adds a maturity rating that learns which sources produce edge.
All advisory; no GO/WAIT or strategy-scoring change; 'core' activation operator-gated. Daily cron 05:45.

## Gate 1 — Source→outcome attribution  `scripts/source_outcome_attribution.py`
Attributes downstream paper-trade outcomes back to the source that surfaced the symbol (news within
ATTRIB_DAYS=5 before entry). Upserts `source_performance` (total_signals, go_signals, trades_matched,
profitable/wrong, win_rate, avg_pnl_pct, scar_factor). NOTE: trade-outcome attribution is structurally
thin today — only ~1 traded symbol overlaps the news universe — so `go_signals` (source→GO/WAIT) carries
quality for now; trade win-rate populates as overlap grows. The loop is correct + scheduled.

## Gate 2 — Maturity score + tiers  `scripts/source_maturity.py`
Blends precision (go-rate) + outcome (trade win-rate) + yield (source_learning_scores) + health
(data_source_health) + credibility (research_sources) → maturity_score 0–100 + tier
{core|trusted|probationary|candidate|demoted}. Writes data/runtime/source_maturity_latest.json.
Live: hermes=trusted (go-rate 0.45), 5 high-volume-noise sources demoted, rest candidate (cautious w/o outcomes).

## Gate 3 — Maturity → classifier confidence  `scripts/catalyst_classifier.py`
classify(..., source=) now scales catalyst confidence by source tier (core 1.15 … demoted 0.80, clamped).
Verified: hermes(trusted)→conf 0.66, yahoo_rss(demoted)→0.48 on the same headline. Wired via news_to_catalyst.

## Gate 4 — Guarded vetting ladder  `scripts/source_vetting_ladder.py`
Registers new sources as candidates (active=false), persists tier into research_sources.notes, and emits an
operator action queue (APPROVE_FOR_CORE / REVIEW_FOR_ACTIVATION / REVIEW_FOR_DEACTIVATION_NOISE) to
data/runtime/source_vetting_actions_latest.json. Does NOT auto-flip `active` on live sources — promotion to
core + deactivation of major feeds stay operator decisions (safe).

## Gate 5 — v3 board  `/api/v2/hermes/source-maturity` + System→Hermes "Source Maturity" card
Read-only: tier counts, per-source tier/score/go-rate/signals/trades, operator action count.

## Schedule & safety
Daily `45 5 * * *`: attribution → maturity → ladder (flock-guarded). Read-only except source_performance +
research_sources.notes registrations. Reversible (remove cron; JSONs regenerable). No trades/scoring touched.

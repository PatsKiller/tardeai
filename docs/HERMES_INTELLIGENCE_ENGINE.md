# Hermes Intelligence Engine — ranked, intelligence-driven watchlist (canonical)

**Status:** shipped 2026-06-09 (H-1 → H-5). Advisory-only — never gates execution. Paper mode.
Builds on the Watch Directives feature ([`WATCH_DIRECTIVES.md`](WATCH_DIRECTIVES.md)) + the watchlist
enrichment sweep.

**Goal:** a dynamic, ranked watchlist that surfaces the highest-conviction opportunities by combining
news/social, analyst, sector, competition, momentum, and trade-setup quality into one tunable score.

## Data foundation (reused, not reinvented)
- `watchlist_items` (rsi/trend/score/price from the **enrichment sweep**, `watchlist_enrichment_sweep.py`)
- `intelligence_entities` (per-ticker social_score/sentiment, rvol, confluence, catalyst, sector, industry)
- `data/runtime/pro_analyst_pills_latest.json` (analyst consensus, target upside, internal-vs-Street divergence)
- sector ETF vs SPY momentum from `market_quotes` (same as `/api/v2/sectors/monitor`)
- `hermes_research_intelligence` (Hermes's own research/theses)

## H-1 — Composite scorer (`scripts/hermes_watchlist_scorer.py`, cron `10,40 * * * *`)
One weighted 0-100 score per active/researched watchlist name, ranked highest-first. Factors (each
normalized 0-100):

| Factor | Source |
|---|---|
| technical_momentum | rsi posture + trend + rvol + confluence |
| setup_quality | sweep score + Bucket-2/3 classifier qualification |
| analyst | pro-analyst pills: consensus + target upside + divergence |
| social_sentiment | intelligence_entities social score + sentiment |
| sector_strength | sector ETF vs SPY |
| news_catalyst | verified catalyst presence |
| risk_reward | target/stop from watchlist_strategy_cards |

- **Weights** live in `config/hermes_score_weights.yaml` — tunable now, calibratable by H-4.
- **No fabrication:** missing factors are dropped and remaining weights re-normalized.
- **Coverage-confidence penalty:** `composite = raw * (0.55 + 0.45 * coverage)` so a name strong across
  many dimensions beats a thin 2-factor RVOL pop. Confidence = `0.4 + 0.6*coverage`.
- Writes `hermes_composite_score` / `hermes_rank` / `hermes_score_components` (jsonb) / `hermes_scored_at`
  on `watchlist_items`, plus an append-only snapshot to `hermes_score_history`.

## H-2 — Intel card + ranked board
- `GET /api/v2/hermes/intel/{symbol}` — structured card: composite/rank/confidence, factor breakdown,
  analyst / sector / social views, **trade-setup recommendation** (type · entry · invalidation ·
  conviction · why, via `_hermes_setup`), catalysts, risks (`_hermes_risks`), provenance.
- `/v3/watchlist` sorts by `?sort=hermes` (highest-first), shows a **★#rank · score** badge per card,
  dedups symbols, and drills into the intel card.

## H-3 — Competition / peer analysis (`_hermes_competition`)
In the intel card: peer group from the same **industry** (fallback **sector**), relative rank +
strength by Hermes score (e.g. "#1 of 3 in Semiconductors, leading peers"; peers AMD/MOBX/MX/IPWR).
Honest "no peers" when there's no intelligence coverage (limited to ~88 names with industry data).

## H-4 — Training / calibration (`scripts/hermes_score_calibration.py`, cron `30 16 * * 1-5`)
The feedback loop. Pairs each `hermes_score_history` snapshot with a ≥6h-later one for the **forward
return**, measures **per-factor predictiveness** (mean forward-return of high-factor vs low-factor
snapshots), and proposes renormalized weights → `hermes_weight_calibration` table. **ADVISORY** — the
operator applies suggestions to `config/hermes_score_weights.yaml`; it never auto-edits live weights.
Reports `insufficient_data` until history accumulates.

## H-5 — Alerting (`scripts/hermes_score_alerts.py`, cron `15,45 * * * *` `--send`)
Compares each symbol's two latest snapshots and flags: composite **spike/drop** (≥8), **rank surge**
(≥20), **analyst divergence flip**, **sector/setup factor regime shift** → `alert_events` (idempotent
`alert_uid`, no re-spam) + Telegram to both chat IDs (`6993102664`, `8797974247`).

## Schema (additive)
- `migrations/2026-06-09_hermes_composite_score.sql` — score/rank/components/scored_at on watchlist_items.
- `migrations/2026-06-09_hermes_score_history.sql` — `hermes_score_history` (append-only) +
  `hermes_weight_calibration`.

## Near-24/7 cron summary
```
*/30 9-15 + 16:15   watchlist_enrichment_sweep   (rsi/trend/score)
*/30 (all hours)    hermes_directive_discovery   (trend leads → staging → governed promotion)
10,40 (all hours)   hermes_watchlist_scorer      (composite score + rank + history snapshot)
15,45 (all hours)   hermes_score_alerts --send   (Telegram both chat IDs)
16:30 weekdays      hermes_score_calibration --apply  (weight suggestions)
```

Advisory throughout — scalp + Hermes firewalls intact, holdings untouched, no execution.

# Gate A — Professional Analyst Intelligence Layer — CLOSEOUT (2026-06-08)

## Source of professional analyst data
- **Yahoo (`yahoo_analyst_targets_history`) = authoritative consensus** — recommendation_mean (1-5),
  recommendation_key (strong_buy…), number_of_analyst_opinions, target_mean/high/low/median. **LIVE today.**
- **Finviz (`analyst_consensus_history`) = legacy/supplemental** — its `recom` is TARGET-DISTANCE %, not a
  1-5 rating; derived `analyst_rating` is MISLEADING and is NOT used as rating (target_price only, guarded).
- **Benzinga = news-only** (`/api/v2/news`), no ratings/upgrades endpoint wired.
- **Upgrade/downgrade** = catalyst-classifier headlines → EVENT pills, not consensus.

## Is Yahoo live today? YES (210 rows/35 symbols in 7d, newest today) — but narrow.
## Finviz safe? Only its target_price, with a caveat; never its rating. Benzinga: news-only.

## Coverage by tier (real consensus)
held 29.3% (12/41) · scalp 4.9% (2/41) · open_paper 0% (0/19) · watchlist 0% · proposals n/a.
14 symbols with consensus of 121. Honest reality: scalp/watchlist are microcaps with NO professional
coverage (real-world fact, shown as "no professional coverage" info pill); Yahoo currently covers held
large-caps (AVAV buy 17an +66.7%, CACI buy 14an +28%, BAH hold 13an +18%). yfinance is rate-limited for
bulk expansion — coverage grows as the daily fetch runs politely (1.5s/symbol).

## What was built
- `pro_analyst_fetch.py` — fetch Yahoo consensus for the actionable universe (held+trades+proposals+scalp+watch).
- `build_pro_analyst_read_model.py` — unified per-symbol read model (Yahoo-preferred, Finviz target supplemental,
  upgrade/downgrade events, upside, divergence, confidence, stale, provenance) → pro_analyst_pills_latest.json.
- Endpoint `GET /api/v2/pro-analyst/pills` [?symbol=] — list (coverage + divergent) + per-symbol pill.
- v3 System→Hermes "Professional Analyst Consensus" card (Street rec / analysts / target / upside / internal / divergence).
- Daily cron `10 6 * * *` (fetch → read model).

## Internal-vs-professional divergence
Computed per symbol (fused_signals direction vs Street recommendation_key) → aligned/mixed/divergent/unavailable.
Currently mostly "unavailable" (covered held names lack a fused direction); populates as fused+covered overlap grows.

## Monitoring / freshness
Read model stamps `stale` (Yahoo >7d) per symbol + coverage_by_tier; no-coverage on ETF/microcap = info, not failure.

## Confirmation — NO scoring/trading changes
Advisory only. No GO/WAIT change, no strategy scoring change, no catalyst-weight change, no trades/broker/
holdings/stops/proposal-execution touched. Raw provenance preserved. Finviz recom NOT used as consensus.

## Remaining (clearly scoped follow-on)
- Per-symbol analyst pills on the Holdings / Watchlist / Proposals / Scalp-detail / Open-trades pages (endpoint
  ready — mechanical wiring of a shared ProAnalystPill consuming /api/v2/pro-analyst/pills?symbol=).
- yfinance coverage expansion is rate-limited; the daily polite fetch grows it over time.

# Gate A Step 0 — Professional Analyst Data Audit (2026-06-08)

## Tables (both LIVE today)
- `yahoo_analyst_targets_history` — **authoritative consensus**: recommendation_mean (1-5), recommendation_key
  (strong_buy…), number_of_analyst_opinions, target_mean/high/low/median, current_price. LIVE (210 rows/7d)
  but **narrow: only ~36 symbols** (held portfolio — fetched by portfolio_orchestrator).
- `analyst_consensus_history` — broad (1685 symbols) but **recom_raw is TARGET-DISTANCE %, not a 1-5 rating**.
  Confirmed: AAPL recom_raw="1184.60%" → derived label "Strong Sell"; AAL "-60.82%" → "Strong Buy". The
  derived `analyst_rating` is MISLEADING and must NOT be used as consensus. Its `target_price` may be usable.

## Sources verdict
- **Yahoo = the real consensus** (1-5 mean, key, analyst count, targets). Live, narrow.
- **Finviz = legacy/supplemental** — do NOT use its rating; target only, with caveat.
- **Benzinga = news-only** — `_fetch_benzinga_api` hits `/api/v2/news`, NOT a ratings/upgrades endpoint.
- **Catalyst classifier** — analyst_upgrade/analyst_downgrade from headlines → use as EVENT pills, not consensus.

## The coverage gap (key finding)
Actionable universe = 80 symbols. With Yahoo consensus (7d): **2/80**. With Finviz (misleading): 35/80.
→ Real professional consensus barely covers what we trade/watch. Yahoo fetch is held-portfolio-only.

## Recommendation
Build the advisory layer Yahoo-preferred + extend Yahoo target fetching to the actionable universe (the
analog of the news-coverage fix), so pills are populated for scalp/watchlist/proposals — not just holdings.

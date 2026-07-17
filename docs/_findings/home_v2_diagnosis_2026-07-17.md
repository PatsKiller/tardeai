# Home v2 (Command Brain) — Phase 0 Diagnosis (2026-07-17)

## Flag-backs (session contract)
- `scripts/top_gainer_awareness.py` DOES NOT EXIST — the prompt's `load_finviz_top_gainers`
  lives as inline logic in api_v2/portfolio_dashboard. WS-A builds its own `market_movers`
  ingestion on the PROVEN pattern: finviz_screener_runner's screener.ashx→/export CSV
  conversion + Elite cookie + finviz_throttle.
- `news_items` table doesn't exist — the real store is **news_articles** (2,059 rows / 243
  symbols last 72h, fresh to 12:00 today; symbol/source/source_url/published_at/headline)
  plus catalyst_events. `news_symbol_guard.headline_matches_symbol` exists ✓.
- Holdings rows: equity rows carry day_change/day_change_pct/market_value/portfolio_pct ✓
  (the pasted h[0] was a fieldless cash/first row) but **sector: None on every row** — sector
  attaches via the api_v2 per-symbol meta map (:26477 {description, sector, industry,
  sector_etf}); the WS-B endpoint joins it server-side; missing → "Unclassified" (visible).
- **Repo is PUBLIC (window #5+) — confirmed via gh.** Per operator instruction: flip private
  at session close (done in closeout) + restate rotation.

## 0.1 Finviz capability
Export layer proven: `screener.ashx?...` → `elite.finviz.com/export?...` CSV w/ Elite cookie
(finviz_screener_runner:74-84); global cross-process throttle (finviz_throttle.acquire/
cooldown, state file data/state/finviz_throttle.json). Signal screens are standard screener
signals (s=ta_topgainers, ta_toplosers, ta_newhigh, ta_newlow, ta_unusualvolume,
ta_mostvolatile, ta_mostactive, n_earningsbefore/after, it_latestbuys/sales) — same export
path; each is one throttled GET. Chart proxy (Elite cookie server-side) already in prod.

## 0.4 Poll budget (current)
inbox 25KB · risk 18KB · portfolio/performance **98KB (at the 100KB line — watch)** ·
trade-ai/summary 529B. 15 useApi feeds on HomeHub. New endpoints must be <50KB + ETag.

## 0.5 Enum census (feeds WS-D dictionary; raw kept in tooltips)
| Raw | Plain English |
|---|---|
| market_relist_monitor | monitoring for re-entry |
| reentry_candidate | re-entry candidate |
| HUMAN_REVIEW | needs your review |
| ROTATION_REVIEW | rotation review |
| ADD_REVIEW | add-more review |
| read_only · synthesis→human_review | analysis only — awaiting your review |
| unknown_sync | adopted from broker sync |
| pullback_macd_reversal | pullback reversal setup |
| risk_off / risk on trend | defensive regime / risk-on trend |
| kill_switch_db_unavailable | trading halted — database was unreachable |
| RUN_UNDERFILLED | scan ran thin (few symbols) |
| run label `0400 2026-07-17` | 4:00 AM scan · Jul 17 |
| `4.0` counts | `4` |
| Heat 8.9% threshold 5% | "Heat 8.9% — above your 5% ceiling" |
Alert rewrites: holdings.json missing last_repriced → "Price data incomplete — some holdings
not repriced yet · Health →"; Schwab journal ingest log Nh old → "Trade journal sync is Nh
behind — closed trades may lag · Health →"; N decision-feeding agent jobs queued >2h →
"N agent analyses backed up over 2h · Ops →". Unknown shapes → `raw` chip + log here.

## 0.6 The +99.34% ≈ class
performance endpoint marks approx periods (≈) but renders the raw % regardless; Roth 6M/1Y
+104.92% is transfer distortion (Roth conversions in window). D3 = suppress at the API when
|pct| implausible vs account flows: render "n/a · transfers", raw in tooltip.

## Click-map skeleton (completed in WS-D)
element → destination → filter → ✓ (filled during D4 sweep)

## D4 click map (completed 2026-07-17)
| Element | Destination | Filter/anchor | ✓ |
|---|---|---|---|
| Metric-strip tiles (6) | existing drills | payload rows | ✓ (pre-existing, kept) |
| Movers board row (held/watch) | /v3/watch?symbol=X | symbol | ✓ |
| Movers board row (unknown) | finviz.com/quote (new tab, noopener) | symbol | ✓ |
| Movers signal chip | filters board in place | signal | ✓ |
| Treemap square | holding drill (onDrill) | symbol | ✓ |
| Treemap footer | /v3/portfolio | — | ✓ |
| Major News cell | headlines modal | symbol | ✓ |
| Modal actions | portfolio / watch / risk ?symbol=X | symbol | ✓ |
| Modal headline | source article (new tab, noopener) | — | ✓ |
| Today's Winners/Losers rows | /v3/portfolio?symbol=X | symbol | ✓ |
| Weekly Movers rows | /v3/portfolio?symbol=X | symbol | ✓ |
| Stops Triggered rows | /v3/risk?symbol=X | symbol | ✓ |
| Recovery Watch rows | /v3/risk?symbol=X | symbol | ✓ |
| CIO Decisions rows | decision drill (onDrill row) | item | ✓ |
| Health alert rows | drill + CTA route (healthFindingCta) | finding | ✓ (pre-existing + plain-English) |
| Action Inbox / Operator Inbox | own CTAs (OperatorInboxPanel — v1 'every row clickable' pass) | per-row | ✓ (verified present) |
| Equity-curve annotations | n/a — no annotations exist on the curve today | — | n/a (honest) |

## WS-E census (final coat — remaining debt stated)
- Raw hex in HomeHub.tsx: **59 occurrences** (pre-watchTokens file). New Row-1 components are
  100% watchTokens (BB/T/TYPE/numStyle/heatRamp). Full hex→token conversion of the legacy 600
  lines is deliberately NOT half-done this session (regression risk in a P0 build); logged as
  the one open E item. Type floor and mono-numerics hold on all new surfaces.
- Poll budget: /api/v2/portfolio/performance = 98KB — AT the 100KB line; next growth must
  move it to a summary endpoint (flagged, not yet split).

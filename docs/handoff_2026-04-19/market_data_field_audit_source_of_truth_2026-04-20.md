# Market Data Field Audit — Source of Truth

**Version:** 1.0  
**Date:** 2026-04-20  
**Author:** Claude Opus 4.6 (audit pass)  
**Status:** Audit — informs future implementation decisions

---

## 1. Executive Summary

This audit maps **every market-intelligence field** currently captured, persisted, or available in the Trade AI / Portfolio Intelligence system. It identifies 59 Finviz enrichment fields, 18 quote-cache fields, 55 technical-snapshot fields, and 7 Yahoo-derived field families — totaling **100+ unique data points** per ticker.

**Critical finding:** Most of this data is captured daily but **overwritten without history**. Only `ticker_snapshot_daily` (84 tickers, implemented today) preserves enrichment history. The quote cache, technical snapshot, and Yahoo data are all transient.

---

## 2. Current Live Source Inventory

| Source File | Tickers | Fields/Ticker | Cadence | Historical? |
|-------------|:---:|:---:|---------|:---:|
| `ticker_enrichment_cache.json` | 84 | 57 | 6-hr TTL | **YES** (via ticker_snapshot_daily) |
| `finviz_quote_cache.json` | 39 | 18 | Every 30min market hrs | NO |
| `technical_snapshot.json` | 15 | 55 | Daily pipeline | NO |
| `price_cache.json` + Postgres | 92 | OHLCV daily | Weekly rebuild | YES (Postgres) |
| `dividend_calendar.json` + Postgres | 15 | 8 | Daily | YES (dividend_history) |
| `watchlist.json` | 5 | 5 | Manual | NO |
| `watchlist_intelligence.json` | — | derived | Daily | NO |

### Postgres tables currently storing market history

| Table | Scope | Rows | Cadence |
|-------|-------|------|---------|
| `price_cache` | 92 symbols, OHLCV | 130,984 | Weekly |
| `ticker_snapshot_daily` | 84 symbols, 43-field enrichment | 84 (day 1) | Daily |
| `dividend_history` | 11 payers, yield/income | 11 (day 1) | Daily |
| `action_signals_history` | 40 tickers, signal/rule | 40/day | Daily |

---

## 3. Finviz Enrichment Field Inventory (59 fields)

Source: `ticker_enrichment_cache.json` — populated by `scripts/finviz_enrichment.py` from 6 Finviz Elite views.

### By Finviz View

#### View 111 — Base (Company/Sector/Price)
| Field | Type | Example | Category | Persisted? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `ticker` | str | "SCHD" | descriptive | ✓ snapshot | ✓ everywhere |
| `company` | str | "Schwab US Div..." | descriptive | ✓ snapshot | ✓ reports |
| `sector` | str | "Financial" | descriptive | ✓ snapshot | ✓ signals, dashboard |
| `industry` | str | "Exchange Traded Fund" | descriptive | ✓ snapshot | ✓ reports |
| `country` | str | "USA" | descriptive | ✓ snapshot | — |
| `market_cap_b` | float | None (ETF) | valuation | ✓ snapshot | ✓ Trade AI scoring |
| `pe` | float | None (ETF) | valuation | ✓ snapshot | — |
| `volume_base` | float | 31.03 | quote | ✓ snapshot | — |
| `price` | float | (in quote cache) | quote | ✓ snapshot | ✓ everywhere |
| `change_pct` | float | (in quote cache) | quote | ✓ snapshot | ✓ signals |

#### View 121 — Valuation (EPS/PE/Growth)
| Field | Type | Example | Category | Persisted? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `forward_pe` | float | None | valuation | ✓ snapshot | — |
| `peg` | float | None | valuation | ✓ snapshot | — |
| `ps` | float | None | valuation | ✓ snapshot | — |
| `pb` | float | None | valuation | ✓ snapshot | — |
| `pc` | float | None | valuation | ✓ snapshot | — |
| `pfcf` | float | None | valuation | ✓ snapshot | — |
| `eps_ttm` | float | None | valuation | ✓ snapshot | — |
| `eps_next_q` | float | None | valuation | ✓ snapshot | — |
| `eps_next_y` | float | None | valuation | ✓ snapshot | — |
| `eps_next_5y` | float | None | valuation | ✓ snapshot | — |
| `eps_past_5y` | float | None | valuation | ✓ snapshot | — |
| `sales_past_5y` | float | 31.03 | valuation | ✓ snapshot | — |
| `eps_qoq` | float | -0.06 | valuation | ✓ snapshot | — |
| `sales_qoq` | float | 17240879 | valuation | ✓ snapshot | — |

#### View 131 — Ownership/Short
| Field | Type | Example | Category | Persisted? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `float_m` | float | 0.0 (ETF) | float/shares | ✓ snapshot | ✓ Trade AI scoring |
| `shares_outstanding_m` | float | None | float/shares | ✓ snapshot | — |
| `insider_own_pct` | float | None | ownership | ✓ snapshot | ✓ Trade AI |
| `insider_trans_pct` | float | None | ownership | ✓ snapshot | ✓ signals |
| `inst_own_pct` | float | None | ownership | ✓ snapshot | — |
| `inst_trans_pct` | float | None | ownership | ✓ snapshot | — |
| `short_float_pct` | float | None | ownership | ✓ snapshot | ✓ Trade AI |
| `short_ratio` | float | 0.13 | ownership | ✓ snapshot | ✓ Trade AI |
| `avg_vol_m` | float | 24345.47 | float/shares | ✓ snapshot | ✓ scoring |

#### View 141 — Performance/RVOL
| Field | Type | Example | Category | Persisted? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `perf_week_pct` | float | 0.94 | performance | ✓ snapshot + column | ✓ reports, weekly |
| `perf_month_pct` | float | 1.44 | performance | ✓ snapshot + column | ✓ reports |
| `perf_quarter_pct` | float | 7.37 | performance | ✓ snapshot | — |
| `perf_halfyr_pct` | float | 16.79 | performance | ✓ snapshot | — |
| `perf_ytd_pct` | float | 13.12 | performance | ✓ snapshot + column | ✓ signals, reports |
| `perf_year_pct` | float | 22.07 | performance | ✓ snapshot | — |
| `volatility_w_pct` | float | 26.98 | technical | ✓ snapshot | — |
| `volatility_m_pct` | float | 25.12 | technical | ✓ snapshot | — |
| `recom` | str | "129.57%" | analyst | ✓ snapshot | — |
| `recom_score` | float | 129.57 | analyst | ✓ snapshot | — |
| `rvol` | float | 1.05 | quote | ✓ snapshot | ✓ Trade AI scoring |

#### View 161 — Fundamentals
| Field | Type | Example | Category | Persisted? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `div_yield_pct` | float | (not in sample) | valuation | ✓ snapshot | — |
| `roa_pct` | float | (when available) | valuation | ✓ snapshot | — |
| `roe_pct` | float | (when available) | valuation | ✓ snapshot | — |
| `roic_pct` | float | (when available) | valuation | ✓ snapshot | — |
| `gross_margin_pct` | float | (when available) | valuation | ✓ snapshot | — |
| `oper_margin_pct` | float | (when available) | valuation | ✓ snapshot | — |
| `profit_margin_pct` | float | (when available) | valuation | ✓ snapshot | — |

#### View 171 — Technical
| Field | Type | Example | Category | Persisted? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `beta` | float | 0.68 | technical | ✓ snapshot + column | ✓ signals, reports |
| `atr` | float | 0.32 | technical | ✓ snapshot | ✓ stops, Trade AI |
| `sma20_pct` | float | 1.15 | technical | ✓ snapshot + column | ✓ signals |
| `sma50_pct` | float | -0.01 | technical | ✓ snapshot + column | ✓ signals |
| `sma200_pct` | float | 9.22 | technical | ✓ snapshot + column | ✓ signals |
| `week52_high_pct` | float | -2.88 | technical | ✓ snapshot + column | ✓ signals |
| `week52_low_pct` | float | 25.32 | technical | ✓ snapshot + column | ✓ signals |
| `rsi` | float | 57.45 | technical | ✓ snapshot + column | ✓ signals, dashboard |
| `gap_pct` | float | 0.06 | technical | ✓ snapshot | ✓ Trade AI scoring |
| `change_from_open_pct` | float | -0.13 | technical | ✓ snapshot | ✓ Trade AI |

#### Derived/Computed
| Field | Type | Source | Category | Persisted? | Used? |
|-------|------|--------|----------|:---:|:---:|
| `rsi_status` | str | Computed from RSI | technical | ✓ snapshot | ✓ signals |
| `trend` | str | Computed from SMAs | technical | ✓ snapshot | ✓ signals |
| `cached_at` | str | Timestamp | metadata | ✓ snapshot | ✓ staleness |
| `symbol` | str | Key | metadata | ✓ | ✓ |
| `analyst_rating` | str | Computed from recom | analyst | ✓ snapshot | — |

---

## 4. Finviz Quote Cache Field Inventory (18 fields)

Source: `finviz_quote_cache.json` — populated by `scripts/portfolio_repricer.py` every 30min.

| Field | Type | Example | Category | Historical? | Used? |
|-------|------|---------|----------|:---:|:---:|
| `price` | float | 19.12 | quote | NO | ✓ repricing |
| `prev_close` | float | 19.0895 | quote | NO | ✓ day-change calc |
| `change_pct` | float | 0.16 | quote | NO | ✓ dashboard, alerts |
| `volume` | int | 4357252 | quote | NO | ✓ RVOL calc |
| `rvol` | float | 0.55 | quote | NO | ✓ signals |
| `analyst` | str | "" | analyst | NO | — |
| `target` | float | 0.0 | analyst | NO | — |
| `perf_week` | float | 5.11 | performance | NO | ✓ reports |
| `perf_month` | float | 5.11 | performance | NO | ✓ reports |
| `perf_quarter` | float | -8.52 | performance | NO | — |
| `perf_halfyr` | float | -2.1 | performance | NO | — |
| `perf_ytd` | float | -5.49 | performance | NO | ✓ YTD calc |
| `perf_year` | float | -6.27 | performance | NO | — |
| `volatility_w` | float | 1.83 | technical | NO | — |
| `volatility_m` | float | 2.19 | technical | NO | — |
| `symbol` | str | "ARCC" | metadata | �� | ✓ |
| `source` | str | "finviz_elite" | metadata | — | — |
| `last_updated` | str | timestamp | metadata | — | ✓ freshness |

**Gap:** Quote cache provides intraday price updates but NO history is preserved.

---

## 5. Yahoo-Derived Field Inventory

| Field Family | Script | What | Persisted? | Scope |
|-------------|--------|------|:---:|--------|
| **OHLCV price history** | portfolio_price_cache.py | Daily close prices, 2020-present | YES (Postgres price_cache) | 92 symbols |
| **Fidelity fund returns** | portfolio_orchestrator.py | 1M/3M/6M/1Y returns for proprietary funds | NO (computed live) | 10 Fidelity funds |
| **Beta regression** | fetch_betas_yfinance.py | 3-year weekly OLS beta vs SPY | YES (manual_beta_overrides.json) | Manual |
| **fast_info** | ticker_snapshot_builder.py | market_cap, last_price, day_high/low, year_high/low, shares | NO (transient) | On-demand |
| **Fundamentals** | (not currently captured) | Revenue, margins, guidance | NOT CAPTURED | — |
| **Analyst targets** | (not currently captured) | Mean/median PT, buy/hold/sell counts | NOT CAPTURED | — |
| **Dividend history** | (partial via dividend_calendar) | Quarterly amounts, yield | YES (dividend_history table) | 11 payers |

---

## 6. Persistence Matrix

| Field Family | Source | Current Location | Historical? | Scope | Recommended |
|-------------|--------|-----------------|:---:|--------|-------------|
| Enrichment (43 fields) | Finviz 6 views | ticker_enrichment_cache.json | **YES** (ticker_snapshot_daily) | Holdings+watchlist (84) | ✓ Already daily |
| Quote (18 fields) | Finviz live | finviz_quote_cache.json | **NO** | Holdings only (39) | Persist daily close |
| Technical (55 fields) | Finviz + computed | technical_snapshot.json | **NO** | Top 15 positions | Merge into enrichment |
| OHLCV prices | Yahoo | price_cache.json + Postgres | **YES** | 92 symbols | ✓ Already stored |
| Dividend yield/income | Pipeline | dividend_calendar.json | **YES** (dividend_history) | 11 payers | ✓ Already daily |
| Action signals | Pipeline | action_signals.json | **YES** (history table) | 40 tickers | ✓ Already daily |
| Performance returns | Pipeline | performance_history.json | **YES** (performance_daily) | Portfolio-level | ✓ Already daily |
| Analyst consensus | Finviz `recom` | In enrichment cache | **YES** (in snapshot JSONB) | 84 tickers | Extract to dedicated table later |
| Yahoo fundamentals | Not captured | — | **NO** | — | Add in Phase B |
| Yahoo analyst targets | Not captured | — | **NO** | — | Add in Phase B |

---

## 7. Usage Matrix

| Field Family | CC Dashboard | Signals | Observations | Escalations | AI Summary | Reports | Watchlist | Trade AI |
|-------------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Price/volume | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | ✓ |
| Performance (perf_*) | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | — |
| Technical (RSI/SMA/beta) | ✓ | ✓ | — | — | — | ✓ | — | — |
| Ownership/short | — | ✓ | — | — | — | — | — | ✓ |
| Valuation (PE/EPS) | — | — | — | — | — | — | — | — |
| Fundamentals (margins) | — | — | — | — | — | — | — | — |
| Analyst consensus | — | — | — | — | — | ✓ | — | — |
| Dividend yield | — | ✓ | ✓ | — | ✓ | ✓ | — | — |
| Watchlist thesis | — | — | — | — | — | — | ✓ | — |

**Key gaps in usage:**
- Valuation fields (PE, EPS, PEG) are captured but NOT USED anywhere
- Fundamentals (margins, debt ratios) captured but NOT USED
- Analyst consensus stored as raw string, not parsed for shift detection

---

## 8. Gap Analysis

### 1. Fields captured but NOT persisted historically
| Field Family | Gap Impact |
|-------------|-----------|
| Quote cache intraday prices | Can't detect "price broke support at 3 PM" |
| Technical snapshot (BB, MACD, supports/resistances) | Can't track "MACD crossover trend" |

**Recommendation:** NOT urgent. Enrichment snapshot captures daily-close equivalents.

### 2. Fields persisted but NOT used
| Field | Status |
|-------|--------|
| All valuation fields (PE, PEG, PS, PB, PFCF) | Stored in snapshot JSONB but no consumer queries them |
| All fundamental fields (margins, ROE, debt ratios) | Same |
| EPS growth fields (eps_next_q, eps_next_y, eps_past_5y) | Same |

**Recommendation:** These become valuable when recommendation drafts need quality-scoring. Keep storing, add consumers later.

### 3. Fields needed for recommendation quality but MISSING
| Missing | Why needed | Source |
|---------|-----------|--------|
| Yahoo analyst mean/median price target | Compare current price to consensus target | yfinance `.analyst_price_targets` |
| Yahoo forward revenue growth | Quality assessment for growth names | yfinance `.financials` |
| Dividend growth rate (YoY) | Yield quality vs yield trap detection | Computed from dividend_history over time |
| Earnings surprise history | Post-earnings reaction prediction | yfinance `.earnings_history` |

### 4. Fields needed for watchlist/screener workflows
| Missing | Why needed |
|---------|-----------|
| Watchlist membership in Postgres | Query "what's been on my watchlist?" historically |
| Screener-candidate enrichment | Same 43-field snapshot for screener results, not just holdings |
| Candidate comparison vs held positions | "How does this watchlist name compare to what I own?" |

### 5. Fields needed for mutual fund / ETF support
| Missing | Why needed |
|---------|-----------|
| Holdings look-through composition | Already exists in `fund_lookthrough.json` — not in Postgres |
| Expense ratio history | Fee tracking for cost-aware rebalancing |
| NAV vs price (for closed-end funds) | Premium/discount tracking |

### 6. Fields needed for analyst-curated watchlists
| Missing | Why needed |
|---------|-----------|
| Analyst firm attribution | "Goldman upgraded V" vs "Morningstar downgraded" |
| Rating change events | Event-driven: upgrade/downgrade triggers observation |
| Target price change history | "Mean target moved from $320 to $350 this month" |

---

## 9. Screener-Catalog Readiness

### Current enrichment coverage

The 43 fields from 6 Finviz views cover:
- ✓ Price/volume
- ✓ Performance periods
- ✓ Technical indicators (RSI, SMA, beta, ATR)
- ✓ Ownership/short interest
- ✓ Basic valuation (PE, market cap)
- ✓ Extended valuation (PEG, PS, PB, forward PE)
- ✓ Fundamentals (margins, ROE, debt ratios)
- ✓ Float/shares structure

**This is sufficient for 90% of screener use cases.** The enrichment pipeline already pulls all the fields a screener would need.

### What's needed for broad screener catalog

| Need | Status |
|------|--------|
| Same enrichment for ANY ticker (not just holdings) | Supported — `finviz_enrichment.py` accepts any symbol list |
| Historical snapshots for screener candidates | `ticker_snapshot_daily` supports any symbol in the enrichment cache |
| Watchlist membership tracking | Needs `watchlist_items` table |
| Candidate scoring/ranking | Needs scoring function (exists in Trade AI as `pre_score`) |

### DB structure recommendation

The current `ticker_snapshot_daily` already stores data for ALL tickers in the enrichment cache (84 today). To support screeners:
1. Expand the enrichment cache to include watchlist + screener candidates
2. `ticker_snapshot_daily` automatically captures them (it persists the full cache)
3. `watchlist_items` tracks which symbols are being watched and why
4. Same history table serves holdings, watchlist, AND screener candidates

**No separate "screener_history" table needed** — the unified `ticker_snapshot_daily` serves all.

---

## 10. Architect Recommendation

### Current source of truth per field family

| Family | Source of Truth | Historical Store |
|--------|----------------|------------------|
| Enrichment (43 fields) | `ticker_enrichment_cache.json` | `ticker_snapshot_daily` (Postgres) |
| Live price | `finviz_quote_cache.json` | `price_cache` (Postgres, weekly) |
| Dividend yield/income | `dividend_calendar.json` | `dividend_history` (Postgres) |
| Action signals | `action_signals.json` | `action_signals_history` (Postgres) |
| Performance returns | `performance_history.json` | `performance_daily` (Postgres) |
| Holdings composition | `holdings.json` | `holdings` (Postgres) |
| Watchlist membership | `watchlist.json` | NOT in Postgres (gap) |
| Analyst consensus | In enrichment JSONB (`recom` field) | Not extracted separately |
| Yahoo fundamentals | NOT CAPTURED | NOT STORED |

### Most important missing capture gaps (ranked)

1. **Watchlist in Postgres** — user-curated watchlist has no historical tracking
2. **Analyst consensus extraction** — `recom` field is a raw percentage string, not parsed into buy/hold/sell counts or mean target
3. **Yahoo analyst price targets** — not captured at all; critical for "is this position above/below consensus?"
4. **Quote cache daily close persistence** — 30-min prices lost daily; enrichment snapshot partially covers this

### Best next implementation slice

**`watchlist_items` table + user-added watchlist modal in CC** — this is the biggest gap for user workflow (architect already approved it as next after ticker_snapshot_daily).

### What to capture now even if not used yet

The enrichment pipeline already captures valuation + fundamental fields. These are stored in `ticker_snapshot_daily` JSONB. **No additional capture needed** — the data is there, just unused by current consumers. When recommendation drafts need quality scoring, the historical data will be available.

---

## 11. Appendix

### Inspected file paths
```
data/portfolios/state/ticker_enrichment_cache.json (84 tickers, 57 fields/ticker)
data/portfolios/state/finviz_quote_cache.json (39 tickers, 18 fields)
data/portfolios/state/technical_snapshot.json (15 positions, 55 fields)
data/portfolios/state/watchlist.json (5 entries)
data/portfolios/state/watchlist_intelligence.json (derived)
data/portfolios/state/price_cache.json (92 symbols, 130K entries)
data/portfolios/state/dividend_calendar.json (15 payers)
scripts/finviz_enrichment.py (6 Finviz views: 111, 121, 131, 141, 161, 171)
scripts/portfolio_repricer.py (quote cache writer)
scripts/ticker_snapshot_builder.py (yfinance + finvizfinance optional)
scripts/portfolio_price_cache.py (Yahoo OHLCV)
scripts/portfolio_orchestrator.py (enrichment supplement)
```

### Finviz view summary
| View | Purpose | Fields |
|------|---------|--------|
| 111 | Base (company, sector, price) | 10 |
| 121 | Valuation (PE, EPS, growth) | 14 |
| 131 | Ownership (float, short, institutional) | 11 |
| 141 | Performance (weekly→yearly, RVOL) | 12 |
| 161 | Fundamentals (margins, ratios, ROE) | 14 |
| 171 | Technical (RSI, SMA, ATR, beta, 52w) | 12 |

### Example enrichment row (full 57 fields)
Stored daily in `ticker_snapshot_daily.data` as JSONB with `_provenance` block.

---

*Market data field audit completed 2026-04-20.*

# Finviz Enrichment System — Documentation
## Version: 1.0 | April 16, 2026

---

## OVERVIEW

`finviz_enrichment.py` is the single source of truth for all Finviz Elite data
across Trade AI and Portfolio Intelligence. It replaces fragmented Finviz calls
in `finviz_ingestion.py`, `portfolio_technical.py`, and the broken cookie scrape.

**Problem it solves:**
- RVOL was 0.0 in all scored tickers (not captured from Finviz)
- Float was 0.0 in all scored tickers (not captured from Finviz)
- RSI/SMA were None in technical_snapshot.json (cookie scrape failing)
- Three separate modules making overlapping Finviz API calls

**Solution:**
- One module, 5 views, shared cache, no cookie needed for technical data
- ~45 indicators per ticker stored in `data/state/ticker_enrichment_cache.json`
- Both Trade AI and Portfolio Intelligence read from the same cache

---

## FINVIZ ELITE VIEWS USED

| View | Purpose | Key Fields |
|---|---|---|
| v=111 | Base | Price, Change%, Volume, Sector, Company, PE, Market Cap |
| v=131 | Ownership | **Float (M)**, Short Float%, Short Ratio, Inst Ownership%, Avg Volume |
| v=141 | Performance | **RVOL**, Perf Week/Month/Quarter/HalfYr/YTD/Year, Volatility W/M, Earnings Date |
| v=161 | Fundamentals | Dividend Yield, ROE, ROA, Gross/Oper/Profit Margin, Debt/Equity |
| v=171 | Technical | **RSI(14)**, **SMA20/50/200%**, ATR, Beta, 52wk H/L%, Gap%, Change from Open |

**v=171 eliminates cookie dependency** — RSI and SMA available via API token, no scraping.

---

## FULL FIELD REFERENCE (~45 fields per ticker)

### Base (v=111)
| Field | Type | Description |
|---|---|---|
| symbol | str | Ticker symbol |
| company | str | Company name |
| sector | str | Sector |
| industry | str | Industry |
| price | float | Current price |
| change_pct | float | % change today |
| volume | float | Today's volume |
| market_cap_b | float | Market cap in billions |
| pe | float | Price/Earnings ratio |

### Ownership (v=131)
| Field | Type | Description |
|---|---|---|
| float_m | float | **Float in millions** |
| shares_outstanding_m | float | Shares outstanding (M) |
| short_float_pct | float | Short % of float |
| short_ratio | float | Days to cover |
| inst_own_pct | float | Institutional ownership % |
| inst_trans_pct | float | Institutional transaction % |
| insider_own_pct | float | Insider ownership % |
| avg_vol_m | float | Average volume (M) |

### Performance (v=141)
| Field | Type | Description |
|---|---|---|
| rvol | float | **Relative volume** |
| perf_week_pct | float | 1-week performance % |
| perf_month_pct | float | 1-month performance % |
| perf_quarter_pct | float | 1-quarter performance % |
| perf_halfyr_pct | float | 6-month performance % |
| perf_ytd_pct | float | YTD performance % |
| perf_year_pct | float | 1-year performance % |
| volatility_w_pct | float | Weekly volatility % |
| volatility_m_pct | float | Monthly volatility % |
| earnings_date | str | Next earnings date |

### Fundamentals (v=161)
| Field | Type | Description |
|---|---|---|
| div_yield_pct | float | Dividend yield % |
| roa_pct | float | Return on assets % |
| roe_pct | float | Return on equity % |
| roic_pct | float | Return on invested capital % |
| gross_margin_pct | float | Gross margin % |
| oper_margin_pct | float | Operating margin % |
| profit_margin_pct | float | Net profit margin % |
| current_ratio | float | Current ratio |
| lt_debt_equity | float | LT debt/equity |
| total_debt_equity | float | Total debt/equity |

### Technical (v=171) — No cookie needed
| Field | Type | Description |
|---|---|---|
| rsi | float | **RSI(14)** |
| rsi_status | str | overbought / oversold / neutral |
| sma20_pct | float | **% above/below SMA20** |
| sma50_pct | float | **% above/below SMA50** |
| sma200_pct | float | **% above/below SMA200** |
| sma20_price | float | SMA20 price level (derived) |
| sma50_price | float | SMA50 price level (derived) |
| sma200_price | float | SMA200 price level (derived) |
| week52_high_pct | float | % below 52-week high |
| week52_low_pct | float | % above 52-week low |
| atr | float | Average True Range |
| beta | float | Beta vs market |
| gap_pct | float | Today's gap % |
| change_from_open_pct | float | % change from open |
| trend | str | uptrend/downtrend/above_200/below_200 |

---

## CACHE STRUCTURE

File: `data/state/ticker_enrichment_cache.json`

```json
{
  "MAMO": {
    "symbol": "MAMO",
    "cached_at": "2026-04-16T14:30:00",
    "price": 1.35,
    "change_pct": 37.0,
    "float_m": 4.05,
    "short_float_pct": 2.03,
    "rvol": 14.2,
    "rsi": 83.33,
    "sma20_pct": 99.28,
    "sma50_pct": 133.07,
    "sma200_pct": 61.20,
    "rsi_status": "overbought",
    "trend": "uptrend",
    ...
  }
}
```

**TTL:** 6 hours — refreshes automatically on next pipeline run.
**PostgreSQL:** When DB ready, `save_cache()` gets second write path.

---

## INTEGRATION POINTS

### Trade AI (scripts/trade_ai_orchestrator.py)
Add after Stage 2 (finviz_ingestion), before Stage 5 (catalyst_enrichment):
```python
# Stage 2.5 — Finviz enrichment (float, RVOL, RSI, SMA)
try:
    from finviz_enrichment import enrich_tickers
    syms = [t["symbol"] for t in tickers]
    fv_enriched = enrich_tickers(syms, project_root=str(root))
    for t in tickers:
        sym = t["symbol"]
        if sym in fv_enriched:
            e = fv_enriched[sym]
            t["float_m"] = e.get("float_m") or t.get("float_m", 0)
            t["relative_volume"] = e.get("rvol") or t.get("relative_volume", 0)
    _ok("finviz_enrichment", f"{len(fv_enriched)} tickers enriched")
except Exception as exc:
    _err("finviz_enrichment", str(exc))
```

### Portfolio Intelligence (scripts/portfolio_technical.py)
Replace `_finviz_cookie_batch()` call with:
```python
from finviz_enrichment import enrich_portfolio_holdings
enriched = enrich_portfolio_holdings(holdings, project_root=str(root))
# enriched[sym]["rsi"], enriched[sym]["sma200_pct"] etc.
```

### Scoring (scripts/scoring.py)
No change needed — float_m and relative_volume already read from ticker dict.
Once orchestrator wires enrichment into tickers, scoring gets correct values.

---

## RATE LIMIT CALCULATION

| Scenario | Tickers | Batches | Views | Total Requests |
|---|---|---|---|---|
| Trade AI daily run | ~20 tickers | 1 batch | 4 views | 4 requests |
| Portfolio enrichment | ~45 tickers | 3 batches | 4 views | 12 requests |
| Full system (both) | ~65 tickers (deduped) | 4 batches | 4 views | 16 requests |
| With fundamentals | ~65 tickers | 4 batches | 5 views | 20 requests |

**Budget: 100 req/hour. Daily usage: ~20-40 requests. Well within limits.**

---

## SCHEDULED REFRESH

Cache TTL is 6 hours. Automatic refresh happens when:
1. Trade AI pipeline runs (Mon-Fri 4AM, 7AM, 9AM) — refreshes screener tickers
2. Portfolio daily pipeline runs (Mon-Fri 7AM) — refreshes portfolio holdings
3. Sunday price cache job — force refresh all holdings

**Net effect:** Portfolio holdings refreshed every weekday morning.
Trade AI tickers refreshed every pipeline run (already fresh from screener).

---

## POSTGRESQL SCHEMA (future)

```sql
CREATE TABLE ticker_enrichment (
    symbol VARCHAR(10) PRIMARY KEY,
    cached_at TIMESTAMP,
    price DECIMAL(10,2),
    change_pct DECIMAL(8,4),
    float_m DECIMAL(10,2),
    short_float_pct DECIMAL(8,4),
    inst_own_pct DECIMAL(8,4),
    rvol DECIMAL(8,2),
    perf_week_pct DECIMAL(8,4),
    perf_month_pct DECIMAL(8,4),
    perf_ytd_pct DECIMAL(8,4),
    perf_year_pct DECIMAL(8,4),
    volatility_w_pct DECIMAL(8,4),
    rsi DECIMAL(6,2),
    sma20_pct DECIMAL(8,4),
    sma50_pct DECIMAL(8,4),
    sma200_pct DECIMAL(8,4),
    sma20_price DECIMAL(10,2),
    sma50_price DECIMAL(10,2),
    sma200_price DECIMAL(10,2),
    atr DECIMAL(8,4),
    beta DECIMAL(6,4),
    gap_pct DECIMAL(8,4),
    week52_high_pct DECIMAL(8,4),
    week52_low_pct DECIMAL(8,4),
    div_yield_pct DECIMAL(8,4),
    roe_pct DECIMAL(8,4),
    gross_margin_pct DECIMAL(8,4),
    rsi_status VARCHAR(12),
    trend VARCHAR(12),
    earnings_date VARCHAR(20)
);
```

---

## FILES

| File | Purpose |
|---|---|
| `scripts/finviz_enrichment.py` | Main module |
| `data/state/ticker_enrichment_cache.json` | Cache store |
| `docs/FINVIZ_ENRICHMENT.md` | This document |

---

## TESTING

```bash
# Test with trade AI tickers
python3 scripts/finviz_enrichment.py MAMO ACHV MYSE

# Test with portfolio holdings
python3 -c "
import json, sys
sys.path.insert(0,'scripts')
from finviz_enrichment import enrich_portfolio_holdings
holdings = json.load(open('data/portfolios/state/holdings.json'))['holdings']
result = enrich_portfolio_holdings(holdings, project_root='.')
for sym, data in list(result.items())[:3]:
    print(f'{sym}: float={data.get(\"float_m\")}M rvol={data.get(\"rvol\")} rsi={data.get(\"rsi\")} trend={data.get(\"trend\")}')
"
```

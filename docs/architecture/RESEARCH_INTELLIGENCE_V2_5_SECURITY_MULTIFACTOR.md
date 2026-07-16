# Research Intelligence v2.5 — Security Data + Multi-Factor Sizing

**Status:** Implemented · **Date:** 2026-07-15  
**Builds on:** v2.4 concentration/heat sizing  
**Addresses:** Immature “theme + portfolio math only” recommendations

## Problem (v2.4)

Recommendations looked polished but were mostly **theme matching + book math**. Missing security-level edge (RSI, relative strength, earnings, valuation, liquidity) made adds feel like educated guesses.

## Solution overview

| Layer | Module | Role |
|-------|--------|------|
| Security snapshots | `research_intelligence_security.py` | RSI, RS vs SCHG, EPS, PE/PEG, liquidity, vol, conviction A/B/C |
| Multi-factor size | `research_intelligence_portfolio.py` | Theme room × heat × concentration × vol × conviction |
| Narrative / tiers | `research_intelligence_narrative.py` | Why-selected takeaways; quality score includes security |
| UI | `ResearchIntelligenceHub.tsx` | Conv tier, RSI/RS/PE chips on ticker cards |

## Data sources (existing SSOT — no new vendors required)

| Source | Path | Used for |
|--------|------|----------|
| Enrichment | `data/portfolios/state/ticker_enrichment_cache.json` | RSI, PE, PEG, EPS, perf, SMA, beta, volume |
| Technical snapshot | `…/technical_snapshot.json` | RSI, SMA, tech_score/grade, perf |
| Finviz quotes | `…/finviz_quote_cache.json` | Volatility, rvol, price/perf fallback |
| Risk | `…/risk_management.json` | Portfolio heat (from v2.4) |

**Note:** Finviz-style `analyst_rating` is used only when `recom_score` is in a plausible 0–10 band (corrupted “Strong Sell + absurd %” stamps are ignored).

## Conviction score (0–100 → A/B/C)

Factors (signed):

- RSI zone (constructive / overbought / oversold)
- **Relative strength** vs SCHG (1M)
- Earnings momentum (EPS QoQ / next year)
- Valuation (PEG / PE heuristics; ETFs skip hard PE)
- Trend + SMA50/200 + tech_grade
- Valid analyst rating (when available)
- Liquidity (thin → penalty)
- Beta / data coverage

| Tier | Score | Size mult |
|------|-------|-----------|
| A | ≥72 | ×1.15 |
| B | ≥52 | ×1.00 |
| C | &lt;52 | ×0.65 |

Adds ranked by conviction; overbought (RSI≥78) + C or thin liquidity demoted to **watchlist**.

## Multi-factor sizing

```
base = min(conviction_base, 40% of theme room)
× heat_mult
× book_conc_mult
× (extra 0.75 if top-3 ≥ 50%)
× theme_vol_profile
× security vol_size_mult (beta, liquidity)
× conviction_size_mult
capped at single-name soft/hard max
```

### Proactive concentration

| Rule | Effect |
|------|--------|
| Top-3 ≥ 50% | Extra ×0.75 size; prefer funded |
| SCHG ≥ 24% | **Require funding trim** (SCHG first) |
| Theme soft max full | `allow_add=False` — rotate only |
| Book high / heat high | Funded adds only |

**Diversification note** appended when funded SCHG trim improves top-3 concentration.

## Standard card template (v2.5)

Every advisory payload includes `card_template.sections`:

1. executive_summary  
2. key_takeaways (includes Tickers + Why {SYM})  
3. bull_bear  
4. investment_implications  
5. tickers_allocation (role + conv + RSI/RS/PE)  
6. sizing_guidance  
7. sizing_reason  
8. concentration_heat  
9. risk_caveat  

## UI

Ticker chips show:

- Role (`add_candidate` / `trim_candidate` / …)
- **Conv A/B/C** + score
- RSI · RS vs SCHG · P/E · PEG
- Why-selected headline

## Feed version

`version: "2.5"`

## Roadmap (next phases — not in this ship)

| Phase | Item | Status |
|-------|------|--------|
| 2.5 | RSI + RS + valuation + multi-factor size | **Done** |
| 2.6 | Clean analyst consensus / revision time series | Open (cache quality) |
| 2.6 | Earnings surprise history (beats/misses) | Open |
| 2.7 | Sector-relative RS (vs industry peers, not only SCHG) | Open |
| 2.7 | EV/EBITDA peer z-score | Open |

## Operator notes

1. Hard-refresh `/v3/` after dist build.  
2. Enrichment cache freshness drives conviction quality — keep Finviz/enrichment jobs healthy.  
3. Recommendations remain advisory; stops via Replace mode.

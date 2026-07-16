# Research Intelligence v2.6 — Maturity Upgrade

**Status:** Implemented · **Date:** 2026-07-16  
**Builds on:** v2.5 security multi-factor sizing

## Goals

Close the “immature desk” gap: transparent conviction, data completeness gates,
analyst + options layers, dollar sizing, and click-through actions.

## Features

### Transparent conviction

Base 40 + components (shown on cards / hover):

| Component | Typical range |
|-----------|----------------|
| RSI / Momentum | −12 … +14 |
| Relative Strength (SPY/QQQ) | −14 … +17 |
| Valuation (PEG/PE) | −10 … +12 |
| Analyst consensus (Finnhub) | −12 … +14 |
| Earnings / growth | −10 … +12 |
| Trend / SMAs | −14 … +17 |
| Options flow (desk proposals) | −8 … +8 |
| Liquidity / vol (beta) | −18 … +6 |
| Data quality | −12 … +6 |

Tier: **A** ≥72 + data complete; **B** ≥52; **C** &lt;52 (incomplete capped ≤58).

### Data completeness gate

Adds require **RSI + relative strength**. Incomplete → demote to **watchlist**,
`quality_gate` note, lower conviction size mult.

### Analyst layer

`stock_intelligence.json` Finnhub counts (buy/hold/sell) → consensus label.
Corrupted enrichment “Strong Sell + absurd recom_score” ignored when Finnhub present.

### Options layer

`options_proposals.json` → IV rank + call/put bias. Explicit “No unusual options
activity detected” when empty (never silent omit).

### Sizing

- % of book + **$ band** from household total  
- **1% risk budget** note  
- Cash cap for unfunded adds  
- Funded path when SCHG≥24% / top-3&gt;50% / high heat  

### Action bar

Per ticker / card: Build Trade Ticket, Watchlist, Open Trading, Set/Refresh Stop,
Propose Trim (when role=trim).

### Card template sections (v2.6)

executive_summary → key_takeaways → technical_snapshot → analyst_snapshot →
options_flow → bull_bear → investment_implications → tickers_allocation →
sizing → action_bar → concentration/heat → risk_caveat

## Feed

`version: "2.6"`

## Still open (v2.7+)

- Live Polygon unusual options sweeps (needs API key + cache)  
- Analyst revision time series  
- Earnings calendar dates on every name  
- Auto-seed compounding pillar topics if empty after filter  

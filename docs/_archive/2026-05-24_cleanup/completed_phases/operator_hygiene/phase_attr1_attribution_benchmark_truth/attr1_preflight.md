# ATTR-1 Preflight

## Safety
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings: $1,192,726

## Pre-Fix State
- `performance_attribution.json` exists with portfolio metrics but all benchmark fields null
- SPY/ITA/AGG missing from `price_cache.json`
- API `/api/v2/attribution` returns `bench_cagr: null`, `alpha_annualized: null`
- UI shows "N/A" and "—" for benchmark metrics without explanation
- yfinance >= 0.2.x returns MultiIndex columns, breaking the price extraction

## Scripts Found
- `scripts/portfolio_performance_attribution.py` — main attribution pipeline
- `scripts/report_attr1_benchmark_alpha.py` — diagnostic report
- `scripts/api_v2.py` — attribution() API handler at line 5356
- `apps/command-center-v2/src/pages/Attribution.tsx` — UI page

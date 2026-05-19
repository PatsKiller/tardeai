# SCREENER-ARCH-4 Preflight

**Date:** 2026-05-19

## Safety
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings guard: $1,193,829

## Universe
- Catalog: 1,139 tickers, 1,129 active
- Memberships: 2,038 (1,311 present, 727 dropped)
- Recent scans (3d): 1,559 symbols, 2,811 rows
- strategy_setup_matches: 2,142 rows

## Strategy Library
- 23 strategy YAMLs (excluding schemas/shared)
- 5 with scoring_weights (TESTING status)
- Timeframes: INTRADAY(2), SHORT_SWING(7), MEDIUM_SWING(2), POSITION(9), other(3)
- Router: multi_setup_router.py with family gates, liquidity gates, YAML scoring

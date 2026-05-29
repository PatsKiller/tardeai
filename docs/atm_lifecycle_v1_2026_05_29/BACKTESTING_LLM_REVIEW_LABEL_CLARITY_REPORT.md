# Backtesting & LLM Review Label Clarity Report — 2026-05-29

## Labels Changed

| Before | After | Location |
|--------|-------|----------|
| "Sim Trades" KPI | "Backtest Rows" | Backtesting.tsx KPI row |
| "Classified" KPI | "Strategy Coverage" | Backtesting.tsx KPI row |
| "Showing X of Y sim trades" | Source-aware: "Showing X replay-trade rows (of Y total backtest rows)" | Backtesting.tsx filter bar |
| "LLM Reviews (N)" tab | "LLM Review Coverage (N)" | Backtesting.tsx tab |
| "Total Reviews" card | "Total Review Rows" | Backtesting.tsx LLM tab |
| "Paper Trades" coverage | "Real Paper Trades With LLM Review" | Backtesting.tsx LLM tab |
| "Backtest Trades" coverage | "Backtest Rows With LLM Review" | Backtesting.tsx LLM tab |
| "N backtest trades have no broker/account mapping (champion simulations)" | "N champion/hypothetical rows have no broker mapping — expected for simulations, not missing real trades" | api_v2.py filter-options |

## Banners Added
1. **Context banner** below header: "Backtesting rows are historical replays and champion simulations — not live broker orders." Dynamically adapts to active run_type filter.
2. **LLM Review Coverage explainer**: "LLM review rows cover paper trades and backtest rows... Errors are review-generation/parser issues, not failed trades."

## Sample-Size Warnings Added
| Location | Badge | Condition |
|----------|-------|-----------|
| Strategy tab — Trades column | "very small" (red) | trades < 5 |
| Strategy tab — Trades column | "small sample" (yellow) | 5 <= trades < 20 |
| Trail Analysis — Trades column | "too few" (red) | trades < 5 |
| Trail Analysis — Trades column | "small" (yellow) | 5 <= trades < 20 |

## Files Changed
- `apps/command-center-v2/src/pages/Backtesting.tsx` — UI labels, banners, sample-size badges
- `scripts/api_v2.py` — champion mapping gap wording

## Build Validation
- Python compile: PASS
- TypeScript: PASS
- Vite build: PASS (261ms)

## Safety
| Check | Result |
|-------|--------|
| Orders placed | NO |
| Broker writes | NO |
| DB writes | NO |
| Proposal mutations | NO |
| paper_trades mutations | NO |
| Journal mutations | NO |
| Classifier apply | NO |
| LLM calls | NO |
| Cron changes | NO |

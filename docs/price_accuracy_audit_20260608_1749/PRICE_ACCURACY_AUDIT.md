# Command Center Price Accuracy Audit — vs Schwab (2026-06-08)

## Complaint
Command Center holdings prices differed from Schwab Alliance (06/08 5:15 PM ET close) by ~0.1–4%.

## Trace
- Command Center /api/v2/portfolio/holdings serves **data/portfolios/state/holdings.json** (`price` field).
- holdings.json is repriced by **portfolio_repricer.py** from **Finviz Elite** → finviz_quote_cache.json
  (symbol set = Schwab portfolio + watchlist, so held names ARE covered). Pipeline is correct.
- **Root cause (systematic):** holdings.json `last_repriced` was **15:45 ET — ~15 min before the 4:00 close**.
  Intraday reprice cadence (agent-triggered, ~hourly to 15:45) had **no post-close run**, so the display froze
  ~15 min before close and missed the closing move → off by the day's final move (±0.1–2%; worst KBR +2.1%,
  which sold off late). After hours it stayed frozen at 15:45 until next morning.
- **Secondary (per-symbol data variance):** even after a fresh post-close reprice (17:47 ET), a couple names
  remain off (KBR +2.0% 35.21 vs 34.53; CACI −1.1%) — Finviz Elite's close quote for these differs from
  Schwab's official close. Vendor variance, not a pipeline bug. Most names matched within ±0.5% (RKLB/RTX/
  IRDM/LHX exact).
- **Tertiary:** ticker_prices (used by OTHER surfaces, not the portfolio view) for held names is the 07:20 AM
  pre-market finviz batch (off 1–4%) — only the portfolio view uses holdings.json, so less impactful, but
  surfaces reading ticker_prices for held symbols inherit pre-market staleness.

## Fixes
1. **Immediate:** reran portfolio_repricer.py (17:47 ET) → Command Center now reflects post-close prices
   (most within ±0.5% of Schwab).
2. **Permanent:** added cron `10 16 * * 1-5` (4:10 PM ET) post-close reprice → holdings.json captures the
   official close automatically each trading day.

## Recommended follow-ons (not yet done)
- Outlier reconciliation: when Finviz close diverges >1.5% from a second source for a held name, flag/fallback
  (KBR/CACI today).
- Optionally point held-symbol ticker_prices at the same post-close reprice so all surfaces agree.

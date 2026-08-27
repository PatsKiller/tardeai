# Journal UI Audit — 2026-06-11 (for review)

**Type:** Playwright visual audit of Command Center v3 → **Journal**, all 6 tabs + key interactions.
**How:** `scripts/crawl_journal_ui.py` (headless Chromium, viewport 1600×1000) walked every tab, JS-clicked
interactive elements, captured modal/drawer states; screenshots compressed to JPEG (q44, ≤1400px wide).
**Read-only** — the crawler only navigates + clicks the UI; no API writes.

> ⚠️ **Sensitivity:** these screenshots show **real account values** ($1.24M portfolio, per-trade P&L).
> They live in the **private** backup repo + the operator's own Drive only. Do not share externally.

## Coverage (12 images)
| Image | What it shows |
|---|---|
| `trades_00_overview` | Trades tab — 160 trades / 4 accounts, KPIs, equity curve, calendar, by-strategy, monthly |
| `analytics_00_overview` | Analytics tab |
| `lessons_00_overview` | Lessons tab |
| `protection_00_overview` | Protection tab |
| `backtesting_00_overview` | Backtesting tab — hypotheses, R-distribution, 14 sub-tabs, filters |
| `real_accounts_00_overview` | Real Accounts (Schwab) — 116 round-trips, badges, Grok lessons |
| `trades_01/02/03_*` | MetricStrip drilldowns (Win Rate / Regime / Setups → DetailDrawer) |
| `trades_drawer_trade_detail` | DetailDrawer drilldown from a trade row |
| `trades_replay_chart` | TradeReplayChart modal (Trades tab) |
| `real_accounts_replay_chart` | RGNT replay — candles + VOL/VWAP/MACD/RSI + BUY/SELL/MFE/MAE markers + scrubber |

## Findings — everything renders correctly with live data
1. **Trades tab healthy:** 160 trades across 4 accounts (Schwab Taxable 87 / Alpaca Paper 39 / Roth IRA 33 /
   Rollover 1). KPIs all populate, incl. the **new Avg R = 0.52R** card and the **By-Strategy R column**
   (0.3R / 0.1R / 2.4R / 1.5R) — confirms the R:R work shipped today is live. Equity curve, Daily P&L,
   Calendar P&L (Dec 2025–Jun 2026) all render.
2. **Real Accounts confirms the execution work:** 116 round-trips, win 52.6%, net $37,046; execution badges
   (weak/poor + capture%), **Grok lessons on every row** (incl. swings), and the long-term-trims
   ($114,938) + basis_unknown (13, excluded) honesty banners.
3. **Backtesting rich + correct:** the three execution hypotheses all show **"hurts"** (negative avg Δ/sh) —
   consistent with the coaching queue's "do not graft." R-multiple distribution histogram + win-rate-by-
   strategy chart render; strategy/broker/account/run-type filters present; 14 sub-tabs.
4. **Replay charts are the standout:** RGNT replay shows 424 1-min bars, candles, volume, VWAP/MACD/RSI panes,
   BUY/SELL/MFE/MAE/max-after-exit/16:00-close markers, the win/weak·cap75% badge, and the 0.5–8× scrubber.
5. **Data-quality surfacing works:** the Trades tab shows an **Integrity Warning** — "NUVL has 2 open records
   — possible duplicate." Worth resolving (see below), but good that the UI flags it.
6. **DetailDrawer drilldowns work** from KPI cards and trade rows.

## Items for the operator to verify
- **NUVL duplicate open record** (Integrity Warning) — confirm whether NUVL legitimately has two open lots or
  a phantom; resolve if duplicate.
- **Headless capture timing (not a prod bug):** the journal's API fetches need ~6–8 s to resolve; an initial
  3 s wait captured empty states. The crawler now waits 4.5 s + 4 s per tab. Real users won't see this.

## Reproduce
```bash
PLAYWRIGHT_BROWSERS_PATH=~/.cache/ms-playwright \
  .venv/bin/python scripts/crawl_journal_ui.py /tmp/journal_crawl_out
```

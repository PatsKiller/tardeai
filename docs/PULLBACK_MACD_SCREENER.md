# Pullback / MACD Screener

Daily S&P 500 scan for **uptrend names that have pulled back ~20% off their 52-week high and whose
MACD is approaching a bullish cross** — a counter-trend dip-buy discovery tool. Advisory only:
auto-generated proposals require operator approval; nothing auto-executes.

## Signal definition (config-driven)

All thresholds live in `config/pullback_macd_screener.yaml` (no hardcoded values).

1. **Uptrend gate** — `close > SMA200` AND `SMA50 > SMA200` AND `SMA50` rising (5-bar)
2. **Pullback gate** — drawdown from the 52-week high in the **12–28%** band (centered on 20%)
3. **MACD approaching cross** — MACD(12,26,9): `line < signal`, histogram `< 0` and rising ≥2 bars,
   and `|MACD − signal| / price ≤ 0.6%` (proximity)
4. Optional RSI confirmation (off by default)

Two tiers:
- **trigger** — all gates pass; the cross is imminent
- **watch** — uptrend + pullback, but the cross hasn't triggered yet (carries a `why_not`)

Entry = last close; stop = `entry − 1.5×ATR(14)`; target1 = `entry + 2.0×risk` (R:R ~2.0). All tunable.

## Why it fires rarely

A deep pullback that *keeps* a name above a rising 200-day is genuinely uncommon — when the market is
near highs, uptrend names tend to sit near their highs. A representative scan: 500 screened → ~208 in
uptrend → ~22 in the pullback band → ~1 trigger + ~21 watch. Zero-trigger days are normal.

## Components

| Piece | Path |
|---|---|
| Scan engine (pandas-native MACD/SMA, yfinance data) | `scripts/pullback_macd_screener.py` |
| Tables | `migrations/2026_06_26_pullback_macd_screener.sql` — `sp500_constituents`, `pullback_macd_candidates`, `pullback_macd_runs` |
| Config | `config/pullback_macd_screener.yaml` |
| API | `GET /api/v2/pullback-macd/candidates` (`?tier=trigger\|watch`, `?limit=`) in `scripts/api_v2.py` |
| UI | `apps/command-center-v3/src/pages/PullbackMacdHub.tsx` (nav: **Pullback/MACD**), with the amber **pullback banner** on each card |
| Launcher / cron | `linux_launchers/run_pullback_macd_screener.sh`, cron `40 16 * * 1-5` (post-close) |
| Health | `collect_pullback_macd_screener()` in `health_agent.py` (scan freshness + universe size) |

## Outputs (all advisory)

A single scan fans out to four channels:
1. **`pullback_macd_candidates`** table → API → Command Center **Pullback/MACD** screen (with banner)
2. **Candidate/incubator pipeline** — `ticker_strategy_classifications` + `watchlist_items` (source `pullback_macd`)
3. **Telegram** — alert on **new** triggers only (tier flipped to trigger since last scan)
4. **Approval queue** — advisory proposals into `paper_trade_proposals` for the configured tiers
   (`proposal_tiers: [trigger]` by default), `status=PENDING`, `auto_execution_label=manual` — operator approves

> **Why trigger-only:** every PENDING broker-route proposal is picked up by `broker_promote_oversight`
> for per-proposal local + cloud LLM review. Emitting watch-tier proposals too (21 in the first run)
> spawned 22 concurrent oversight reviews and spiked machine load, starving the single-threaded API
> server. Watch-tier names still appear on the tab and feed the pipeline — they just don't create
> queue proposals. Set `proposal_tiers: [trigger, watch]` to re-enable (not recommended).

## Usage

```bash
# Dry run — compute + print, no DB writes / proposals / alerts
.venv/bin/python scripts/pullback_macd_screener.py --dry-run

# Real scan (writes candidates, emits proposals, feeds pipeline, alerts on new triggers)
.venv/bin/python scripts/pullback_macd_screener.py [--json]

# Limit universe for testing
.venv/bin/python scripts/pullback_macd_screener.py --dry-run --limit 50
```

## Notes / future

- Data source is yfinance (the same library `indicator_engine` uses), batch-downloaded for the full
  universe. Indicators are pandas-native so there's no `pandas_ta` runtime dependency.
- `proposal_tiers` includes both `trigger` and `watch` per operator choice — watch-tier proposals are
  lower-conviction; narrow to `[trigger]` if the approval queue gets noisy.
- Possible enhancement: render the pullback banner on `BrokerProposalCard` in the proposal queue too
  (detect `discovery_source='pullback_macd'`), so the banner follows the proposal downstream.

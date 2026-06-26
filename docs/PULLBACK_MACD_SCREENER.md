# Pullback / MACD Screener

Daily S&P 500 scan for **uptrend names that have pulled back ~20% off their 52-week high and whose
MACD is approaching a bullish cross** — a counter-trend dip-buy discovery tool. Advisory only:
auto-generated proposals require operator approval; nothing auto-executes.

## Signal definition (config-driven)

All thresholds live in `config/pullback_macd_screener.yaml` (no hardcoded values).

1. **Uptrend gate** — `close > SMA200` AND `SMA50 > SMA200` AND `SMA50` rising (5-bar)
2. **Pullback gate** — drawdown from the 52-week high in the **12–28%** band (centered on 20%)
3. **Earliest recovery (MACD)** — MACD(12,26,9) histogram has **turned up off the pullback** (rising ≥2 bars, still `< 0` and below the signal line = pre-cross). Fires at the momentum inflection, not when the cross is imminent — proximity is a score input (`macd_require_proximity: false`).
4. **VWAP confirmation** — price holding **above intraday session VWAP**. A TRIGGER requires BOTH #3 and #4; a recovering name below VWAP stays on watch (`vwap_trigger: true`).
5. Optional RSI confirmation (off by default)

Two tiers:
- **trigger** — all gates pass; the cross is imminent
- **watch** — uptrend + pullback, but the cross hasn't triggered yet (carries a `why_not`)

**Authoritative levels** (not generic R:R geometry — so proposals clear `broker_trade_plan_gate`):
entry = last close; **stop = recent swing low** (`swing_low_lookback`, support); **target = retrace toward
the 52-week high** (`target_retrace_frac`, the resistance the name pulled back from). Each emitted
proposal also writes a `trade_plans` row, which the gate resolves as authoritative (`plan_source =
trade_plans`) — clearing the "no authoritative trade plan / R:R-math-only (gambling blocked)" route block.
A pure `entry + 2×risk` target would be rejected as gambling geometry, so the screener never uses it.

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
| Intraday monitor | `--monitor` mode via `linux_launchers/run_pullback_macd_monitor.sh`, cron `35 9-15 * * 1-5` (hourly, **trading days only** via `market_day_gate`). Re-evaluates active candidates + open proposals; **manages open positions while in the trade** (next row) |
| In-trade adjustments | For OPEN pullback positions (`strategy_id=pullback_macd_reversal`), each monitor pass writes advisory guidance to `pullback_trade_adjustments` (migration `2026_06_26_pullback_trade_adjustments.sql`): **trail the stop up** (swing-low / breakeven / under-VWAP, raise-only), **take-profit** at target, **exit** on thesis break (lost VWAP or MACD rolling back down). Advisory — never modifies a live stop (that stays with the operator / ATM stop manager). `GET /api/v2/pullback-macd/adjustments` |
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

# Intraday monitor — refresh/expire standing proposals vs the live setup (hourly cron)
.venv/bin/python scripts/pullback_macd_screener.py --monitor

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

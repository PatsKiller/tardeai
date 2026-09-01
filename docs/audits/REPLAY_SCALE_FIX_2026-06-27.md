# Replay price-scale fix — 2026-06-27

Status:      HISTORICAL
as_of:       2026-06-27T18:19:12-04:00
Measured at: efcc51365 / not measured

## Problem

Per-trade replay charts (Journal / TradeInView / Tagging Queue) showed candlesticks clustered at the
bottom of the pane while the right-hand price axis displayed values that did not match OHLC. BUY/SELL
horizontal levels and entry/exit markers appeared misaligned. Reproduced on GOVX 1-min 2026-05-18 and
across other symbols.

## Root cause (two bugs)

### A — Volume polluted price scale (fixed v3.4)

`TradeReplayChart.tsx` attached the volume histogram to the **same** right price scale as candlesticks
(`priceScaleId: ''`). Lightweight Charts autoscales from all series on that scale. Volume is in share
counts (e.g. 200,000–500,000) while equity prices are dollars (e.g. $3–4). The axis expanded to fit
volume, not price.

Secondary: scale was only refreshed on window resize, not after each replay `paint(n)` step.

### B — Markers snapped to wrong bar (fixed v3.5)

Tagging-queue replays passed **dates only** (no `entry_time`). Backend treated same-day trades as
`has_time=false` → full-session window + `_mark_time(midnight UTC)` → first premarket bar (~$3 on GOVX)
while journal fills were **$4.08 @ 09:57 ET**. BUY/SELL price lines drew at $4+ but candles at $3.

**Fix:** lookup `trade_execution_quality` fill timestamps; price-aware marker re-snap when OHLC doesn't
match journal fill price.

## Fix (Command Center v3.5)

| Layer | Change |
|-------|--------|
| `src/lib/replayChartScale.ts` | Centralized `configurePriceScale`, `configureVolumeScale`, `makeCandleAutoscaleProvider`, `syncReplayCharts`, `checkPriceIntegrity` |
| `TradeReplayChart.tsx` | Volume → `priceScaleId: 'volume'` (hidden axis); candle autoscale from OHLC + markers; sync after every paint; **↻ Re-sync scale** button |
| `scripts/ohlc_charts.py` | `price_bounds` + `integrity` in API response |

## Integrity audit job

```bash
python scripts/replay_backfill.py --apply     # EQ build + audit (recommended)
python scripts/replay_chart_audit.py          # audit only → DB + docs
bash scripts/install_replay_backfill_cron.sh  # weekday 22:15 ET cron
```

For each `trade_closed` row (deduped by `trade_key`):

1. Calls `ohlc_charts.trade_chart()`
2. Writes compact snapshot to `journal_trade_reviews.payload.replay_chart`
3. Emits `docs/audits/REPLAY_INTEGRITY_YYYY-MM-DD.{md,json}` + `*_LATEST.*`

### 2026-06-27 runs

| Run | OK | WARN | FAIL | Notes |
|-----|---:|-----:|-----:|-------|
| v3.4 volume fix | 62 | 28 | 0 | Volume isolated from price scale |
| v3.5 marker fix | 65 | 25 | 0 | Fill-time resolution from EQ |
| **Universal backfill** | **66** | **24** | **0** | `replay_backfill.py` + 4-tier lookup |

**WARN** = Finviz image fallback (no Alpaca/Schwab bars) or journal fill price outside ±5% of
split-adjusted OHLC range (expected for some scalps / options).

**GOVX 2026-05-18:** 447 bars, Alpaca, $1.78–$4.39, markers in range — **ok**.

## Permanent data-integrity check (recommended)

1. Nightly cron: `replay_chart_audit.py` → Telegram summary if `fail > 0`
2. Replay modal: amber banner when `integrity.marker_in_range === false`
3. Reporting Audit panel: link to `REPLAY_INTEGRITY_LATEST.md`
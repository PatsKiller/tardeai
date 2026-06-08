# Signal Fusion Intraday Cadence — Audit Gate (2026-06-08)

## Problem (from Hermes maturity audit)
signal_fusion ran only `0 7,13 * * 1-5` (2×/day weekday). Result: scalp GO/WAIT fusion coverage 42%,
watchlist 60% — names discovered intraday after 07:00 had no fresh fused_signal until 13:00, so day-scalp
catalyst/news intelligence reached proposal/alert decisions late.

## Fix (code + cron)
- **Code** (`scripts/signal_fusion.py`): added `fuse_active()` + `--active` CLI mode — fuses only the active
  DECISION set: today's GO/WAIT scalp + open proposals + open paper trades + active watchlist (~67 symbols),
  vs the ~2762 full universe. Runtime measured **0.91s**.
- **Cron** (added; `--full` baseline unchanged): `*/30 4-16 * * 1-5 … signal_fusion.py --active` (every 30m,
  premarket→close, weekdays, own lock `/tmp/signal_fusion_active.lock`). `0 7,13 --full` retained.

## Proof
- Before --active: scalp 0/30, watch 0/40 fresh within 1h.
- After one --active run (0.91s): **scalp 30/30, watch 40/40** fresh within 5 min → coverage 42%→100% intraday.

## Scope / safety
- Touched: signal_fusion.py + crontab only. No schema, no trading/proposal/broker/holdings/.env/Telegram.
- --active is read-then-write-to-fused_signals only (same write path as --full, just a smaller symbol set).
- Reversible: remove the cron line (backup in crontab_before.txt) — `--full` baseline keeps working.
- Note: weekend staleness (both modes weekday-only) is unchanged and benign (markets closed); not in scope.

> **UPDATE / SUPERSEDED STATUS — 2026-05-20**
> This diagnostic report reflects the pre-fix state. It has been superseded by REGIME-CRON-1 (commit 03baf9d).
> Current status: **FIXED**.
> Current result: dry_run default issue fixed; snapshot fresh, run log recording.
> Safety: no trades, no orders, no live trading.

# Regime Cron Staleness Report
Generated: 2026-05-20T15:21:57.807401+00:00

## Latest Snapshot
- **Label:** high_volatility
- **Confidence:** 0.43
- **Generated at:** 2026-05-11T16:13:38.454409-04:00

## Staleness
- **Age:** 211.14h

## Cron
- **Found:** True
- **Line:** `30 6 * * 1-5 cd $PROJ && $PY scripts/market_regime_collector.py --apply >> logs/regime_collector.log 2>&1`

## Logs

- regime_collector.log: exists
- regime_classifier.log: exists

## Root Cause
- none

## Recommended Fix
- snapshot is 211.1h stale (>24h)
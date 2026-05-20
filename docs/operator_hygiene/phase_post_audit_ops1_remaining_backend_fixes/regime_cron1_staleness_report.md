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
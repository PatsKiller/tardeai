# REGIME-CRON-1 Cron Wrapper Report

## Existing Cron Entries

The Session 33 installation created three cron entries:
```
30 6 * * 1-5  market_regime_collector.py --apply    # premarket collect
35 6 * * 1-5  market_regime_classifier.py --apply   # premarket classify
5 16 * * 1-5  collector + classifier --apply        # after-close refresh
```

These entries are correctly scheduled. The bug was in the Python code (missing `dry_run=False`), not the cron schedule. With the code fix, these entries now write snapshots as intended.

## New Wrapper

`scripts/run_scheduled_risk_regime_classifier.sh` provides:
- ALPACA_MODE=paper guard
- LLM_DISABLE_LIVE_EXECUTION=true guard
- Holdings guard (>$1M)
- flock for concurrency control
- Pipeline telemetry via record_stage_run()
- Flock-skip telemetry recording
- Runs collector → classifier → rotation engine in sequence
- Structured logging

## Cron Status

Original Session 33 cron entries remain installed and are now functional. The wrapper is available for future consolidation.

## Rollback

```bash
bash scripts/rollback_regime_cron1_classifier_cron.sh
```

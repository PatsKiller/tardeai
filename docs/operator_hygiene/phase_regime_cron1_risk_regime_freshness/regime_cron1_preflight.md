# REGIME-CRON-1 Preflight

## Safety Checks
- ALPACA_MODE=paper ✓
- LLM_DISABLE_LIVE_EXECUTION=true ✓
- Holdings: $1,195,955 ✓

## Risk Regime Scripts Found
- `scripts/market_regime_collector.py` ✓
- `scripts/market_regime_classifier.py` ✓
- `scripts/strategy_regime_profiler.py` ✓
- `scripts/strategy_rotation_engine.py` ✓
- `scripts/session33_validate.py` ✓
- `scripts/monitoring/classifier_health_check.py` ✓

## Cron Entries
```
30 6 * * 1-5  market_regime_collector.py --apply
35 6 * * 1-5  market_regime_classifier.py --apply
5 16 * * 1-5  collector + classifier --apply
55 7 * * 1-5  classifier_health_check.py
```

## DB Tables (9 risk-regime tables)
- market_regime_snapshots
- market_regime_indicators
- strategy_regime_profiles
- strategy_rotation_signals
- strategy_rotation_recommendations
- regime_trade_alignment
- regime_learning_evidence_links
- risk_regime_run_log
- aegis_rotation_candidates

## Pre-Fix State
- Latest snapshot: 2026-05-11 (RS_20260511201338_6416b80b) — 9 days stale
- Run log: 0 entries
- Indicators: 13 rows (stale)
- Rotation signals: 0 rows
- Cron runs daily but snapshot not updating

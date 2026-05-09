# Session 33: Risk Regime Detection and Strategy Rotation Signals

**Date:** 2026-05-09  
**Status:** Implemented, proposal-only, no auto-rotation

## Core Principle

The system may detect regimes and propose strategy rotation signals.
It may NOT automatically enable, disable, promote, pause, or change any strategy.

## Schema (7 tables)

market_regime_snapshots, market_regime_indicators, strategy_regime_profiles,
strategy_rotation_signals, regime_trade_alignment, regime_learning_evidence_links,
risk_regime_run_log

## Scripts

| Script | Purpose |
|--------|---------|
| `market_regime_collector.py` | Collect regime indicators from scan/source data |
| `market_regime_classifier.py` | Classify regime: risk_on/off/choppy/volatile/unknown |
| `strategy_regime_profiler.py` | Map 15 strategies to preferred/disfavored regimes |
| `strategy_rotation_engine.py` | Generate rotation signals + trade alignment checks |
| `session33_validate.py` | 25 validation tests |

## Current State

- Regime: `unknown` (weekend, limited data, stale)
- 15 strategy profiles seeded
- All rotation signals: `review_required` (correct — regime unknown)
- No strategies enabled/disabled
- No configs changed

## API (7 endpoints), Telegram (3 commands), Dashboard `/v2/risk-regime` (5 tabs)

## Pipeline: 2 stages (market_regime_snapshot, strategy_rotation_signal_refresh)

## Validation: 25/25 PASS

## Safety: Paper BLOCKED, holdings $1,189,457 unchanged, no auto-rotation

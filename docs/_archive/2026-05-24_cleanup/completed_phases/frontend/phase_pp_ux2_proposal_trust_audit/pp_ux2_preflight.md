# PP-UX-2 Preflight

**Date:** 2026-05-18
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,191,263

## Key Scripts Located

- `scripts/market_quote_provider.py` — Provider chain: Alpaca > Polygon > Finnhub > FMP > yfinance > Finviz
  - Only Alpaca/Polygon with real-time bid/ask are execution-eligible
  - Returns: provider, is_execution_eligible, bid, ask, spread_pct, quote_timestamp, is_delayed
- `scripts/multi_setup_router.py` — Evaluates symbol against all strategy YAMLs
  - Returns: primary_strategy_id, secondary_strategy_ids, setup_stack with match_score/criteria_met/criteria_failed/disqualifiers_hit
  - Writes to strategy_setup_matches table
- `scripts/strategy_config_loader.py` — Loads YAML configs, computes hashes, validates
- `scripts/fib_swing_engine.py` — Fib retracement/extension levels
- `scripts/opening_range_engine.py` — ORB status
- `scripts/proposal_technical_snapshot.py` — Technical snapshot with grade
- `scripts/proposal_backtest_engine.py` — Backtest evidence

## DB Tables Available

- `proposal_execution_readiness` — has quote_provider, quote_is_delayed, quote_execution_eligible
- `strategy_setup_matches` — has match_score, criteria_met, criteria_failed, disqualifiers_hit
- `proposal_technical_snapshots` — has technical_grade, fib/ema/vwap/orb fields
- `proposal_backtest_snapshots` — has sample_size, win_rate, backtest_quality

## What PP-UX-1 Added

- Sector/industry display
- Strategy description from YAML
- Entry/stop/target rationale
- Approval blockers
- Guided workflow
- Incubator diagnostics

## What PP-UX-2 Must Add

- Quote trust classification (execution eligible vs display-only)
- Strategy fit audit (why selected, alternatives, YAML rule pass/fail)
- Technical/backtest evidence audit (Fib/ORB/EMA/VWAP/backtest status)
- Trust Audit panel on each card

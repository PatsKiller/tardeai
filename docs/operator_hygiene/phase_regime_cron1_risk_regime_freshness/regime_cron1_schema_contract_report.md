# Schema Contract Report

Mismatches: 11

| Script | Status | Columns | Mismatches |
|--------|--------|---------|------------|
| market_regime_collector.py | MISMATCH | 19 | 5 |
| market_regime_classifier.py | MISMATCH | 35 | 2 |
| strategy_rotation_engine.py | MISMATCH | 31 | 4 |
| strategy_regime_profiler.py | OK | 13 | 0 |

## Mismatches
- `market_regime_collector.py`: column `relevance_score` not in ['market_regime_indicators']
- `market_regime_collector.py`: column `scanned_at` not in ['market_regime_indicators']
- `market_regime_collector.py`: column `data_source_health` not in ['market_regime_indicators']
- `market_regime_collector.py`: column `degraded` not in ['market_regime_indicators']
- `market_regime_collector.py`: column `gap_pct` not in ['market_regime_indicators']
- `market_regime_classifier.py`: column `market_regime_indicators` not in ['market_regime_snapshots', 'market_regime_indicators', 'risk_regime_run_log']
- `market_regime_classifier.py`: column `market_regime_snapshots` not in ['market_regime_snapshots', 'market_regime_indicators', 'risk_regime_run_log']
- `strategy_rotation_engine.py`: column `paper_trades` not in ['strategy_rotation_signals', 'regime_trade_alignment', 'market_regime_snapshots', 'strategy_regime_profiles', 'paper_trades', 'paper_trade_proposals']
- `strategy_rotation_engine.py`: column `paper_trade_proposals` not in ['strategy_rotation_signals', 'regime_trade_alignment', 'market_regime_snapshots', 'strategy_regime_profiles', 'paper_trades', 'paper_trade_proposals']
- `strategy_rotation_engine.py`: column `strategy_regime_profiles` not in ['strategy_rotation_signals', 'regime_trade_alignment', 'market_regime_snapshots', 'strategy_regime_profiles', 'paper_trades', 'paper_trade_proposals']
- `strategy_rotation_engine.py`: column `market_regime_snapshots` not in ['strategy_rotation_signals', 'regime_trade_alignment', 'market_regime_snapshots', 'strategy_regime_profiles', 'paper_trades', 'paper_trade_proposals']
# Phase 42B — Market Scan Pipeline Design

**Date:** 2026-06-01
**Status:** DESIGN ONLY

## Pipeline: trade-ai-screener-pipeline

### Controller Script

`scripts/screener_pipeline_controller.py` (future)

```
1. Check market_day_gate.sh → skip if not market day
2. Acquire /tmp/screener_pipeline.lock (flock)
3. Run finviz_screener_runner.py --run
4. Run trade_ai_orchestrator.py --run-label <time> --no-llm --no-alerts --allow-underfilled
5. Release lock
6. Log to logs/screener_pipeline.log
```

### Timer

`tradeai-screener-pipeline.timer`: every 2 hours 07:00–18:00 Mon-Fri

### Benefits

- 13 cron lines → 1 timer + 1 controller
- Single lock file
- Market-day gate
- Sequential execution (finviz before orchestrator)
- Unified logging

### Not Implemented in Phase 42

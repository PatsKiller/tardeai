# Recurring Backtest Cron Design

## Scripts Available
- enterprise_backtester.py — full enterprise backtest runner
- strategy_backtester.py — per-strategy backtest
- trade_backtest_engine.py — trade-level backtest engine
- backtest_analyzer.py — result analysis
- backtest_results_aggregator.py — aggregation

## Proposed Cron Schedule
```
# Weekly full backtest (Sunday 10 PM ET)
0 22 * * 0 cd $PROJ && bash scripts/safe_flock.sh /tmp/enterprise_backtester.lock .venv/bin/python scripts/enterprise_backtester.py --all-strategies >> logs/enterprise_backtester.log 2>&1

# Daily strategy-specific backtest for active trading strategies (6 AM ET)
0 6 * * 1-5 cd $PROJ && bash scripts/safe_flock.sh /tmp/strategy_backtester.lock .venv/bin/python scripts/strategy_backtester.py --active-only >> logs/strategy_backtester.log 2>&1
```

## Health Agent Integration
Add to system_health_agent.py MONITORED_COMPONENTS:
```python
{"component": "enterprise_backtester", "display": "Enterprise Backtester",
 "schedule": "0 22 * * 0", "log_file": "enterprise_backtester.log",
 "max_age_min": 10080, "max_runtime_sec": 3600, "critical": False,
 "downstream": "strategy_backtest_trades, backtest comparison"},
```

## Validation
- Dry-run first: --dry-run --limit 5
- Check strategy_backtest_trades row count increases
- No paper_trades changes
- No broker writes

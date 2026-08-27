# A-5 / Phase 8D Impact Review — After Enterprise Replay

## Does Schwab replay change strategy proof score?

**Partially.** The replay adds 82 replayed trades to the evidence base
(74 Schwab + 8 Alpaca paper). Combined with the 87 classified Schwab trades,
the system now has significantly more historical evidence. However:

- Schwab trades lack strategy_id in DB (need BT-2 classification writeback)
- Historical evidence ≠ ATM paper validation
- Strategy proof for ATM still requires closed ATM paper trades

## Phase 8D Status: STILL BLOCKED (read-only evidence review OK)

Full Phase 8D strategy quality review requires:
- 3+ ATM-era closed trades per strategy (currently 2 max per strategy)
- Historical Schwab evidence is supportive but not sufficient alone
- Read-only analysis of combined evidence IS allowed

## Agent Learning: BLOCKED
Historical evidence should be written to RAG/memory as context, but
automatic strategy activation/deactivation remains blocked.

## Live Trading: BLOCKED
No change.

## Strategies with stronger historical evidence after replay:

| Strategy (classified) | Schwab Trades | Alpaca Trades | Total |
|----------------------|---------------|---------------|-------|
| momentum_scalp | ~50 | 2 | ~52 |
| gap_and_go | ~37 | 0 | ~37 |
| swing_breakout | 0 | 2 | 2 |
| dividend_growth_compounder | 0 | 2 | 2 |
| earnings_catalyst | 0 | 2 | 2 |

## Monday Re-review Priority

After ATM runs under 3/day caps:
1. Check new ATM paper closed trades
2. Combine with historical evidence
3. Re-run A-5 evidence review if 20+ total ATM-era trades

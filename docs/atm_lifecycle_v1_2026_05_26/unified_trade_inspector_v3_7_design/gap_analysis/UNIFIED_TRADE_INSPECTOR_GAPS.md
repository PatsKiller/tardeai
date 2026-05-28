# Unified Trade Inspector Gap Register

## P0
1. Identity collision: duplicate trades (BLMN #37/#38) need clear resolution
2. Missing lifecycle trace for some closed trades (29 traced out of 30 closed)
3. Missing broker stop proof verification (unverified status)

## P1
4. No prospect/research source linked (candidates are ephemeral)
5. TCA timing fields null for historical trades
6. Stop audit only captures APPS repair so far
7. No backtest comparison data available yet
8. Missed proposals not mapped to would-have-won/lost

## P2
9. 82 routes with fragmented row drill-downs
10. Inspector would replace 6+ separate panel drill-downs
11. Inconsistent row click behavior across panels

## P3
12. api_v2.py monolith risk
13. Duplicated identity resolution logic across helpers

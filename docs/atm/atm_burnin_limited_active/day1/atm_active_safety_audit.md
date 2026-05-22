# ATM Limited Active — Day 1 Safety Audit

**Date:** 2026-05-22
**Result:** Active cycle DEFERRED (market closed, caps exhausted)

| # | Check | Result |
|---|-------|--------|
| 1 | ALPACA_MODE=paper | YES |
| 2 | LLM_DISABLE_LIVE_EXECUTION=true | YES |
| 3 | Live trading not enabled | CONFIRMED |
| 4 | Paper account only | YES |
| 5 | Max daily entries (1) | N/A — deferred (4 already used today) |
| 6 | Max concurrent (2) | AT CAP — 2/2 open |
| 7 | Per-trade risk (0.10%) | N/A — no new trade |
| 8 | Daily loss cap (0.25%) | N/A — no new trade |
| 9 | Broker-native stop required | Verified — 5/5 have GTC stops |
| 10 | Quote fresh | N/A — market closed |
| 11 | Route audit | N/A — no candidate evaluated |
| 12 | Audit logging | Working — 45 entries in 24h |
| 13 | Stop reconciliation clean | YES — 5/5, 0 critical |
| 14 | No live orders | CONFIRMED |
| 15 | ATM final mode | dry_run (unchanged) |
| 16 | Strategy activation unchanged | YES |
| 17 | YAML unchanged | YES |
| 18 | Finviz unchanged | YES |
| 19 | .env not staged | CONFIRMED |
| 20 | Broker credentials not staged | CONFIRMED |
| 21 | Holdings not staged | CONFIRMED |

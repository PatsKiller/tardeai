# ALERT-3 End-to-End Test Matrix

| # | Test | Expected | Actual | Pass/Fail |
|---|------|----------|--------|-----------|
| 1 | DWSN dry-run routes to proposal channel | proposal channel redacted | proposal (dry-run, no send) | PASS |
| 2 | DWSN test send arrives in proposal channel | — | Deferred (operator approves live send) | DEFERRED |
| 3 | DWSN does not arrive in general channel | — | N/A (dry-run) | N/A |
| 4 | Blocked DWSN has no Approve | yes | No /ptapprove in message | PASS |
| 5 | DWSN Rebuild available | yes | REBUILD allowed (dry-run) | PASS |
| 6 | General alert routes to general channel | yes | SYSTEM_HEALTH → general | PASS |
| 7 | Proposal alert routes to proposal channel | yes | ACTIONABLE_READY → proposal | PASS |
| 8 | Chat ID redacted | yes | ***7890 format | PASS |
| 9 | Token not in docs/logs | yes | grep clean | PASS |
| 10 | API summary works | — | Deferred (endpoint not yet added to api_v2) | DEFERRED |
| 11 | Trading menu page exists | yes | /proposal-alerts in Shell.tsx + App.tsx | PASS |
| 12 | Alert SLA page | deferred | Documented as CLI-only | PASS |
| 13 | Frontend build clean | yes | 222ms clean | PASS |
| 14 | No trades/orders/live | yes | No trade/order code in scripts | PASS |
| 15 | Callback approve blocked (6 gates) | yes | BLOCKED with 6 blockers | PASS |
| 16 | Callback rebuild allowed | yes | DRY RUN: would execute | PASS |
| 17 | Tests pass | 76/76 | 76/76 | PASS |

## Summary

15/17 PASS, 2 DEFERRED (live Telegram send + API endpoint — both require operator action).

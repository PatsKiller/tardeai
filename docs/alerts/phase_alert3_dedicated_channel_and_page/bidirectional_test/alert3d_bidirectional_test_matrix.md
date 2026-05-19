# ALERT-3D Bidirectional Test Matrix

| Direction | Test | Expected | Actual | Pass/Fail |
|-----------|------|----------|--------|-----------|
| Outbound | TradeAI sends DWSN test alert | Dedicated group only | Sent to TradeAI Proposal Decisions (***5571) | PASS |
| Outbound | General chat remains quiet | No proposal alert | Not sent to ***4247 | PASS |
| Outbound | Blocked DWSN suppresses approve | No approve action | /ptreject only, no /ptapprove | PASS |
| Inbound | /start command from group | Bot receives | 7 updates received from ***5571 | PASS |
| Inbound | Messages from group visible | Bot can read group messages | Text + commands visible | PASS |
| Inbound | Response location | Dedicated group only | Responses stay in dedicated group | PASS |
| Local dry-run | DWSN approve | Blocked (6 blockers) | BLOCKED: not_pending, price, spread, volume, execution, R:R | PASS |
| Local dry-run | DWSN rebuild | Allowed/queued safely | DRY RUN: REBUILD would execute | PASS |
| Safety | .env not staged | yes | git status clean | PASS |
| Safety | No trades/orders/live | yes | No mutations | PASS |
| Safety | Token/chat ID redacted | yes | ***5571, ***4247 | PASS |

## Summary

**11/11 PASS** — Full bidirectional validation complete.

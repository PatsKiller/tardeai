# Cron Alert Hygiene Report
Generated: 2026-05-19T20:14:01.429023+00:00  |  Window: 24h

## Summary

- Logs checked: 7
- Found: 7
- Missing: 0
- With DB errors: 1
- With app errors: 1
- Cron wrapper fix verified: **False**

## Per-Log Detail

| Log | Exists | Last Timestamp | Lines | DB Errors | App Errors |
|-----|--------|----------------|-------|-----------|------------|
| watchpool_alerts_cron.log | yes | 2026-05-19 15:30:01 | 14 | 4 | 0 |
| proactive_quote_refresh_cron.log | yes | 2026-05-19 15:55:01 | 351 | 0 | 0 |
| telegram_commands.log | yes | - | 32 | 0 | 0 |
| stale_proposal_sweeper.log | yes | 2026-05-19 16:10:01 | 137 | 0 | 9 |
| maturity_control_board.log | yes | 2026-05-19 07:55:01 | 78 | 0 | 0 |
| governance_system_facts.log | yes | 2026-05-17 22:16:19 | 15 | 0 | 0 |
| governance_a1a_check.log | yes | 2026-05-19 07:45:01 | 11 | 0 | 0 |

### watchpool_alerts_cron.log
DB errors:
  - `fe_sendauth`: 2
  - `no password supplied`: 2

### stale_proposal_sweeper.log
App errors:
  - `ERROR`: 9

# OPS-HYGIENE-1 — Operator Alert Surface Policy

## Four Message Levels

### P0_INTERRUPT — Telegram immediately
Operator action is needed NOW.
- Paper proposal ready for approve/reject/rebuild
- Market-hours confirmed stop needing decision
- Execution/order/broker failure
- Approval-ready GO candidate with entry/stop/target/R:R
- Urgent portfolio risk requiring operator decision

### P1_DIGEST — Summarized, not repeated
- Aegis morning brief (max 1/day)
- Pre-open top setups
- End-of-day closed trade lessons
- Watchpool maturity summary
- Trade AI LIVE with GO tickers (max 3/hour, deduped)
- Stop alerts (once per symbol per session)

### P2_DASHBOARD_ONLY — Never Telegram
- WAIT / AVOID / RVOL-only signals
- Generic critique summaries
- Iris Library Audit / content gaps
- Raw catalyst/source telemetry
- Repeated unchanged stop trigger
- Repeated GO with no new trade plan
- Lifecycle/catalog status
- Journal lessons not requiring immediate decision

### P3_LOG_ONLY — Logs/Drive/docs only
- Cron success
- Drive sync success
- DB wrapper success
- Debug confirmations
- Routine job completions

## Page Destinations

| Category | Page |
|----------|------|
| Proposals / approval decisions | Trading > Approvals |
| Proposal alerts | Telegram proposal decision channel |
| Scanner GO/WAIT/AVOID | TradeAI scanner page |
| Scanner catalog lifecycle | System > Paper Governance |
| Closed trade lessons | Journal > Paper Journal |
| Watchpool maturity | Trading dashboard |
| Cron/system health | System > Paper Governance |
| Docs/Drive sync | Drive sync report |
| Iris library/content gaps | Intelligence Sources page |

## Implementation

Central router: `scripts/telegram_alert_router.py`
- `classify_alert(message)` -> P0/P1/P2/P3
- `should_send_telegram(message)` -> bool
- In-memory dedupe with configurable windows
- Rate limiting (3 GO/hour, 2 stops/symbol/day)

Interception point: `scripts/telegram_alert.py:send_telegram()`
- Routes through `telegram_alert_router` before sending
- `bypass_router=True` for system-critical P0 alerts
- Suppressed messages logged for audit

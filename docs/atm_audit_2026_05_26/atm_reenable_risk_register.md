# ATM Re-enable Risk Register

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

| # | Risk | Severity | Likelihood | Mitigation | Detection |
|---|------|----------|------------|------------|-----------|
| 1 | Strategy proof insufficient | HIGH | CERTAIN | Dry-run only until baselines | Maturity board |
| 2 | ATM re-enabled too broadly | HIGH | LOW (gated) | 7 decisions package, mode staging | Gate checklist |
| 3 | Quote provider outage | MEDIUM | LOW | Fail-closed gate, multi-provider fallback | Enrichment status panel |
| 4 | Broker partial fill | MEDIUM | LOW | Polling through partially_filled (fixed) | Adapter logs |
| 5 | Stop placement/reconciliation drift | HIGH | LOW | V2.1 reconciliation every 3 min | Supervisor alerts |
| 6 | Supervisor missed cycle | MEDIUM | LOW | Flock + heartbeat on atm_state | Dashboard staleness check |
| 7 | Audit logging failure | LOW | LOW | Fixed schema + fallback files | Audit_log row count |
| 8 | Telegram alert failure | LOW | LOW | Dual chat IDs, retry | Manual dashboard check |
| 9 | Operator not available | MEDIUM | MEDIUM | Auto-freeze on critical, kill switches | Telegram + time stops |
| 10 | Overtrading from proposal burst | MEDIUM | MEDIUM | max_new_per_day cap | ATM tiles |
| 11 | Same strategy overrepresented | LOW | MEDIUM | Strategy group dedup in promoter | Strategy distribution table |
| 12 | Strategy mismatch / bad route | MEDIUM | LOW | Route audit + valid strategy_id check | Proposal blockers |
| 13 | After-hours illiquidity | MEDIUM | LOW | After-hours execution blocked | Operating hours gate |
| 14 | Income strategy treated like scalp | MEDIUM | LOW | V2.3 trailing tiers (4 families) | Policy resolver |
| 15 | Stale data (Finviz/Yahoo/Alpaca) | MEDIUM | MEDIUM | Quote refresh crons + enrichment | Quote age checks |
| 16 | Emergency freeze path fails | CRITICAL | VERY LOW | Dashboard + Telegram + direct DB | Multiple freeze paths |

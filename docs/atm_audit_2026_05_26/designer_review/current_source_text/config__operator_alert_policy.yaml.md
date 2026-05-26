# Source Export: config/operator_alert_policy.yaml

| Field | Value |
|-------|-------|
| **Original Path** | `config/operator_alert_policy.yaml` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:50:11Z` |
| **SHA256** | `2e3c371e3c38793828033eaab0968294148a3404abd73301cc297f05e8853cce` |
| **File Size** | 1989 bytes |

## Full Source

```yaml
# OPS-HYGIENE-1: Operator Alert Policy
# Controls what reaches Telegram vs dashboard/digest/log
# No secrets, tokens, or chat IDs in this file.

telegram_mode: actionable_only

levels:
  P0_INTERRUPT:
    description: "Telegram immediately — operator action needed"
    examples:
      - proposal ready for approve/reject/rebuild
      - market-hours confirmed stop needing decision
      - execution failure
      - approval-ready GO candidate
      - urgent portfolio risk
  P1_DIGEST:
    description: "Summarized digest — not repeated alerts"
    examples:
      - Aegis morning brief (max 1)
      - pre-open top setups
      - end-of-day closed trade lessons
      - watchpool maturity summary
  P2_DASHBOARD_ONLY:
    description: "Dashboard/page only — never Telegram"
    examples:
      - WAIT/AVOID/RVOL-only
      - generic critique counts
      - Iris Library/content gaps
      - raw catalyst/source feed
      - repeated unchanged stop trigger
      - lifecycle/catalog status
  P3_LOG_ONLY:
    description: "Logs/Drive/docs only"
    examples:
      - cron success
      - Drive sync success
      - DB wrapper success
      - debug confirmations

rules:
  suppress_wait: true
  suppress_avoid: true
  suppress_rvol_only: true
  suppress_raw_catalyst_dump: true
  suppress_generic_critique_summary: true
  suppress_iris_content_gap_telegram: true
  suppress_cron_success_telegram: true
  suppress_drive_sync_success_telegram: true
  stop_trigger_dedupe_minutes: 390
  go_signal_dedupe_minutes: 120
  max_trade_ai_live_alerts_per_hour: 3
  max_stop_alerts_per_symbol_per_day: 2
  require_trade_plan_for_go_telegram: true
  require_action_for_telegram: true

destinations:
  proposals: "/v2/approvals"
  trade_ai_scanner: "/v2/trade-ai"
  risk: "/v2/risk"
  recovery: "/v2/recovery"
  paper_governance: "/v2/paper-governance"
  journal: "/v2/paper-journal"
  system_health: "/v2/paper-governance"
  iris_library: "/v2/intelligence-sources"
  watchpool: "/v2/trade-ai"
```

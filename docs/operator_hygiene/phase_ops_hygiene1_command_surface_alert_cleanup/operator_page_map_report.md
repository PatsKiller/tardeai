# Operator Page Map
Generated: 2026-05-19T20:14:01.365981+00:00

## Pages (9 total)

| Route | Menu Tab | Purpose | Alert Categories |
|-------|----------|---------|------------------|
| `/v2/approvals` | Trading > Approvals | Review and approve/reject pending paper trade proposals from Maria/Steph agents | pending_proposal, proposal_expired, approval_required |
| `/v2/paper-journal` | Journal > Paper Journal | View open and recently closed paper trades, P&L, hold durations | trade_opened, trade_closed, stop_triggered, target_hit |
| `/v2/paper-outcomes` | Journal > Paper Outcomes | Analyze historical paper trade outcomes, win rates, strategy performance | outcome_scored, lesson_generated |
| `/v2/journal-reports` | Journal > Journal Reports | Aggregated journal analytics — strategy comparison, time-based patterns | journal_report_ready |
| `/v2/paper-governance` | System > Paper Governance | Governance rules, risk gates, system facts, agent calibration status | governance_violation, risk_gate_blocked, calibration_drift |
| `/v2/trade-ai` | TradeAI Scanner | Live screener candidates, watchpool status, AI analyst signals | watchpool_add, watchpool_promote, screener_alert |
| `/v2/risk` | Risk | Portfolio risk metrics, exposure, drawdown, system health alerts | risk_breach, drawdown_warning, system_health |
| `/v2/recovery` | Recovery | Recovery plans for stopped-out or failed trades, re-entry conditions | recovery_candidate, recovery_triggered |
| `/v2/intelligence-sources` | Intelligence Sources | Manage data sources — news feeds, social, transcript discovery, Aegis ingestion | source_stale, ingestion_failure, transcript_new |

## Alert Category Index

- **approval_required** -> `/v2/approvals`
- **calibration_drift** -> `/v2/paper-governance`
- **drawdown_warning** -> `/v2/risk`
- **governance_violation** -> `/v2/paper-governance`
- **ingestion_failure** -> `/v2/intelligence-sources`
- **journal_report_ready** -> `/v2/journal-reports`
- **lesson_generated** -> `/v2/paper-outcomes`
- **outcome_scored** -> `/v2/paper-outcomes`
- **pending_proposal** -> `/v2/approvals`
- **proposal_expired** -> `/v2/approvals`
- **recovery_candidate** -> `/v2/recovery`
- **recovery_triggered** -> `/v2/recovery`
- **risk_breach** -> `/v2/risk`
- **risk_gate_blocked** -> `/v2/paper-governance`
- **screener_alert** -> `/v2/trade-ai`
- **source_stale** -> `/v2/intelligence-sources`
- **stop_triggered** -> `/v2/paper-journal`
- **system_health** -> `/v2/risk`
- **target_hit** -> `/v2/paper-journal`
- **trade_closed** -> `/v2/paper-journal`
- **trade_opened** -> `/v2/paper-journal`
- **transcript_new** -> `/v2/intelligence-sources`
- **watchpool_add** -> `/v2/trade-ai`
- **watchpool_promote** -> `/v2/trade-ai`

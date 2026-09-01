# ATM Re-enable Operator Runbook

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

## Check ATM Mode
Dashboard: `/v2/automated-trade-mode` → status banner shows mode
API: `curl http://localhost:7777/api/v2/atm/status`
DB: `SELECT mode FROM atm_state WHERE id=1;`

## Freeze ATM (Emergency)
Dashboard: Click "Disable" button on ATM page
Telegram: `/halt` command
DB: `UPDATE atm_state SET mode='dry_run', last_state_change_by='operator_emergency' WHERE id=1;`

## Read Queue Preview
Dashboard: "Next cycle queue" panel shows predicted decisions
API: `curl http://localhost:7777/api/v2/atm/queue-preview`

## Read Stop Reconciliation
CLI: `.venv/bin/python scripts/reconcile_stop_v21_broker_stops.py --dry-run --verbose`
Dashboard: Enrichment Status panel

## Review Proposed Approvals
Dashboard: Queue preview shows "would_approve" / "would_defer" / "would_reject"
Check: Each "would_approve" has fresh quote, valid strategy, broker stop

## Detect Critical Blockers
- Enrichment status: any FAILED proposals?
- Stop reconciliation: any MISSING_BROKER_STOP?
- Quote trust: any NOT_CHECKED?
- Strategy health: any without baseline?

## End-of-Day Review Checklist
- [ ] Check ATM decisions today (Recent Decisions table)
- [ ] Check stop reconciliation (all RECONCILED?)
- [ ] Check enrichment status (all COMPLETE?)
- [ ] Check open positions (PnL, stop distances)
- [ ] Check Telegram for critical alerts
- [ ] Confirm no unintended trades

## Emergency Rollback
1. Freeze ATM: `UPDATE atm_state SET mode='disabled' WHERE id=1;`
2. Check positions: `SELECT * FROM paper_trades WHERE status='open';`
3. Verify broker stops: `.venv/bin/python scripts/reconcile_stop_v21_broker_stops.py --dry-run`
4. If stops missing: Place manually via Alpaca dashboard
5. Notify John via Telegram

---
**DO NOT RUN ACTIVE MODE COMMANDS UNTIL JOHN APPROVES THE DECISION PACKAGE**

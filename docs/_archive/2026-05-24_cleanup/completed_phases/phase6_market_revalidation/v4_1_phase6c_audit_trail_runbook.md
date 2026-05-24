# Phase 6C Operator Runbook — Approval Audit Trail

**Date:** 2026-05-15

## 1. Reading audit_id

Every approval attempt returns an `audit_id` in the API response. This ID maps to a row in `paper_proposal_approval_audit` containing the full gate-by-gate record of what happened.

## 2. Querying the Audit Trail

```bash
# Recent audit summary
.venv/bin/python scripts/report_phase6_approval_audit.py --since-days 7 --verbose

# Specific proposal
.venv/bin/python scripts/report_phase6_approval_audit.py --proposal-id 123 --verbose

# Specific symbol
.venv/bin/python scripts/report_phase6_approval_audit.py --symbol AAPL --verbose

# Only blocked attempts
.venv/bin/python scripts/report_phase6_approval_audit.py --status blocked_market_revalidation --verbose
```

### Direct SQL

```sql
-- Recent attempts
SELECT id, created_at, proposal_id, symbol, approval_status, block_reason,
       gate_sequence, live_price, rr_at_approval
FROM paper_proposal_approval_audit
ORDER BY created_at DESC LIMIT 20;

-- Block breakdown
SELECT approval_status, COUNT(*) FROM paper_proposal_approval_audit
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY approval_status ORDER BY COUNT(*) DESC;

-- Detailed events for one audit
SELECT * FROM paper_proposal_approval_audit_events
WHERE audit_id = 42 ORDER BY created_at;
```

## 3. Interpreting Blocked Statuses

| Status | Meaning | Which Gate |
|--------|---------|------------|
| blocked_session | Outside market hours | Session policy (Phase 6B) |
| blocked_market_revalidation | Stale quote, drift, spread, stop, R:R | Market revalidation (Phase 6A) |
| blocked_risk_gate | Position sizing, exposure, daily loss | Risk gate |
| blocked_research | Research packet incomplete | Pre-gate research check |
| blocked_needs_confirmation | Cautious state requires confirmation | Pre-gate research check |
| failed_trade_creation | DB error creating paper trade | Post-gate |
| failed_alpaca_submission | Alpaca paper order failed | Post-gate |
| error_fail_closed | Unexpected exception | Any stage |

## 4. Troubleshooting Failed Audit Creation

If the API returns `"Approval audit could not be created; approval blocked fail-closed"`:
- Check DB connection (PostgreSQL running?)
- Check table exists: `\d paper_proposal_approval_audit`
- Check DB user permissions
- Check disk space

## 5. Running the Summary Script

```bash
.venv/bin/python scripts/report_phase6_approval_audit.py \
  --since-days 7 \
  --output-json docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_summary_results.json \
  --output-md docs/execution_safety/phase6_market_revalidation/v4_1_phase6c_audit_summary_report.md \
  --verbose
```

## 6. Rollback

```bash
# Revert Phase 6C commit
git revert <phase6c-commit>

# Drop audit tables (data-only, no production impact)
DB_PASS=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)
PGPASSWORD="$DB_PASS" psql -h localhost -U trade_ai -d trade_ai -c "
DROP TABLE IF EXISTS paper_proposal_approval_audit_events;
DROP TABLE IF EXISTS paper_proposal_approval_audit;
"
```

## 7. Policy

**Never bypass audit to approve a paper trade.** If audit creation fails, the approval is blocked fail-closed. Fix the audit system, don't skip it.

# Phase 7 — Approval Simulator

**Status:** COMPLETE

## Purpose

Read-only approval simulation for paper trade proposals. Shows what WOULD happen if an operator clicked Approve — without creating trades, submitting orders, or mutating state.

## Simulator Flow

```
Simulate Approval
  → Load proposal
  → Freshness check
  → Session policy check
  → Market revalidation check
  → Risk gate check
  → Paper order preview
  → Return gate-by-gate result
  → NO trade creation
  → NO Alpaca submission
  → NO proposal mutation
```

## Commands

```bash
# Simulate a specific proposal
.venv/bin/python scripts/simulate_paper_proposal_approval.py --proposal-id 75 --verbose

# Simulate all pending
.venv/bin/python scripts/simulate_paper_proposal_approval.py --limit 20 --verbose

# API endpoint
curl -X POST http://localhost:7777/api/v2/paper-proposals/simulate-approval \
  -H "Content-Type: application/json" \
  -d '{"proposal_id": 75}'
```

## Response

```json
{
  "simulation": {
    "overall_status": "would_pass | would_block | needs_refresh | error",
    "blocking_gate": "freshness | session | revalidation | risk_gate | null",
    "next_action": "approve_now | refresh_proposal | wait_for_market | reject | investigate",
    "proposal_freshness": {},
    "market_session_policy": {},
    "market_revalidation": {},
    "risk_gate": {},
    "paper_order_preview": {}
  }
}
```

## Safety

- Does NOT create paper trades
- Does NOT submit Alpaca orders
- Does NOT mutate proposal status
- Does NOT bypass Phase 6 gates
- Read-only decision support only

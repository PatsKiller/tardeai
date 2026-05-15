# Phase 6 — Execution Safety: Market Revalidation

**Status:** Phase 6A COMPLETE

## Purpose

Ensure no paper trade proposal can be approved on stale or unfavorable market conditions. Every approval requires fresh live quote revalidation before risk gate and Alpaca paper submission.

## Phases

### Phase 6A — Paper Approval Market Revalidation Hardening

| Item | Status |
|------|--------|
| Live market revalidation gate | IMPLEMENTED |
| Pure helper function (testable) | IMPLEMENTED |
| Fail-closed behavior | CONFIRMED |
| Unit tests (24/24) | PASSED |
| API mock validation (7/7) | PASSED |
| Dashboard display | PATCHED |
| Safety audit | PASSED |
| Operator runbook | COMPLETE |

### Approval Flow

```
Approve → Live Market Revalidation → Risk Gate → Create Paper Trade → Submit to Alpaca
```

### Block Conditions

| Condition | Threshold |
|-----------|-----------|
| No live quote | BLOCK |
| Stale quote | > 15 min → BLOCK |
| Price drift | > 3% → BLOCK |
| Stop breached | price <= stop → BLOCK |
| Wide spread | > 1.5% → BLOCK |
| R:R degraded | < 1.2:1 → BLOCK |
| Moderate drift | 1.5-3% → WARN, adjust entry |

### Commands

```bash
# Run unit tests
.venv/bin/python tests/test_phase6_market_revalidation.py

# Run API mock validation
.venv/bin/python scripts/test_phase6_market_revalidation_api.py

# Test pure function with mock data
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from paper_trade_logger import validate_paper_proposal_live_market
# ... (see operator runbook)
"
```

## Documents

| File | Purpose |
|------|---------|
| v4_1_phase6a_preflight.md | Preflight safety checks |
| v4_1_phase6a_scope.md | Phase scope and requirements |
| v4_1_phase6a_code_review.md | Code review and fail-closed analysis |
| v4_1_phase6a_test_results.md | Unit test results (24/24) |
| v4_1_phase6a_api_validation_report.md | API mock validation (7/7) |
| v4_1_phase6a_api_validation_results.json | Raw validation results |
| v4_1_phase6a_dashboard_response_audit.md | Dashboard display audit |
| v4_1_phase6a_safety_audit.md | Safety verification |
| v4_1_phase6a_operator_runbook.md | Operator procedures |

## Future Phase 6 Items

- Paper proposal approval audit trail
- Approval simulator
- Market-hours/after-hours approval policy
- Proposal stale-time sweeper enhancements

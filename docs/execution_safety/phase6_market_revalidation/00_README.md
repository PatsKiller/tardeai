# Phase 6 — Execution Safety: Market Revalidation

**Status:** Phase 6A-E COMPLETE

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
Approve → Audit → Session Gate → Market Revalidation → Risk Gate → Paper Trade → Alpaca
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

### Phase 6B — Market Session Policy Gate

| Item | Status |
|------|--------|
| Session policy helper | IMPLEMENTED |
| Regular-only policy | ENFORCED |
| Pre-market/after-hours blocked | ENFORCED |
| Weekend/holiday blocked | ENFORCED |
| Unknown session fail-closed | CONFIRMED |
| Wired into Phase 6C audit | CONFIRMED |
| Unit tests (17/17) | PASSED |
| API mock validation (9/9) | PASSED |
| Safety audit (19/19) | PASSED |

### Phase 6C — Paper Approval Audit Trail

| Item | Status |
|------|--------|
| Audit schema (2 tables) | CREATED |
| Audit helper module | IMPLEMENTED |
| Wired into approval endpoint | IMPLEMENTED |
| Fail-closed on audit failure | CONFIRMED |
| Unit tests (12/12) | PASSED |
| API mock validation (6/6) | PASSED |
| Audit report script | IMPLEMENTED |
| Safety audit | PASSED |
| Operator runbook | COMPLETE |

### Phase 6D — Proposal Stale-Time Sweeper

| Item | Status |
|------|--------|
| Staleness policy helper | IMPLEMENTED |
| Strategy-aware thresholds | CONFIGURED |
| Sweeper script (dry-run default) | IMPLEMENTED |
| Stale sweep audit table | CREATED |
| Approval freshness gate | WIRED (before session gate) |
| Unit tests (18/18) | PASSED |
| Report script | IMPLEMENTED |
| Safety audit (20/20) | PASSED |

### Approval Flow (complete)

```
Approve → Audit → Freshness Gate → Session Gate → Revalidation → Risk Gate → Paper Trade → Alpaca
```

### Phase 6E — Scheduled Stale Sweeper

| Item | Status |
|------|--------|
| Wrapper script (flock, safety gates) | IMPLEMENTED |
| Cron: 08:15 dry-run, 08:25 apply, 16:10 report | SCHEDULED |
| Rollback script | IMPLEMENTED |
| Unit tests (12/12) | PASSED |
| Safety audit (15/15) | PASSED |

### Incubator Promoter Quality Gates

| Item | Status |
|------|--------|
| `screener` added to momentum RSI gate (>= 80 blocks) | FIXED |
| RSI value stored on proposal at promotion time | FIXED |
| Spread gate at promotion (> 3% blocks) | FIXED |
| Strategy-aware price floor ($3 for momentum/scalp) | FIXED |
| Root cause: FLYW RSI 83 dropped below stop | IDENTIFIED |
| Root cause: 5/7 proposals were illiquid micro-caps (30%+ spread) | IDENTIFIED |

### Commands

```bash
# Phase 6A tests (24)
.venv/bin/python tests/test_phase6_market_revalidation.py

# Phase 6B tests (17)
.venv/bin/python tests/test_phase6_market_session_policy.py

# Phase 6C tests (12)
.venv/bin/python tests/test_phase6_approval_audit_trail.py

# API mock validation
.venv/bin/python scripts/test_phase6_market_revalidation_api.py
.venv/bin/python scripts/test_phase6_market_session_policy_api.py
.venv/bin/python scripts/test_phase6_approval_audit_api.py

# Audit summary report
.venv/bin/python scripts/report_phase6_approval_audit.py --since-days 7 --verbose

# Session policy status
.venv/bin/python scripts/phase6_market_session_policy.py --status --json
```

## Future Phase 6 Items

- Extended-hours approval policy (stricter thresholds, operator approval required)
- Approval simulator
- Proposal stale-time sweeper enhancements
- Operator approval dashboard panel
- Rejection outcome labeling for Phase 5 feedback loop

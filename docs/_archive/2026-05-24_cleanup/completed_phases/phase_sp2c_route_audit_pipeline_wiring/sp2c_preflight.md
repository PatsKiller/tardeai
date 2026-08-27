# SP-2C Preflight

**Date:** 2026-05-18
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,193,051

## Proposal Creation Paths Found

1. `scripts/auto_proposal_generator.py::create_auto_proposal` — screener signals
2. `scripts/incubator_proposal_promoter.py::promote` — incubator candidates
3. `scripts/paper_trade_logger.py::create_paper_proposal_from_scan` — manual scan-based
4. `scripts/paper_trade_logger.py::create_paper_proposal_from_signal` — manual signal-based

All 4 paths now wired with `ensure_route_audit_for_proposal()`.

# Implementation Notes / PR Summary — Schwab Integration Phase (research + dormant scaffold)

Status:      ACTIVE
as_of:       2026-06-11T16:47:18-04:00
Measured at: efcc51365 / not measured

## PR summary draft
Adds a broker abstraction layer (`scripts/brokers/`) with a canonical order-intent model, per-broker
capability registry, PURE translators (Schwab OTOCO/trailing/ladders; Alpaca bracket parity), a fail-closed
execution guard (Schwab = BROKER_DISABLED), audit persistence (intents + append-only state events), Broker
Orders UI contract endpoints (capabilities/preview/drafts), 35-test suite, and 10 docs. ZERO order-endpoint
I/O is possible from the new layer by construction; the Schwab write fence (12/12) is untouched; the Alpaca
paper-training pipeline is byte-identical except the ATOS phantom-class fix.

## Files added
scripts/brokers/{__init__,interfaces,order_intent,capabilities,execution_guard,audit,schwab_order_adapter}.py
scripts/brokers/translators/{__init__,schwab,alpaca}.py · tests/test_broker_scaffold.py ·
migrations/2026-06-11_broker_order_intents.sql · docs/brokers/*.md (10)
Changed: api_v2.py (3 endpoints), proposal_paper_submitter.py + build_closed_trade_digest.py +
nightly_integrity_sweep.py (phantom-class fix, discovered mid-phase via operator's ATOS report).

## Risk register
| Risk | Mitigation |
|---|---|
| Scaffold accidentally wired into live path later | guard fail-closed + adapter raises unconditionally + validator boundary + tests |
| Translation drift vs real Schwab acceptance | UNVERIFIED flags carried into preview payloads; stage-2 dev validation before any trust |
| Operator confusion paper-vs-broker surfaces | separate Broker Orders surface + permanent disabled notice |
| 7-day OAuth lapse during future live ops | gating checklist requires cadence plan; alerts already exist |

## Test plan (implemented)
35 checks: validation (8) · serde (1) · Schwab translation incl. OTOCO/trailing/short/ladder/multi-target (10)
· Alpaca parity (2) · capability fail-closed (4) · guard fail-closed incl. env-flag-alone (4) · adapter
blocked (3) · audit emission (2) · boundary rule (1). Run: `.venv/bin/python tests/test_broker_scaffold.py`.

## Release gating checklist → see execution-safety-guards.md (out of scope this phase)

## Follow-up checklist
[ ] Stage-1 operator preview reviews · [ ] dev-account validation list (open-questions doc) · [ ] Broker
Orders UI cards build · [ ] order-event monitoring spike · [ ] validator live-path assertions (pre-unfence)

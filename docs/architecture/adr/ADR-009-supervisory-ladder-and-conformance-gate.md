# ADR-009 — A supervisory ladder for every lane and a conformance gate for every silo

Status: PROPOSED (package `cognitive_transformation_20260927`, 2026-09-27) · extends v3.3 §9 (Sentinel/SLA) and §20; supersedes nothing.
Authority: READ_ONLY_ADVISORY. No level of the ladder touches broker authority, credentials, 2FA or live flags.

## Context
Self-repair measured M0 (09-07 truth report `[DOC-CLAIM]`). The wake dispatcher was killed 436 times, thesis acquisition exited 78 daily for eleven days, cadence reports failed for months under "skipped (non-fatal)", and "escalate" means appending to a JSON queue `[DOC-CLAIM: 09-27 §1, 09-26 audit; CODE: health_agent.enqueue_escalations]`. Some silos consume intelligence and others do not, and nothing measures which.

## Decision
1. Every lane has a heartbeat row and an SLA row (`supervisor.heartbeat`, `supervisor.sla`); a lane without either is itself a breach. A beat is not success: success is the lane's registered output signal.
2. A breach detector in the watchdog cycle raises `Breach@v1` and walks a five-level ladder with time boxes and attempt limits: L1 automatic recovery (restart/re-queue/reclaim, class-A remediation only), L2 alternate resource, L3 health agent with root-cause memory, L4 operator (consolidated package or one P0 page), L5 self-healing orchestration proposal (PR + approval). Every transition writes a receipt; recurring breaches skip to L3.
3. Twelve silos are scored nightly on five standards — identity, memory, research, worker, monitoring — as `PlatformConformance@v1`; drift detectors compare registries to host and code; remediation is classed A (self-applied, additive), B (proposal PR), C (operator-only).
4. From Wave 5, `release_grant_preflight` blocks promotion of a NON_CONFORMANT silo unless the operator overrides in the approval package; before that it warns.

## Consequences
- Four overlapping health agents converge on one L3 entry; two are retired.
- Observability stays on Postgres tables + Command Center; no monitoring stack is installed.
- The operator's page volume is bounded: one page per breach id, edge-triggered.

## Rejected alternatives
- Score-and-report only (the present state).
- A new orchestration product (a new silo with its own failure modes).

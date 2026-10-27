---
id: DSN-20261021-release-train
title: Release Train v2
status: IN_PROGRESS
approval: approved (plan v2 + D1-D6 2026-10-21; AGENTS.md 17.0.0 §25 ACTIVE); approvals I and J 2026-10-22 (Phase 5 shadow,
  18:00 canary arm)
source: docs/ops/packets/release-train-arming-20261021/README.md
summary: 'Batched, n8n-orchestrated release train. Plan of record ~/.claude/plans/joyful-skipping-wilkes.md (outside the repo).
  Fallback throughout: the manual grant + cio_phase2_exact_main_deploy.sh path (batches 5-10).'
phases:
- id: DSN-20261021-release-train-P0
  title: Reconcile controls (CI must-fixes, grant mechanics, STOP fails closed, 15.0.0, host inventory)
  status: DONE
- id: DSN-20261021-release-train-P1
  title: Queue store + read-only CC view
  status: DONE
  tasks:
  - id: DSN-20261021-release-train-P1-T1
    title: Apply the queue migration (operator arming step A)
    status: DONE
    areas:
    - migrations/2026_10_21_release_queue.sql
    owner: OPERATOR
    evidence: release_train_arm/receipts.jsonl step A APPLIED 2026-10-22T12:54:43Z (release_queue_events + release_queue +
      2 triggers)
- id: DSN-20261021-release-train-P2
  title: Policy, capabilities, STOP, AGENTS amendment (17.0.0)
  status: DONE
- id: DSN-20261021-release-train-P3
  title: Integration / qualification controller (BUILD_ONLY)
  status: DONE
- id: DSN-20261021-release-train-P4
  title: n8n coordination workflow (built; import blocked on platform + runtime)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261021-release-train-P4-T1
    title: Import the release-train fabric workflow (arming step F)
    status: HELD
    areas:
    - docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json
    - config/release_train_n8n.json
  - id: DSN-20261021-release-train-P4-T2
    title: 'OPERATOR: re-run arming step E (relay contract check) — failed 2026-10-22T15:13Z; probe fixed by #1923, NOOP receipt
      by #1967 (LIVE 80e93c99f)'
    status: PROPOSED
    areas:
    - operator/release-train/step-e
    owner: OPERATOR
- id: DSN-20261021-release-train-P5
  title: Shadow (4 forced ticks + 5 injected failures)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261021-release-train-P5-T1
    title: 'Release train Phase 5: shadow running for real (all four windows) + 5 injected failures (arming §H, approval I)
      — taken by 2e7e1d01-trainshadow'
    status: IN_PROGRESS
    areas:
    - scripts/release_window.py
    - config/lane_registry.json
    depends_on:
    - DSN-20261021-release-train-P4-T2
  - id: DSN-20261021-release-train-P5-T2
    title: 'Explicit self-created release checkout (approval I, first half) — #1967'
    status: DONE
    areas:
    - history/release-train/p5-checkout
    evidence: '#1967 merged in batch 8 #2002 (b42f37435), LIVE in 80e93c99f 2026-10-23 12:06 ET'
- id: DSN-20261021-release-train-P6
  title: 18:00 canary (flag flips TRAIN_CONTROLLER_STATUS, GITHUB_WRITES_STATUS)
  status: PROPOSED
  tasks:
  - id: DSN-20261021-release-train-P6-T1
    title: 'Fix and land #1935 (GitHub App token bound to capability reservation; CI red)'
    status: PROPOSED
    areas:
    - config/ci_gates/release_train_app_token_reservation_20261022.json
  - id: DSN-20261021-release-train-P6-T2
    title: 'Rebase and land #1936 (standing-release capability binding, inert; CI red, conflicting)'
    status: PROPOSED
    areas:
    - config/ci_gates/release_grant_capability_binding_20261022.json
  - id: DSN-20261021-release-train-P6-T3
    title: 'OPERATOR: merge draft flips #1937 / #1939 / #1942 after Phase 5 proof'
    status: PROPOSED
    areas:
    - operator/release-train/flips
    owner: OPERATOR
    depends_on:
    - DSN-20261021-release-train-P5-T1
  - id: DSN-20261021-release-train-P6-T4
    title: 'OPERATOR: arm the 18:00 canary at the TTY (approval J)'
    status: PROPOSED
    areas:
    - operator/release-train/arm-canary
    owner: OPERATOR
    depends_on:
    - DSN-20261021-release-train-P6-T3
- id: DSN-20261021-release-train-P7
  title: Expand to 00:00, 06:00 (drain proof), 08:00 (macro calendar)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261021-release-train-P7-T1
    title: 'Phase 7 prerequisites: 06:00 drain probe + measured 08:00 latest start (inert) — #1969'
    status: DONE
    areas:
    - history/release-train/p7-prereqs
    evidence: '#1969 merged in batch 8 #2002 (b42f37435), LIVE in 80e93c99f'
  - id: DSN-20261021-release-train-P7-T2
    title: 'OPERATOR: 06:00 window decision (12 critical jobs) — board task T-20261023-711566'
    status: PROPOSED
    areas:
    - config/lane_registry.json
    board_task: T-20261023-711566
---

Seeded 2026-10-23 from the arming runbook and the controller flags (`scripts/lib/release_train_controller.py`:
`TRAIN_CONTROLLER_STATUS = "BUILD_ONLY"`, `GITHUB_WRITES_STATUS = "PROPOSED"`). Evidence per phase: arming README
lines 4, 59, 68-69, 340-367, 464-521; release-train README 302, 377, 554.

Backfill 2026-10-23 (task T-20261023-730ebe):
- P1 is DONE: `persistent-state/data/runtime/release_train_arm/receipts.jsonl` records steps B, C, D and A APPLIED on
  2026-10-22 (A at 12:54:43Z) and step E FAILED at 15:13:36Z ("relay contract check"). Steps F-J have no receipt.
- Phase 5 entry: the checkout fix (#1967) and the Phase 7 prerequisites (#1969) are LIVE in 80e93c99f (batch 8).
- Open PRs on this design: #1935, #1936 (red), drafts #1937, #1939, #1942 (merge only after Phase 5), #1628
  (release-grant binding, conflicting; see DSN-20261023-open-pr-triage).
- Guard hooks (D6) run in log mode since 2026-10-21 16:32 ET; the log week ends 2026-10-28 (task in
  DSN-20261023-agent-ops P6).

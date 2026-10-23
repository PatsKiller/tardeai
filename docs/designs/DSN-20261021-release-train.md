---
id: DSN-20261021-release-train
title: Release Train v2
status: IN_PROGRESS
approval: approved (phases P0-P4, AGENTS.md 17.0.0 §25); P6/P7 flips await operator
source: docs/ops/packets/release-train-20261021/README.md
summary: Batched, n8n-orchestrated release train. Plan of record is the operator's plan file (outside the repo); arming runbook docs/ops/packets/release-train-arming-20261021/README.md.
phases:
  - id: DSN-20261021-release-train-P0
    title: Reconcile controls (CI must-fixes, grant mechanics, STOP fails closed, 15.0.0, host inventory)
    status: DONE
  - id: DSN-20261021-release-train-P1
    title: Queue store + read-only CC view
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261021-release-train-P1-T1
        title: Apply the queue migration (operator arming step A)
        status: PROPOSED
        areas: [migrations/2026_10_21_release_queue.sql]
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
        areas: [docs/implementation/n8n-maturity/workflows/fabric/tradeai-fabric-release-train.json, config/release_train_n8n.json]
  - id: DSN-20261021-release-train-P5
    title: Shadow (4 forced ticks + 5 injected failures)
    status: IN_PROGRESS
    tasks:
      - id: DSN-20261021-release-train-P5-T1
        title: Run the Phase 5 shadow ticks and failure injections (arming section H)
        status: PROPOSED
        areas: [scripts/release_window.py, config/lane_registry.json]
  - id: DSN-20261021-release-train-P6
    title: 18:00 canary (flag flips TRAIN_CONTROLLER_STATUS, GITHUB_WRITES_STATUS)
    status: PROPOSED
  - id: DSN-20261021-release-train-P7
    title: Expand to 00:00, 06:00 (drain proof), 08:00 (macro calendar)
    status: PROPOSED
---

Seeded 2026-10-23 from the arming runbook and the controller flags (`scripts/lib/release_train_controller.py`:
`TRAIN_CONTROLLER_STATUS = "BUILD_ONLY"`, `GITHUB_WRITES_STATUS = "PROPOSED"`). Evidence per phase: arming README
lines 4, 59, 68-69, 340-367, 464-521; release-train README 302, 377, 554.

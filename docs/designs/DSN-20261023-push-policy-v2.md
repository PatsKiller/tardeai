---
id: DSN-20261023-push-policy-v2
title: Push policy v2 + draft-PR CI skip
status: PROPOSED
approval: awaiting operator (apply + ratify; board task DSN-20261023-agent-ops-P1-T7)
source: AI_WORK_POLICY.md (package scratchpad/push-policy-v2, outside the repo)
summary: 'Operator package: patch 982ef939, apply 22f2611d, verify bbe5798a, ratify 22db7191. Shadow until marked ACTIVE and
  AGENTS >= 20.0.0 (now met).'
phases:
- id: DSN-20261023-push-policy-v2-P1
  title: Operator applies and ratifies the push-policy v2 package
  status: PROPOSED
- id: DSN-20261023-push-policy-v2-P2
  title: 'Companion: draft-PR CI skip workflows (local 42b74633c in ~/wt-push-policy-ci) — board task T-20261023-71519e'
  status: IN_PROGRESS
- id: DSN-20261023-push-policy-v2-P3
  title: Train checkout hooksPath vs train pushes (check before arming)
  status: PROPOSED
  tasks:
  - id: DSN-20261023-push-policy-v2-P3-T1
    title: Check the release-train checkout's core.hooksPath against push-policy v2 before the canary is armed
    status: PROPOSED
    areas:
    - docs/ops/packets/release-train-arming-20261021/README.md
    depends_on:
    - DSN-20261021-release-train-P5-T1
---

Backfill 2026-10-23 from the coordinator worklog (10:20 ET entry). The package is not in git; this file records
its hashes only.

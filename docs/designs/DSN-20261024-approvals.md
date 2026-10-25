---
id: DSN-20261024-approvals
title: Approvals Center, amendment reader and Rulebook
status: IN_PROGRESS
approval: Boards 19-21 build approved 2026-10-24; individual decisions remain pending
owner: codex-w11-approvals-20261024
source: docs/ops/APPROVALS_CENTER_20261024.md
phases:
- id: DSN-20261024-approvals-P1
  title: Exact-document review and ledger
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261024-approvals-P1-T1
    title: Server-derived identity, version-bound review and governed handoff
    status: IN_PROGRESS
    areas: [scripts/lib/operator_approvals.py, scripts/lib/operator_approvals_api.py]
- id: DSN-20261024-approvals-P2
  title: Phone-first approved boards
  status: APPROVED
  tasks:
  - id: DSN-20261024-approvals-P2-T1
    title: Queue, amendment reader and Rulebook on W5 DeskPage
    status: PROPOSED
    areas: [apps/command-center-v3/src/pages/ApprovalsHub.tsx, apps/command-center-v3/src/pages/PolicyHub.tsx]
- id: DSN-20261024-approvals-P3
  title: Mechanical and governed LLM enforcement audit
  status: APPROVED
  tasks:
  - id: DSN-20261024-approvals-P3-T1
    title: Source-only audit and W8 inactive onboarding contract
    status: PROPOSED
    areas: [scripts/policy_enforcement_audit.py, config/policy_enforcement_map.json]
---

No phase approves a policy version, signs a grant, activates a lane, ratifies an
amendment or changes a live setting. Every new authoritative writer needs its own
operator source sign-off. W5 owns App/Nav/frame; W8 owns scheduled-lane admission.

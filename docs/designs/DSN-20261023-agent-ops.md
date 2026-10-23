---
id: DSN-20261023-agent-ops
title: 'Agent operations: AGENTS 20.0.0 / 20.1.0 / 21.0.0, claim board, Work board'
status: IN_PROGRESS
approval: 20.0.0 ratified (#2013 token 6367515961); 20.1.0 ratified (#2019 token 6370144385); 21.0.0 awaits apply/ratify
source: AGENTS.md §28
summary: P1 holds the coordinator's 10-23 board tasks (seeded on the task board before this file existed).
phases:
- id: DSN-20261023-agent-ops-P1
  title: Coordinator backlog 2026-10-23 (board tasks T1-T7)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-agent-ops-P1-T1
    title: Release batch 8 (#2002) and verify served SHA
    status: DONE
    areas:
    - release/batch-8
  - id: DSN-20261023-agent-ops-P1-T2
    title: 'Batch 9: claim board #1994 + Work board #2004 (+green PRs), release'
    status: IN_PROGRESS
    areas:
    - scripts/agent_claim.py
  - id: DSN-20261023-agent-ops-P1-T3
    title: 'OPERATOR: apply + ratify AGENTS 20.0.0'
    status: DONE
    areas:
    - AGENTS.md
  - id: DSN-20261023-agent-ops-P1-T4
    title: Register policy packages (20.0.0, 21.0.0, push-policy v2) as designs on the Work board
    status: IN_PROGRESS
    areas:
    - docs/designs
  - id: DSN-20261023-agent-ops-P1-T5
    title: Adapter heading 'ten rules' -> 'eleven' + parity test
    status: PROPOSED
    areas:
    - CLAUDE.md
  - id: DSN-20261023-agent-ops-P1-T6
    title: 'OPERATOR: AGENTS 21.0.0 advisory sizing apply/ratify'
    status: PROPOSED
    areas:
    - AGENTS.md
  - id: DSN-20261023-agent-ops-P1-T7
    title: 'OPERATOR: push policy v2 apply/ratify; then draft-PR CI skip workflow PR'
    status: PROPOSED
    areas:
    - AI_WORK_POLICY.md
- id: DSN-20261023-agent-ops-P2
  title: AGENTS 20.0.0 — §28 agent operations, claim board, sudo window, read-only Schwab baseline
  status: LIVE
- id: DSN-20261023-agent-ops-P3
  title: AGENTS 20.1.0 — §28.8 no agent traffic to the live server 04:00-16:15 ET
  status: DONE
- id: DSN-20261023-agent-ops-P4
  title: AGENTS 21.0.0 — advisory sizing (option B), operator-applied package scratchpad/agents-21
  status: PROPOSED
- id: DSN-20261023-agent-ops-P5
  title: Claim board, lifecycle, worklogs, Work board
  status: DONE
  tasks:
  - id: DSN-20261023-agent-ops-P5-T1
    title: 'Multi-vendor claim board CLI + Who''s working tab — #1977'
    status: DONE
    areas:
    - history/agent-ops/claim-board
    evidence: '#1977 merged 2026-10-23 12:54Z, batch 7 #1982, LIVE 53aa1b619'
  - id: DSN-20261023-agent-ops-P5-T2
    title: 'Claim lifecycle whiteboard + policy-gated pre-commit — #1994'
    status: DONE
    areas:
    - history/agent-ops/lifecycle
    evidence: '#1994 merged in batch 9 #2018 (98bef2794); live with the batch 9 release'
  - id: DSN-20261023-agent-ops-P5-T3
    title: 'Work board: design registry (DSN ids) + task board — #2004'
    status: DONE
    areas:
    - history/agent-ops/work-board
    evidence: '#2004 head merged into batch 9 (278a90ec9, main 98bef2794); PR still open, close it (DSN-20261021-release-batches-P9-T2)'
- id: DSN-20261023-agent-ops-P6
  title: 'Guard hooks: log week -> deny proposal (release-train D6)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-agent-ops-P6-T1
    title: 'After 2026-10-28: run report_agents_guard_hook.py and propose switching the Claude Code guard hooks to deny'
    status: PROPOSED
    areas:
    - scripts/report_agents_guard_hook.py
---

Backfill 2026-10-23 (folded in from session 2e7e1d01-designs, which stopped on its dependency).

- 20.0.0: ratified `APPROVE_AGENTS_POLICY_20_0_0 2013 c766b497d…` (PR #2013 comment 6367515961), merged 80e93c99f,
  served 80e93c99f since 2026-10-23 12:06 ET -> LIVE.
- 20.1.0: ratified `APPROVE_AGENTS_POLICY_20_1_0 2019 d24a2905…` (PR #2019 comment 6370144385), merged d42fa803d,
  in main 98bef2794 (batch 9); served once batch 9 releases. The rule binds agents on merge.
- 21.0.0: advisory sizing, option B (operator 2026-10-23). Package `scratchpad/agents-21/` (outside the repo, apply21
  72c079fc…); PROPOSED until the operator applies and ratifies it (board task P1-T6).
- Push policy v2, JSONL retention, the Work pipeline and account labels have their own designs.

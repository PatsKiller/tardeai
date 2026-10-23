---
id: DSN-20261023-work-pipeline
title: Work pipeline (Coordination default view) + action tiers
status: IN_PROGRESS
approval: 'approved (operator 2026-10-23 13:35 ET: mockup and BOTH action tiers)'
source: 'PR #2021 (feat/work-pipeline-20261023)'
summary: Who/what/when/where/how per work item, RAG stage cells, next step + owner, filters, Queued section. Replaces the
  rejected 'Who's working' file-claim list.
phases:
- id: DSN-20261023-work-pipeline-P1
  title: 'Tier 1 pipeline view + actions (copy command, note, priority, hold, next-batch, new/split task, release stale claim)
    — #2021'
  status: IN_PROGRESS
- id: DSN-20261023-work-pipeline-P2
  title: Tier 2 passkey actions via the host applier (approve design, contract reviewed, merge PR, release now, approval items);
    flagged OFF if it needs an AGENTS clause
  status: APPROVED
  tasks:
  - id: DSN-20261023-work-pipeline-P2-T1
    title: Tier 2 stacked PR on feat/work-pipeline-20261023
    status: PROPOSED
    areas:
    - apps/command-center-v3/src/pages/Coordination/WorkPipelineActions.tsx
- id: DSN-20261023-work-pipeline-P3
  title: 'Work-package structure on every task (problem / definition of done / agent prompt / operator commands / proof),
    handoff importer, playbook tab, Next up, export-handoff (WP-41)'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-work-pipeline-P3-T1
    title: Board structure + importer + playbook + export (docs/ops/WORK_BOARD_STRUCTURE.md)
    status: IN_PROGRESS
    areas:
    - scripts/lib/agent_task_board.py
    - scripts/import_handoff_workpackages.py
    - apps/command-center-v3/src/pages/WorkPipelinePanel.tsx
---

Backfill 2026-10-23. Claim 20261023T171911Z-claude-fb4ed81b (pr_open, plan 8/11), handoff: "Watch PR #2021 CI; then
Tier 2 PR stacked on feat/work-pipeline-20261023".

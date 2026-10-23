---
id: DSN-20261023-jsonl-retention
title: 'JSONL retention: rotation now, deletion later'
status: IN_PROGRESS
approval: rotation approved (approval K, operator 2026-10-23 11:10 ET); deletion needs a MAJOR amendment
source: 'PR #2016 (ops/jsonl-retention-20261023)'
summary: Writer-safe archive rotation of oversized append-only JSONL stores (2.3 GB to gz). Deletion is blocked by §24.12,
  the persistent-state never-touch list and §23.14.
phases:
- id: DSN-20261023-jsonl-retention-P1
  title: Rotation (#2016, lane at SHADOW, operator packet after 16:15)
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261023-jsonl-retention-P1-T1
    title: 'OPERATOR: review the JSONL rotation lane contract on #2016 (red until REVIEWED)'
    status: PROPOSED
    areas:
    - operator/contracts/jsonl-rotation
    owner: OPERATOR
  - id: DSN-20261023-jsonl-retention-P1-T2
    title: 'Merge + release #2016 (frees config/lane_registry.json for T-20261023-838c62)'
    status: PROPOSED
    areas:
    - config/ci_gates/jsonl_archive_rotate_20261023.json
    depends_on:
    - DSN-20261023-jsonl-retention-P1-T1
  - id: DSN-20261023-jsonl-retention-P1-T3
    title: 'OPERATOR: run the rotation packet after 16:15 ET (archives the two big health JSONL logs — approval K)'
    status: PROPOSED
    areas:
    - operator/packets/jsonl-rotation
    owner: OPERATOR
    depends_on:
    - DSN-20261023-jsonl-retention-P1-T2
  - id: DSN-20261023-jsonl-retention-P1-T4
    title: Hot-list budget 170s registry/inventory row — board task T-20261023-838c62, waits on P1-T2
    status: PROPOSED
    areas:
    - config/lane_registry.json
    board_task: T-20261023-838c62
- id: DSN-20261023-jsonl-retention-P2
  title: Retention by the disk-hygiene lane rules (enabled:false until the operator flips them; daily after the close, shadow
    first)
  status: HELD
  tasks:
  - id: DSN-20261023-jsonl-retention-P2-T1
    title: 'OPERATOR: log deletion decision — deletion needs a MAJOR AGENTS amendment (§24.12 / never-touch list / §23.14)'
    status: PROPOSED
    areas:
    - operator/decisions/log-deletion
    owner: OPERATOR
- id: DSN-20261023-jsonl-retention-P3
  title: 'Legacy 2026-09-27 archives (1.82 GB): operator may remove by hand'
  status: PROPOSED
---

Backfill 2026-10-23. Approval K is still open: on 2026-10-23 14:11 ET `data/runtime/health_inspector_fixes.jsonl`
(121 MB) and `logs/health_agent_remediation.jsonl` (55 MB) are un-rotated and no archive copy exists.
Dependency: T-20261023-838c62 (hot-list registry row) must wait for P1-T2 because #2016 touches
`config/lane_registry.json`; the task CLI cannot add `depends_on` to an existing task, so it is recorded here.

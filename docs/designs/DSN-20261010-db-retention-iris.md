---
id: DSN-20261010-db-retention-iris
title: DB retention / Iris
status: IN_PROGRESS
approval: approved (operator 2026-10-21 "Approve all leans" D1-D10); D11 HELD
source: ~/n8n-maturity-verification/packets/retention-all-managed/OPERATOR_DECISION.md (outside the repo)
summary: Retention runs nightly on the host (platform-maintenance 01:15, archive-first); Iris never owned it. Stays a host
  job, not n8n.
phases:
- id: DSN-20261010-db-retention-iris-P1
  title: Study (DB_RETENTION_AND_IRIS_STUDY.md)
  status: DONE
- id: DSN-20261010-db-retention-iris-P2
  title: Junk embeddings archived + VACUUM FULL (DB 24.95 -> 15.54 GB)
  status: DONE
- id: DSN-20261010-db-retention-iris-P3
  title: 'Every delete/purge registered, archive-first + tripwire (#1690, #1696, #1701)'
  status: LIVE
- id: DSN-20261010-db-retention-iris-P4
  title: 'Priority rulings D6, D8.2, D7, D5.3, D10 — #1900'
  status: LIVE
- id: DSN-20261010-db-retention-iris-P5
  title: 'Off-box archive copy to Drive (D9) — #1902 via batch #1904; install packet archive-offbox-20261021 DRAFT'
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261010-db-retention-iris-P5-T1
    title: 'OPERATOR: install the archive off-box sync packet (docs/ops/packets/archive-offbox-20261021)'
    status: PROPOSED
    areas:
    - operator/packets/archive-offbox
    owner: OPERATOR
- id: DSN-20261010-db-retention-iris-P6
  title: Remaining leans D1-D5, D8 (non-priority) — verify which are implemented
  status: APPROVED
  tasks:
  - id: DSN-20261010-db-retention-iris-P6-T1
    title: Audit D1-D5/D8 rulings against config/data_retention policy and list the unimplemented ones
    status: PROPOSED
    areas:
    - config/data_retention_policy.json
- id: DSN-20261010-db-retention-iris-P7
  title: D11 new deletion policies
  status: HELD
---

Backfill 2026-10-23. PRs: #1481, #1497, #1570, #1690, #1696, #1701, #1900, #1904 merged.

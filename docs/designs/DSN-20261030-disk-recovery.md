---
id: DSN-20261030-disk-recovery
title: Explain the disk growth and restore accountable cleanup
status: IN_PROGRESS
owner: platform
as_of: 2026-10-30
approval: Operator requested investigation, reclamation and a durable repair in-session; retention expansion and automatic apply remain held for separate review.
summary: Repair misleading measurements and fragile backup receipts, then qualify the release-only reclaim and backup-retention decisions separately.
phases:
- id: DSN-20261030-disk-recovery-P1
  title: Non-destructive reporting and receipt repairs
  status: IN_PROGRESS
  tasks:
  - id: DSN-20261030-disk-recovery-P1-T1
    title: Refresh bounded disk-category measurements without hiding unknown sizes
    status: IN_PROGRESS
    areas:
    - scripts/disk_usage_monitor.py
    - scripts/disk_hygiene.py
    - tests/test_disk_hygiene_20261018.py
  - id: DSN-20261030-disk-recovery-P1-T2
    title: Show backup archive usage and honor the existing live-dump size cap
    status: IN_PROGRESS
    areas:
    - scripts/backup_enforcer.py
    - tests/test_backup_enforcer.py
  - id: DSN-20261030-disk-recovery-P1-T3
    title: Preserve last valid backup receipts and publish the recovery evidence
    status: IN_PROGRESS
    areas:
    - linux_launchers/run_pg_backup.sh
    - scripts/pipelines/run_portfolio_maintenance_pipeline.sh
    - tests/test_portfolio_cadence_tar_rc1_20261021.py
    - docs/ops/DISK_RECOVERY_20261030.md
- id: DSN-20261030-disk-recovery-P2
  title: Operator decisions and production acceptance
  status: HELD
  tasks:
  - id: DSN-20261030-disk-recovery-P2-T1
    title: Review and activate release-only automatic reclaim with complete reference proof
    status: PROPOSED
    owner: OPERATOR
    areas:
    - operator/disk-hygiene-release-only
  - id: DSN-20261030-disk-recovery-P2-T2
    title: Decide backup archive retention after verified recovery coverage
    status: PROPOSED
    owner: OPERATOR
    areas:
    - operator/disk-backup-retention
  - id: DSN-20261030-disk-recovery-P2-T3
    title: Verify resumed database retention and restored disk headroom
    status: PROPOSED
    owner: OPERATOR
    areas:
    - operator/disk-recovery-acceptance
  - id: DSN-20261030-disk-recovery-P2-T4
    title: Make off-box backup success require verified uploaded-object evidence
    status: PROPOSED
    areas:
    - scripts/backup_secrets_state.sh
---

The measured incident and concrete acceptance conditions are in
[the recovery record](../ops/DISK_RECOVERY_20261030.md). These task IDs are registered on the claim board.
P1 changes neither deletion eligibility nor scheduling. P2 remains incomplete until its evidence and
applicable operator decisions exist; this design is not standing cleanup authorization.

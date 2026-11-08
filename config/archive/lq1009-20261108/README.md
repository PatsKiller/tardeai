# Archived lane drafts — lq1009-20261108

LQ-20261107-1009 (Fable audit #15). Each item below was mapped against the one lane manifest
(LaneManifest@v1) by `scripts/ops/lane_artifact_triage.py` and had no lane it could act on, so it was
MOVED here out of its live config file. Nothing was deleted: every archived JSON keeps the full original
entry next to the triage row (manifest state and reason) that decided it.

**Nothing may read this directory.** It is history, not config. `tests/test_lane_artifact_triage_20261108.py`
fails if any file under `scripts/` names `config/archive/`.

To restore an item: copy its `entry` back into the live file and give it a manifest lane first.

Archived at 2026-11-08T18:00:00+00:00.

| file | archived | item | manifest state | why |
|---|---|---|---|---|
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | backup-verify | NEVER_SCHEDULED | manifest lane NEVER_SCHEDULED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | build-symbol-profiles-watchlist | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | catalyst-calibration-monitor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | classify-candidates | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | distributions-enrich | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | fund-technicals-enrich | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | hermes-config-governor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | hermes-learning-outcome-feedback-agent | NEVER_SCHEDULED | manifest lane NEVER_SCHEDULED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | lane-governance-packet-weekly | NEVER_SCHEDULED | manifest lane NEVER_SCHEDULED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | llm-retry-monitor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | market-regime-classifier | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | materialize-income-engine | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | mint-identity-registry | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | n8n-selftest-fail | - | no manifest lane |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | refresh-symbol-cards | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | shadow-batch-generator-at-15-9 | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | storage-watch | NEVER_SCHEDULED | manifest lane NEVER_SCHEDULED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | sync-watchlist-items-to-db | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | trade-ai-restore-drill | NEVER_SCHEDULED | manifest lane NEVER_SCHEDULED: nothing left to act on |
| config/n8n_remediation_catalogue.json | n8n_remediation_catalogue.archived.json | watch-directives-monitor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N1/lane-governance-packet-weekly | NEVER_SCHEDULED | manifest lane NEVER_SCHEDULED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N1/n8n-monitor-trade-ai | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N1/n8n-monitor-dof | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N3/material-change-digest | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N4/llm-retry-monitor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N4/catalyst-calibration-monitor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N4/watch-directives-monitor | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N5/backup-generated-docs | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N5/commit-hermes-daily | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N5/n8n-lab-backup | RETIRED | manifest lane RETIRED: nothing left to act on |
| config/n8n_migration_tranches.json | n8n_migration_tranches.archived.json | N5/n8n-lab-restore-drill | RETIRED | manifest lane RETIRED: nothing left to act on |

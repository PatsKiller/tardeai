# Catalyst momentum engine — cron side of the B8 consolidation (2026-10-22)

Operator-run packet. The 2026-10-11 consolidation (`scripts/run_family_slot.py --family catalyst-momentum-engine`)
declared the lane ACTIVE and the two legacy lines RETIRED in `config/lane_registry.json`, but its crontab install
never happened, so the legacy lines still run and the family line is absent
(`check_registry_runtime_truth`: ACTIVE_CRON_LINE_ABSENT + 2x DECLARED_OFF_CRON_LINE_ACTIVE).

Since then the legacy lines gained `env ALPACA_MODE=paper`. The family's proposal modes now carry it too
(`scripts/lib/family_slot_jobs.py` `CATALYST_PAPER_ENV`); the script refuses unless the served release has it.

    bash apply-operator.sh --preview   # changes nothing
    bash apply-operator.sh             # backup, diff, type APPLY, install, verify against a captured file

Rollback: `crontab <backup path printed by the script>`. Approval: operator 2026-10-22, "yes i approve 'approve all'
(A–L)" (item D, lane-registry truth) — the crontab change itself is the operator's act at the TTY.

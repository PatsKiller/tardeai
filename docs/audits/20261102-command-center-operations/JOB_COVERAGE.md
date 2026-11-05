# Job coverage report

> **Frozen capture: 2026-11-02T18:45:27Z — a snapshot, not current state.** Registry drift is
> reported by `python3 scripts/build_command_center_audit_inventory.py --check`; refresh and
> the snapshot's limits are documented in [inventory/README.md](inventory/README.md).

The exhaustive frozen report is [inventory/coverage.md](inventory/coverage.md).
[687JSON records](inventory/inventory.json), [CSV](inventory/inventory.csv),
[summary/definitions](inventory/summary.json), [five runtime orphans](inventory/runtime_orphans.csv)
and [original hashes](inventory/evidence_manifest.json) are copied byte-for-byte.

| Coverage | All687 | Percent | ACTIVE493 | Percent |
|---|---:|---:|---:|---:|
| Measured |93|13.54%|93|18.86%|
| Partially Measured |391|56.91%|391|79.31%|
| Unmeasured |1|0.15%|1|0.20%|
| Orphaned registry/runtime contradiction |8|1.16%|8|1.62%|
| Disabled |194|28.24%|0|0%|

Measured means schedule evidence or documented nonrecurring semantics plus durable identity-bound
completion with exit code. A failed completion can be Measured. Success, output and diagnostics
are separate dimensions. Disabled combines140retired+32never scheduled+22paused; it does not mean
194host processes were disabled.

The217native unknowns comprise185ACTIVE (37.53% of493) and32never scheduled.75ACTIVEunknown
are due today;110are not. Dividing217by343mixes populations. All103ACTIVE systemd lanes are unknown
to the served reader even though generic metadata exposes timer clocks. This is not proof103daemons stopped.

Original inventory says proposed ticket keys. [Remediation manifest](remediation_manifest.json)
now supplies real repository ticket bindings without rewriting capture history. GitHub Issues is disabled.
No code change is credited with improving this historical snapshot.

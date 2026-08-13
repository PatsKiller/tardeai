# Release Manifest — Investment Office Convergence

> Preliminary stamp (Phase 0). Finalized at release (Phase 11) from the exact merged SHA.
> This manifest pins provenance only; it does **not** authorize live trading or any broker action.

## Pin

| Field | Value |
| --- | --- |
| canonical_source_sha | `0a9b6c415e02dc23d150a020327689044d0aa72b` |
| frontend_build_sha | `3.14+msrnuir0` (ui_version; built 2026-08-13T15:16:02Z) — **no git SHA stamped in `build-meta.json` (gap)** |
| backend_release_sha | `d9b63ed6738731477d4a2f316cd8253c7df859a0` (current production, release `20260812-193650`) |
| migration_head | `2026-08-13_two_way_curation.sql` + `2026-08-13_two_way_curation_p0_surfaced_by.sql` |
| docs_pin | `0a9b6c415e02dc23d150a020327689044d0aa72b` |
| runtime_config_version | TBD (stamp from `config/` head + `ui_version` at release) |
| rollback_sha | `d9b63ed6738731477d4a2f316cd8253c7df859a0` (current production) |

## Authority

- `financial_authority: READ_ONLY_ADVISORY`
- `broker_write_paths_added: 0` (branch diff contains only banned-list/assertion strings for order/stops; no order submission paths)
- `unguarded_provider_paths_added: 0` (to be re-verified in Phase 11 safety scan)

## Lineage

```
main 7f622c2f  ->  feature/advisory-desk-v1 324c6171 (+91)  ->  feat/two-way-watchlist-curation 0a9b6c41 (+14)
  ==  feature/investment-office-convergence-v1 0a9b6c41  (+105 over main)
```

## Notes

- Production (`d9b63ed6`) currently runs the advisory/two-way lineage, **105 commits ahead of `main`**. Convergence target is to collapse this to one canonical release lineage.
- Frontend repo build (`3.14+msrnuir0`, 2026-08-13) is **newer** than the deployed backend release (`20260812-193650`). Reconcile at release.

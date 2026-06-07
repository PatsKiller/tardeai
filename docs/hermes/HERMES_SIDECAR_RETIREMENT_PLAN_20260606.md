# Hermes Sidecar Retirement Plan — 2026-06-06

Staged, reversible. **No deletion or renaming in this task.** Stage D requires explicit operator approval.

## Stage A — Preserve (DONE, verified)
- Sidecar full snapshot: `backups/hermes_sidecar_snapshot_20260606_2007.tgz` ✓
- Sidecar file inventory under `docs/hermes/` ✓
- SOULs archived: `~/.hermes/migration_from_tradeai_sidecar_20260606/souls/` (6 files) ✓

## Stage B — Curated Migration (operator-review-gated; NOT executed)
Migrate ONLY reviewed content:
- safe SOUL intent · safe profile rules · safe config intent · curated skills (if reviewed) ·
  durable memories (if reviewed) · documentation references.

DO NOT migrate:
- `.env` · secrets · request dumps · old logs · gateway pid/state files · lock files · kanban DB ·
  response-store DB · state DB · WAL/SHM files · stale qwen references · the generic
  "execute actions via your tools" instruction into tradeai/tradeai12b.

## Stage C — Validate Global Profiles
```
hermes --version          # v0.16.0 (verified)
hermes profile list       # 5 profiles (verified)
hermes chat               # interactive (operator)
tradeai chat              # interactive (operator)
tradeai12b chat           # interactive (operator)
tradeai tools list        # all disabled (verified)
tradeai12b tools list     # all disabled (verified)
```
Non-interactive checks verified this session; interactive `chat` validations are operator-run.

## Stage D — Retire, DO NOT DELETE (operator approval required; NOT done here)
- `mv hermes_sidecar/.hermes hermes_sidecar/.hermes.RETIRED_<timestamp>`
- `mv hermes_sidecar/install hermes_sidecar/install.RETIRED_<timestamp>`
- replace `run_hermes_readonly.sh` with a stub → `exec tradeai chat "$@"`
- replace `run_hermes_gateway.sh` with a stub warning the gateway is retired
- **No `rm -rf`** of retired dirs in this task or Stage D.

Wrapper stubs may be PREPARED (drafted in docs) but NOT installed without operator approval.

## Rollback
Sidecar remains fully functional until Stage D. Restore from the snapshot tarball if needed. All steps reversible.

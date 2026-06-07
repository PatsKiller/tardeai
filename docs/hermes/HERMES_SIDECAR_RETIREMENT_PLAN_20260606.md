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

---
## Status update (2026-06-06, Phase A continuation)
- Stage A (preserve): **DONE** — added pre-retire backup `backups/hermes_sidecar_PRE_RETIRE_20260606_2128.tgz`
  (118M) + `docs/hermes/HERMES_SIDECAR_PRE_RETIRE_FILE_INVENTORY_20260606_2128.txt` (107 files).
- Stage B (curated migration): documented in `HERMES_CURATED_MIGRATION_INVENTORY_20260606.md`; no unsafe/
  runtime content copied into canonical profiles.
- Stage C (validate): **PASS** — profiles correct, tradeai/tradeai12b tools disabled (0/25), canaries pass
  (gemma3:4b + gemma3:12b-ctx4k), unsafe phrase absent.
- Stage D (rename-retire): **PREPARED, NOT EXECUTED** — retirement stubs drafted under `docs/hermes/stubs/`
  (`run_hermes_readonly.sh.retired.stub`, `run_hermes_gateway.sh.retired.stub`). The sidecar is **still in
  place and functional**; rename-retire awaits explicit operator approval token
  `APPROVE_RENAME_RETIRE_HERMES_SIDECAR`. No deletion will ever occur (rename-only).

---
## Stage D EXECUTED (2026-06-06, operator-approved)
Operator approval token: APPROVE_RENAME_RETIRE_HERMES_SIDECAR. **Rename-retire only — no deletion.**
- Final pre-rename backup: `backups/hermes_sidecar_FINAL_BEFORE_RENAME_RETIRE_20260606_2140.tgz` (118M) +
  inventory `docs/hermes/HERMES_SIDECAR_FINAL_BEFORE_RENAME_RETIRE_FILE_INVENTORY_20260606_2140.txt` (107 files).
- Renamed: `hermes_sidecar/.hermes` → `hermes_sidecar/.hermes.RETIRED_20260606_2140`;
  `hermes_sidecar/install` → `hermes_sidecar/install.RETIRED_20260606_2140`.
- Wrappers `run_hermes_readonly.sh` + `run_hermes_gateway.sh` replaced with retirement stubs (print message, exit 2).
- Validation PASS: global hermes v0.16.0 + profiles intact; active sidecar dirs gone; retired dirs present.
- Rollback preserved via the two backup tarballs + the retired directories (nothing deleted).
- Canonical commands: `hermes chat`, `tradeai chat`, `tradeai12b chat`, `dev chat`, `serverops chat`.
- NOT enabled: gateway, Telegram, Discord, Codex, serverops, cron, systemd.

## Git Hygiene Cleanup

After Stage D rename-retire, previously tracked runtime/state files under `hermes_sidecar/.hermes/*` were removed from Git tracking. The files were not deleted from disk; they remain preserved in the `.RETIRED_*` directories and backup tarballs. Ignore rules were added so Hermes runtime state, SQLite databases, request dumps, lock files, gateway state, and retired sidecar directories are not accidentally tracked again.

### Gateway found still-enabled — now stopped/disabled (20260606_2154)
During git-hygiene cleanup, the old sidecar gateway was discovered STILL RUNNING and systemd-enabled
(`hermes-gateway.service`, PID 2392635, ~7 days, `gateway run --accept-hooks`) — it had recreated
`hermes_sidecar/.hermes` after the 21:40 rename. Operator-approved action: `systemctl --user stop` +
`disable hermes-gateway.service` (now is-active=failed/stopped, is-enabled=disabled); no other process
remains. The operator's interactive `hermes chat` (PID 3549046) was deliberately preserved. The recreated
runtime dir was re-retired to `hermes_sidecar/.hermes.RETIRED_20260606_2154`. No deletion; all retired dirs +
backups preserved. Gateway/Telegram/Discord/Codex/cron remain OFF.

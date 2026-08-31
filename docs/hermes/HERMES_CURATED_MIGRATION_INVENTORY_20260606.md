# Hermes Curated Migration Inventory — 2026-06-06

Status:      ACTIVE
as_of:       2026-06-06T22:07:57-04:00
Measured at: efcc51365 / not measured

Curated record of what moved from the Trade-AI sidecar into the global Hermes install, what was
intentionally left behind, and what remains as rollback evidence. Verified live on ms01.

## Preserved (backups / archive)
- Pre-retire sidecar backup: `backups/hermes_sidecar_PRE_RETIRE_20260606_2128.tgz` (118M, full .hermes+install+wrappers).
- Earlier snapshot: `backups/hermes_sidecar_snapshot_20260606_2007.tgz`.
- File inventory: `docs/hermes/HERMES_SIDECAR_PRE_RETIRE_FILE_INVENTORY_20260606_2128.txt` (107 files).
- SOUL archive: `~/.hermes/migration_from_tradeai_sidecar_20260606/souls/` (6 SOULs: global_default, tradeai,
  tradeai12b, dev, serverops before-merge + sidecar_tradeai source).

## Migrated (curated intent only)
- Safe SOUL **intent** → re-authored per-profile SOULs (default + tradeai/tradeai12b/dev/serverops), each
  with explicit safety boundaries (no orders/stops/proposals/secrets) — not a raw copy of the sidecar SOUL.
- Safe config **intent** → provider=custom → local Ollama, gemma3:4b (default/tradeai), gemma3:12b-ctx4k
  (tradeai12b), tools disabled.
- Documentation references (the four HERMES_*_20260606 docs + index + Reference Architecture docx section).

## Intentionally NOT migrated (runtime junk / unsafe)
- `.env` files, secrets, API keys, broker/Telegram tokens
- request dumps, old logs
- gateway pid/state files, lock files
- `kanban.db`, `response_store.db`, `state.db`, WAL/SHM files
- stale `qwen3:14b` references (confirmed absent from live model inventory)
- the generic "execute actions via your tools" instruction — deliberately excluded from tradeai/tradeai12b
  (verified absent; only safe negated boundaries present)

## Current profile SOULs (live)
| Profile | SOUL present | Model | Tools |
|---------|-------------|-------|-------|
| default | ✓ (~/.hermes/SOUL.md) | gemma3:4b | disabled |
| tradeai | ✓ | gemma3:4b | disabled (0/25) |
| tradeai12b | ✓ | gemma3:12b-ctx4k | disabled (0/25) |
| dev | ✓ | — (unconfigured) | future |
| serverops | ✓ | — (unconfigured) | future |

## Remaining in sidecar as rollback evidence
`hermes_sidecar/.hermes` + `hermes_sidecar/install` (v0.15.2) + wrapper scripts — retained, NOT canonical.
Retirement is rename-not-delete (Stage D), operator-approval-gated. Nothing deleted.

## Canary status (live, 2026-06-06)
gemma3:4b → `HERMES_4B_STILL_OK` (/api/generate) ✓ · gemma3:12b-ctx4k → `HERMES_12B_CTX4K_V1_OK` (/v1/chat) ✓.
12B remains experimental (tradeai12b only); not promoted.

---
## Update (2026-06-06): Stage D executed
Sidecar rename-retired to hermes_sidecar/.hermes.RETIRED_20260606_2140 + install.RETIRED_20260606_2140 (no deletion). Rollback via backups/hermes_sidecar_FINAL_BEFORE_RENAME_RETIRE_20260606_2140.tgz + retired dirs.

---
## Status path repoint (2026-06-06)
api_v2.py + check_system_versions.sh repointed from retired sidecar to global Hermes (~/.local/share/hermes-agent-venv, ~/.hermes). Disabled hermes-gateway.service unit file retained as audit artifact (not removed).

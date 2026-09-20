# APPROVED — code-mirror Drive cron + apply (AGENTS.md §9.3 / §17)

```
Status: APPROVED
Effective-Date: 2026-09-20
as_of: 2026-09-20T14:40:00-04:00
Measured at: hub checkout; CURRENT pin resolved; dry-run of sync_code_mirror_to_drive.sh
Canonical repo path: docs/ops/PROPOSED_INSTALL_CODE_MIRROR_DRIVE_CRON_2026-09-20.md
Authority: propose-and-stop — installing a production crontab entry is operator-only
See also: scripts/sync_code_mirror_to_drive.sh;
  config/lane_registry.json lane_id=code-mirror-drive-sync (NEVER_SCHEDULED);
  existing docs sync at :05 (sync-docs-to-drive.sh)
```

## What this is

Hourly one-way mirror of **local git (hub)** and **Trade AI production code (CURRENT)**
into Google Drive folder `Trade_AI_Docs_v2/code_mirror/`.

Not a second docs sync. The docs sync already runs at `:05`. This lane archives **code**.

| artifact on Drive | source | method |
|---|---|---|
| `hub_git_snapshot.tar.gz` | `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | `git archive HEAD` (tracked only) |
| `current_production_snapshot.tar.gz` | `~/trade-ai-releases/portfolio-server/CURRENT` | tar of release tree |
| `CODE_MIRROR_STATUS.json` | derived | as_of, SHAs, sizes, sha256 |

Stable filenames + delete-before-upload (same pattern as `claude_memory_backup.tar.gz`).

## Why archives, not per-file

The hub checkout is ~26GB / ~900k files once data/venv/untracked are counted.
Git-tracked alone is ~8.7k files / ~28MB gzipped — practical for hourly Drive upload.
Per-file sync of the whole tree would thrash the Drive API and collide with the docs job.

## Never synced

`.env`, `.env.*`, `*.pem`, `*.key`, `data/`, `logs/`, `.venv`, `node_modules`,
`dist/`, path segments matching `credentials|secret|password`, and (hub) anything
not in `git ls-files`. Script refuses if `.env` is tracked.

## Dry-run proof (no Drive mutation)

`gog drive upload --dry-run` is **not** used (gog v0.12 uploads anyway —
`docs/ops/DRIVE_MUTATION_SAFETY.md`). Local `--dry-run` builds archives and writes
`~/.local/state/code-mirror-drive-sync-last.json` only.

`[VERIFIED]` 2026-09-20T18:39:17Z — dry-run exit 0, `status=dry_run_ok`, `upload=null`:

```text
hub archive: 28M (28870402 bytes) sha256=144f81a04d…
current archive: 30M (30862092 bytes) sha256=7e9819b66f…
hub_head: 348d4fdba9d9f1738519e3253709fa420925482f
current_source_commit: 5b7e24c95f29b94cf1ce2f3366de1f806ec93767
CURRENT resolved: …/5b7e24c95-main-exact-phase2-20260920-114233
```

Re-run:

```bash
bash scripts/sync_code_mirror_to_drive.sh --dry-run
```

## Exact operator decision ask

Reply with one of:

1. **APPROVE_INSTALL_CODE_MIRROR_DRIVE_CRON** — install crontab + flip lane to ACTIVE:

```bash
# 1) Optional first live upload (creates Trade_AI_Docs_v2/code_mirror/ if needed)
bash /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/sync_code_mirror_to_drive.sh --apply

# 2) Crontab line (offset from docs sync at :05; separate flock)
# 35 * * * * bash /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/safe_flock.sh /tmp/code_mirror_drive_sync.lock bash /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/sync_code_mirror_to_drive.sh --apply >> /home/johnclaw/logs/code-mirror-drive-sync.log 2>&1

# 3) After install: set lane state ACTIVE (remove NEVER_SCHEDULED / state_reason / state_since)
#    in config/lane_registry.json for lane_id=code-mirror-drive-sync
```

2. **APPROVE_APPLY_ONCE** — run `--apply` once now; defer hourly cron.
3. **DEFER** / **REJECT** — leave NEVER_SCHEDULED; document reason on this file.

No agent may edit the live crontab or run `--apply` without an APPROVE_* token.

## Residual

- First `--apply` creates Drive folder `code_mirror` under Trade_AI_Docs_v2
  (`1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR`) if absent.
- Hub archive is **HEAD of the hub checkout**, which may be detached / feature-branch —
  status JSON records `hub_head` and `current_source_commit` so Drive readers can see drift.
- Docs continue on the existing `:05` job; do not fold code into that job.

---

## Operator decision (recorded)

```
token: APPROVE_INSTALL_CODE_MIRROR_DRIVE_CRON + APPROVE_APPLY_ONCE
decided_on: 2026-09-20T15:10:00-04:00
reference: Grok session — operator chose "Push + promote CURRENT + approve code-mirror apply"
effect: install hourly cron; run --apply once; flip lane code-mirror-drive-sync to ACTIVE
```

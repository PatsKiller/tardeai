# Drive mutation safety (gog v0.12.x)

**Status:** ACTIVE for operational Drive writes  
**Campaign:** m2-canary-20260907 Lane T  
**Tool observed:** `gog` v0.12.0 — `drive upload -n/--dry-run` claims “Do not make changes” but is **not trusted** as a dry-run proof for this version (SOAK_RUNBOOK.md §8; live upload observed despite `-n`).

## Rules

1. **Do not use `gog drive … -n` / `--dry-run` as evidence of a dry run.** Treat it as mutating (or at least untrusted). Lane T wrapper refuses these flags on mutation verbs.
2. **Separate plan from execute.**
   - `python3 scripts/gog_drive_safe.py plan <file> --parent <id>` — read-only; never invokes `gog`.
   - `python3 scripts/gog_drive_safe.py execute <file> --account … --parent <id> --i-understand-this-mutates-drive` — real upload with pre-write local hash and **mandatory post-write remote hash** verification (download + sha256).
3. **Explicit target identity required:** `--parent` (create) or `--replace` (replace by file id).
4. **Pre-write:** record local path, bytes, sha256.  
   **Post-write:** remote readback must return `sha256`/`content_sha256`; compare; fail closed if missing or mismatched. Local-only “hash match” is refused.
5. **Prohibit experimental delete dry-runs** against real Drive files (`gog drive delete|rm|trash -n`). Unit tests may exercise the refusal with synthetic ids only — never against a live file.
6. **Tests must not perform Drive mutations.** Negative controls use fake runners/readbacks.

## Wrapper

```bash
# Plan only
python3 scripts/gog_drive_safe.py plan ./report.md --parent "$FOLDER_ID" --account john@jwwhiting.com

# Execute (mutates Drive; requires remote hash verification)
python3 scripts/gog_drive_safe.py execute ./report.md \
  --account john@jwwhiting.com --parent "$FOLDER_ID" \
  --i-understand-this-mutates-drive
```

Library: `scripts/lib/drive_mutation_safety.py`.

## Legacy scripts

`scripts/sync-docs-to-drive.sh` and similar still call `gog drive upload` directly. New work must use the wrapper. Migrating legacy sync scripts is out of Lane T scope; document the risk until migrated.

## Governance

An `AGENTS.md` amendment covering Drive dry-run policy is proposed via Shared File Request (not edited in-lane). Command Center maturity truth / `control_plane_api.py` wiring is also SFR-only while those paths remain integration-owned.

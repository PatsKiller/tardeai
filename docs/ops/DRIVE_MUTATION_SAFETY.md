# Drive mutation safety (gog v0.12.x)

**Status:** ACTIVE for operational Drive writes  
**Campaign:** m2-canary-20260908 Lane T  
**Tool observed:** `gog` v0.12.0 — `drive upload -n/--dry-run` claims “Do not make changes” but is **not trusted** as a dry-run proof for this version.

## Rules

1. **Do not use `gog drive … -n` / `--dry-run` as evidence of a dry run.** Treat it as mutating (or at least untrusted). Lane T wrapper refuses these flags on mutation verbs.
2. **Separate plan from execute.**
   - `python3 scripts/gog_drive_safe.py plan <file> --parent <id>` — read-only; never invokes `gog`.
   - `python3 scripts/gog_drive_safe.py execute <file> --account … --parent <id> --i-understand-this-mutates-drive` — real upload with pre/post hash checks.
3. **Explicit target identity required:** `--parent` (create) or `--replace` (replace by file id).
4. **Pre-write:** record local path, bytes, sha256.  
   **Post-write:** read back metadata/hash; compare; fail on mismatch.
5. **Prohibit experimental delete dry-runs** against real Drive files (`gog drive delete|rm|trash -n`).
6. **Tests must not perform Drive mutations.** Negative controls use fake runners.

## Wrapper

```bash
# Plan only
python3 scripts/gog_drive_safe.py plan ./report.md --parent "$FOLDER_ID" --account john@jwwhiting.com

# Execute (mutates Drive)
python3 scripts/gog_drive_safe.py execute ./report.md \
  --account john@jwwhiting.com --parent "$FOLDER_ID" \
  --i-understand-this-mutates-drive
```

Library: `scripts/lib/drive_mutation_safety.py`.

## Legacy scripts

`scripts/sync-docs-to-drive.sh` and similar still call `gog drive upload` directly. New work must use the wrapper. Migrating legacy sync scripts is out of Lane T scope; document the risk until migrated.

## Governance

An `AGENTS.md` amendment is proposed separately — see  
`docs/ops/AGENTS_MD_AMENDMENT_DRIVE_DRY_RUN_PROPOSED.md`.  
Do not silently edit `AGENTS.md` from this lane.

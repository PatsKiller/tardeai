# Archive off-box sync to Google Drive — install packet (2026-10-21)

Status:      DRAFT (proposed; nothing installed)
as_of:       2026-10-21T13:00:00-04:00
Measured at: branch feat/archive-offbox-drive-20261021 (on a6ac0ebbe) / live pin not changed by this packet

**Decision.** On 2026-10-21 the operator ruled D9 = (a): copy the retention archives off-box to Google Drive,
using the existing Drive path.

**What it protects.** `<state>/archive/` (`/home/johnclaw/trade-ai-releases/persistent-state/archive`). It
held 4,765 files and about 0.95 GiB on 2026-10-21, and grows by up to about 2 GB a month. It is on the same
disk as the database.

**The copier.** `scripts/archive_offbox_sync.py`. Its design is in
[`docs/runbooks/DB_RETENTION.md` §5.1](../../../runbooks/DB_RETENTION.md). In short:
- It uses the `scripts/backup_secrets_state.sh` mechanism: `gog drive`, gpg AES256, and the credential files
  by path only.
- It is incremental by manifest and verifies each upload before recording it.
- Each run is capped at 1 GiB and 1500 files, and the next run resumes.
- It never deletes, locally or on Drive.
- It is a dry run unless given `--apply`.

**Why a host job and not n8n.** It touches credentials and egress.

## Files

| file | purpose |
|---|---|
| `tradeai-archive-offbox-sync.service` | oneshot; runs CURRENT's `scripts/archive_offbox_sync.py --apply`. Nice 10, idle I/O, 3 h timeout. Logs to `persistent-state/logs/archive_offbox_sync.log` |
| `tradeai-archive-offbox-sync.timer` | daily 03:30 America/New_York, `Persistent=true`, 2 min jitter. Runs after the 01:15 retention step and the 02:30 backup cadence |
| `install.sh` | **dry run by default**. `--apply` copies both units to `~/.config/systemd/user`, backing up any differing copy first, then reads them back, runs `daemon-reload` and `enable --now` on the timer |

A new systemd entry is operator-only (AGENTS.md §17). The agent that built this packet installed nothing,
uploaded nothing and ran no `--apply`.

## Dry run (read-only, quoted)

The run was on 2026-10-21 against the live state root:

```
$ .venv/bin/python scripts/archive_offbox_sync.py
[archive-offbox-sync] DRY RUN — nothing uploaded, nothing written. archive=/home/johnclaw/trade-ai-releases/persistent-state/archive
[archive-offbox-sync] already uploaded: 0 file(s); pending: 4757 file(s), 1022354984 bytes (0.952 GiB); new 4757, changed 0
[archive-offbox-sync]   abandoned-branches-20261009              72 file(s)      235805600 bytes
[archive-offbox-sync]   comms_lifecycle                        1580 file(s)       34039505 bytes
[archive-offbox-sync]   db_retention                           2990 file(s)      714751422 bytes
[archive-offbox-sync]   db_trim                                  35 file(s)        8786683 bytes
[archive-offbox-sync]   file_prune                               74 file(s)       28969066 bytes
[archive-offbox-sync]   retired-units-20261009                    6 file(s)           2708 bytes
[archive-offbox-sync] would upload this run (bound 1073741824 bytes / 1500 files): 1500 file(s), 269629097 bytes (0.251 GiB); deferred to later runs: 3257
[archive-offbox-sync] skipped: {'too_new': 8}
```

The run then listed the first 10 paths it would upload, for example
`abandoned-branches-20261009/abandoned-branches-20261009.bundle (235572799 B, new) ->
Trade_AI_Backups/archive/abandoned-branches-20261009/202610/abandoned-branches-20261009.bundle.gpg`. After the
run, neither `data/runtime/archive_offbox_manifest.json` nor `data/runtime/archive-offbox-sync_last.json`
existed.

`install.sh` was also dry-run against a scratch `SYSTEMD_USER_DIR`. It printed `would install` for both
units, then a WARN that CURRENT does not have the script yet (step 0), then `DRY RUN: nothing written`.

## Operator steps

0. **Deploy.** Merge, then release. The unit runs `CURRENT/scripts/archive_offbox_sync.py`, and
   `install.sh --apply` refuses if that file is not there.
1. **Dry run from the release.**
   `cd ~/trade-ai-releases/portfolio-server/CURRENT && ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/archive_offbox_sync.py`
2. **Observed first apply, three files.** The JSON shape of `gog drive get` has not been seen by this code
   yet:
   `... scripts/archive_offbox_sync.py --apply --max-files 3`
   Then check three things:
   - `data/runtime/archive-offbox-sync_last.json` shows `status: ok` and `produced_count: 3`.
   - The manifest entries show `verified_by: size+md5` or `size`.
   - The three `.gpg` files are in Drive under `Trade_AI_Backups/archive/abandoned-branches-20261009/202610/`.

   If the receipt shows `failures[].stage == "verify"`, nothing was recorded. Report it; do not install the
   timer.
3. **Restore check, one file.**
   `gog drive download <drive_file_id>`, then
   `gpg --batch --passphrase-file ~/.openclaw/credentials/env_data_backup.pass -d <file>.gpg | sha256sum`.
   The hash must equal the manifest `sha256`.
4. **Install the timer.**
   `bash docs/ops/packets/archive-offbox-20261021/install.sh` (dry run), then the same command with `--apply`.
   After that, flip the `archive-offbox-sync` row in `config/lane_registry.json` to `ACTIVE`, with
   `state_since` set to the install date. `check_lane_registry.py --state-drift` flags the row until then.
5. **Watch.** Check the receipt's `ok_at` each morning. The backlog of about 4,757 files drains in about four
   nightly runs.

**Rollback.** `systemctl --user disable --now tradeai-archive-offbox-sync.timer`. This removes nothing. The
manifest and the Drive copies stay.

## Open (not in scope)

- **Drive retention for the copies.** None is set: this lane never prunes Drive. Space on Drive is the
  operator's call.
- **Freeing local space.** Deleting a local archive after it is copied off-box needs a separate operator
  grant (§0 rule 6, §17).
- **The rest of `persistent-state`.** Off-box backup of the other stores (AGENTS.md §18) is still a separate
  decision.
- **Content of `abandoned-branches-20261009`.** It includes worktree patches. They go to the operator's own
  Drive gpg-encrypted, the same class as the `data` backup. If that is not wanted, add `--area` flags to the
  unit's ExecStart (repeatable; an include list) naming only the areas to copy.

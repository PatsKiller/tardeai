# Operator-approval packet — archive off-box sync to Google Drive (D9 / P5)

Design-Task: DSN-20261010-db-retention-iris-P5 (install packet `archive-offbox-20261021`)
Status: PROPOSED — nothing installed, nothing uploaded; this packet is for operator approval only
as_of: 2026-10-30
Measured at: main `f6023b931` (packet files `README.md`, `install.sh`, `tradeai-archive-offbox-sync.service`,
  `tradeai-archive-offbox-sync.timer`; copier `scripts/archive_offbox_sync.py` present in-tree)
Authority: AGENTS.md §17 (new systemd entry, off-box backup funding §18), §0 rule 6, §24.12
See also: `README.md` (mechanism + operator steps), `docs/runbooks/DB_RETENTION.md` §5.1

## Plain-English proposal

**What.** Copy the retention archives off-box to the operator's Google Drive so a disk failure on the host
does not also lose the only archive copy. Today `<state>/archive/` lives on the same disk as the database.

**How (in one sentence).** A daily host timer (03:30 ET, after the 01:15 retention step and 02:30 backup
cadence) runs `scripts/archive_offbox_sync.py --apply`, which incrementally gpg-AES256-encrypts and uploads
the archive tree to `Trade_AI_Backups/archive/` on Drive, verifying each object before recording it.

**Safety rails.** It never deletes — locally or on Drive. Each run is capped at 1 GiB / 1500 files and the
next run resumes the backlog. It reuses the existing `gog drive` + gpg mechanism (`backup_secrets_state.sh`),
referencing credential files by path only. It is dry-run by default; `--apply` is required for any upload.

**Why a host job, not n8n.** It touches credentials and egress, which stay on the host path, not the n8n
executor.

## Dry-run preview (read-only, quoted from the packet README, as_of 2026-10-21)

```
$ .venv/bin/python scripts/archive_offbox_sync.py
[archive-offbox-sync] DRY RUN — nothing uploaded, nothing written. archive=~/trade-ai-releases/persistent-state/archive
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

This is a historical read-only run. The operator's first step (README step 1) re-runs this dry-run from the
served release after merge/deploy; a fresh run was **not** executed by this packet (it can touch `gog` Drive
credentials/egress and is left to the operator).

## Operator-input data this packet cannot compute (stated, not assumed)

- **Off-box size / Drive quota:** the archive was ≈0.95 GiB on 2026-10-21 and grows up to ≈2 GB/month
  (config `archive_growth_cap_gb_month`); current Drive quota/headroom is not visible from this box and is
  operator input.
- **Off-box cost:** Drive storage is the operator's funded plan; cost of the incremental growth is not
  computable here.
- **Drive retention for the copies:** none is set; whether/how to age Drive copies is an operator decision
  (open in `README.md`).
- **The install itself (P5-T1):** `bash install.sh --apply` installs a new systemd unit + timer — §17
  operator-only. This packet performs **no** install, upload, archive, or deletion.

## Approval token / next step

This packet is a proposal; the operator's install decision (P5-T1) and the off-box size/cost inputs above are
required before any `--apply`. Nothing here is executed by the authoring agent.

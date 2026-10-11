# DB retention — owners, archive + tripwire, grants

Status:      ACTIVE
as_of:       2026-10-11T09:30:00-04:00
Measured at: e24ccd6c5 (branch n8nmat/retention-hardening) / live pin not changed by this document

Source studies: `~/n8n-maturity-verification/DB_RETENTION_AND_IRIS_STUDY.md` (2026-10-10) and
`OVERNIGHT_REPORT_20261011.md`, section "DB retention" (findings 1, 4 and 6). This runbook covers the
retention engine as it stands after the 2026-10-11 hardening. It does not cover the Iris "librarian"
persona. Retention was never part of Iris's implementation (study §3).

## 1. Who deletes what

| Job | Scheduler (read-only check, 2026-10-11) | Scope | Archives? |
|---|---|---|---|
| `scripts/db_retention.py` | systemd `tradeai-platform-maintenance-nightly.timer` 01:15, which runs `CURRENT/scripts/pipelines/run_platform_maintenance_pipeline.sh` step `db_retention` (`add_step db_retention 30m /tmp/db_retention.lock …`). It has **no crontab line**: `crontab -l` has only a comment that mentions it. | Every DELETE and ARCHIVE_THEN_DELETE row of `config/data_retention_policy.json`, plus four file globs | ARCHIVE_THEN_DELETE rows always. DELETE rows only when `archive_first: true` is set (§3). |
| `scripts/run_hermes_librarian_retention.py --apply` → `scripts/lib/hermes_librarian/retention.py` | systemd `hermes-librarian-retention.timer` 05:10 (+≤180 s). The service `cd`s into CURRENT. It has **no crontab line**. | `hermes_research_intelligence` lifecycle, failed `hermes_embedding_queue` rows, orphan `content_embeddings` (news and hermes_research) | no |
| `scripts/db_trim.py --apply` | operator-run only | duplicate indexes, backup tables and schemas, row trims | yes: `archive/db_trim/<stamp>/` plus `TRIPWIRE.jsonl` |

**The `content_embeddings` 90-day age rail has one owner: `db_retention`.** Until 2026-10-11, both
jobs ran a 90-day hard DELETE on this table, and neither archived. The librarian's `purge_by_age`
step now defers to db_retention. It runs no DELETE and writes this pointer line to
`logs/hermes_librarian_retention.log`:

```
hermes-librarian retention: content_embeddings purge_by_age DEFERRED to db_retention (config/data_retention_policy.json row content_embeddings; …)
```

- **Control:** `config/hermes_librarian_policy.yaml`, key `content_embeddings.max_age_owner`. The
  default is `db_retention`.
- **Rollback:** set the key to `librarian` to restore the old DELETE.
- **Orphan purges stay with the librarian.** They are a different predicate: the source row is gone.

## 2. Archive + tripwire (AGENTS.md §0 rule 6)

Every archive file written by db_retention gets three things, all **before** the DELETE:

- the `.jsonl.gz` file itself, at `<state>/archive/db_retention/<table>/…`;
- a sha256 manifest (`RetentionArchiveManifest@v1`);
- a tripwire line in `<state>/archive/db_retention/<table>/TRIPWIRE.jsonl` (`RetentionArchiveTripwire@v1`).

**Write path.** Every archive path goes through `scripts/lib/retention_archive.write_manifest`. That
covers the nightly `archive_rows`, the verified batches for source windows and the junk purge. If the
tripwire line cannot be written, the batch rolls back and nothing is deleted.

**Reader.** `scripts/lib/retention_tripwire.py` reads the tripwire files. `scripts/report_db_hygiene.py`
calls it every night (platform-maintenance step 11). It also reads `archive/db_trim/TRIPWIRE.jsonl`,
which nothing read before this change. It adds these findings:

| Code | Severity | Fires when |
|---|---|---|
| `ARCHIVE_TRIPWIRE` | P1 | One of these names `archive/db_retention` or `archive/db_trim`: a file under `scripts/`, `config/` or `linux_launchers/`, an uncommented user-crontab line, or a user systemd `.service` unit. Allowlisted (they write or describe the archive, never read it back): `db_retention.py`, `db_trim.py`, `report_db_hygiene.py`, `lib/retention_archive.py`, `lib/retention_tripwire.py`, `config/data_retention_policy.json`, `config/lane_registry.json`. |
| `ARCHIVE_MISSING` | P2 | A tripwire record names an archive file (or db_trim dump / DDL file) that no longer exists. |
| `TRIPWIRE_UNREADABLE` | P3 (P2 if the reader itself fails) | A tripwire line does not parse. |

These findings go through the existing chain, so no new scheduler or sender was added:

1. `db_hygiene_last.json`
2. `scripts/n8n_incident_fanin.py` (source `db_hygiene`) opens an incident.
3. `scripts/n8n_siem_bridge.py` writes a `system_health_events` row.

A P1 or P2 finding also makes the hygiene lane exit 1.

**Limits.**
- Detection is by reference: it catches a reader that names the path. It does not catch one that
  builds the path from parts at runtime.
- Access times are not used, because the nightly pg_dump and the Drive sync read the state tree.
- The 48 `content_embeddings` junk-purge archives from 2026-10-11 were written before tripwire
  records existed. The reference scan covers their directory. `ARCHIVE_MISSING` cannot, because
  there are no records for them.
- Backfilling those records is a durable write to persistent-state. It needs an operator-approved
  `state-write` grant and has not been done.

**Read-only check (2026-10-11, live state root, this branch's tree, live crontab and units).**
- `tripwire files`: `archive/db_trim/TRIPWIRE.jsonl`, 46 records, 0 unreadable.
- Findings: **0**.

## 3. `content_embeddings`: archive-first switch (`archive_first`)

The registry row `content_embeddings` (class `DELETE`, 90 d) has `"archive_first": false`.

- `false` (the default) keeps the inherited hard DELETE.
- `true` sends the same row through the ARCHIVE_THEN_DELETE path: archive, manifest and tripwire,
  and the delete runs only if the archived count equals the matching count.
- db_retention runs from CURRENT and reads CURRENT's registry. Flipping the flag in a PR therefore
  **changes nothing live until a release ships it**.
- The flag is allowed only on DELETE rows. `scripts/check_retention_policy.py` refuses a non-boolean
  value, and refuses the flag on any other class.

## 4. Grants for destructive one-time modes

`db_retention.py --junk-fused-signal-embeddings --apply` requires the variable
`TRADEAI_DB_WRITE_GRANT=<grant id>`. Accepted forms:

- the 32-hex `grant_id` of the **active** `db-write` grant in the guard ledger
  (`$GUARD_APPROVALS_DIR`, default `~/.cursor/approvals`);
- a prefix of that id at least 12 hex characters long. Operators quote 16, e.g. `c45f5cc126cd1d7c`.

**How it is checked.** `scripts/lib/db_write_grant.py` does a read-only `ledger_list` peek, the same
way `guard_push_auth` checks `git-push`. It never consumes a use.

**Refusals.** It refuses, with exit 2 and before opening a DB connection, when the id is:
- unset or malformed;
- not matching the active db-write grant;
- presented while the ledger is missing or corrupt;
- presented while no db-write grant is active.

**Receipt.** The verdict, including the full grant id and the grant's reason, is written under
`grant` in `archive/db_retention/content_embeddings/receipts/<stamp>-junk_fused_signal.json`.

**Not affected.**
- The dry run (no `--apply`) needs no grant.
- The nightly registry run takes no flag and needs no grant.

```
python3 scripts/db_retention.py --junk-fused-signal-embeddings                 # dry run, quote it
TRADEAI_DB_WRITE_GRANT=<id> python3 scripts/db_retention.py --junk-fused-signal-embeddings --apply
```

## 5. Still open (not changed here)

- The orphan purges in the librarian and the 96 DELETE-class registry rows still hard-delete without
  an archive. The operator decision of 2026-09-14 ("retention may keep hard-deleting") stands.
- `FILE_PRUNE` in db_retention `unlink()`s files with no archive.
- Off-box archive copies are an open §17 decision. The archive sits on the same disk as the DB.
- `source_windows_enabled: false` (study §2.6, audit F).

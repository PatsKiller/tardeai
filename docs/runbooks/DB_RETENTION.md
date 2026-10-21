# DB retention — owners, archive + tripwire, grants

Status:      ACTIVE
as_of:       2026-10-21T14:00:00-04:00 (operator rulings 2026-10-21 applied: priority set, registry-owned retention, §5.1 off-box)
Measured at: branch n8nmat/retention-all-managed (on 03b3fb362 + af5b1ef36) / live pin 464524b1b, not changed by this document; 2026-10-21 PRs #1900, #1902 and the registry-owned retention batch

**2026-10-11 retention-all-managed.** The operator asked, verbatim: *"Add, enable, and manage all deletes
and purges."* Every delete and purge on this host is now handled one of three ways:

- **archive-first** through one mechanism (§2, §6);
- **declared** in `config/data_retention_policy.json` `purge_paths` (§7), with a gate that fails on a new,
  unregistered deleter;
- **listed for an operator decision** in `~/n8n-maturity-verification/packets/retention-all-managed/OPERATOR_DECISION.md`.

Nothing here starts deleting a class of data that is not deleted today. Nothing deletes an archive.
**Every change takes effect at the next release.** The nightly run reads CURRENT's registry and code.

Source studies: `~/n8n-maturity-verification/DB_RETENTION_AND_IRIS_STUDY.md` (2026-10-10) and
`OVERNIGHT_REPORT_20261011.md`, section "DB retention" (findings 1, 4 and 6). This runbook covers the
retention engine as it stands after the 2026-10-11 hardening. It does not cover the Iris "librarian"
persona. Retention was never part of Iris's implementation (study §3).

## 0. 2026-10-21: registry-owned retention (operator rulings)

The operator ruled on the decision packet on 2026-10-21 (rulings at the bottom of
`~/n8n-maturity-verification/packets/retention-all-managed/OPERATOR_DECISION.md`): *"approve all archive-first
conversions, remove duplicate/rogue deleters, standardize on registry-owned retention"*. Branch
`fix/retention-registry-owned-20261021`. Tests: `tests/test_retention_registry_owned_20261021.py` (CI gate
`retention_registry_owned_20261021`, anchor `RETENTION_REGISTRY_OWNED`). D6, D7, D8.2, D5.3 and D10 are a separate
change; D11 is held (no new deletion anywhere).

| ruling | what changed |
|---|---|
| D1 | `archive_growth_cap_gb_month: 2.0`, `archive_total_budget_gb: 25` (already present). `market_quotes` stays hard DELETE. |
| D3.1 | `options_chain_snapshots` registry row is ARCHIVE_THEN_DELETE **45 d** (was 365). Both inline 45 d deletes in `options_desk_enterprise.py` are removed: `persist_chain_snapshot` and `prune_chain_snapshots` (the 15:45 `options_iv_snapshot.py` cron still calls it; it deletes nothing and reports `owner: db_retention`). The file is desk analytics, not broker code: it imports no `brokers.*`, places no order and makes no broker call. |
| D3.2 | `purge_youtube_transcripts.py` archives first (`managed_purge`, predicate `purge_after < CURRENT_DATE`); `transcript_processor.py --purge-expired` delegates to it. The live inline crontab purge is **not** changed (cron freeze): operator action below. |
| D3.3 | `news_symbol_guard.purge_mismatched_for_symbol` deletes through `managed_purge` by id: `news_articles`, then `catalyst_symbol_impact` children, then `catalyst_events`. Each verified batch commits on its own. |
| D3.4 | `hermes_source_registry.cleanup_orphan_rss_rows` archives the RSS stub rows first. `managed_purge` now gives an autocommit caller (`hermes_source_curation`) a transaction per batch and restores autocommit afterwards. |
| D3.5 | `reports_portal.purge(apply=True)` archives every table first (`notification_log`, `alert_events`, `telegram_outbox`, `ai_reports`). |
| D4.1 | `health_agent.persist()` no longer deletes; db_retention owns `health_agent_snapshots` at 30 d. |
| D4.2 | `hermes_score_history_retention.py` is RETIRED: it counts and deletes nothing. The `score_history_retention` step stays in `config/pipelines/hermes_learning.json` because its id is compiled into the deployed n8n fabric workflow (`tradeai-fabric-hermes-learning`, blocked step); removing it needs a fabric regeneration and redeploy. The self-tune purge of `hermes_score_history` is removed (counter stays 0). |
| D4.3 | New registry row `market_movers` DELETE 7 d `archive_first`; the inline delete in `finviz_market_movers.py` is removed. |
| D5.1 | `siem_retention_purge.py` purges `alert_events` at the registry's window (30 d, read from `policies[]`); `system_health_events` keeps `--days` (14). |
| D5.2 | `research_critique_pipeline` purges archived `hermes_research_intelligence` at **180 d by `created_at`** (librarian policy), was 45 d by `updated_at`. |
| D5.4 | The self-tune `hermes_external_research` 180 d delete is removed (registry ARCHIVE_THEN_DELETE 90 d owns it). |
| D8.1 | `rotate_runtime_logs.sh` gzips the **head** of a log of 100 MB or more to `<state>/archive/logs/<name>.<stamp>.gz`, re-reads it (byte count + sha256 of the decompressed stream), appends a `RetentionArchiveTripwire@v1` line to `archive/logs/TRIPWIRE.jsonl`, and only then truncates. A failed check leaves the log untouched and exits 1. Tail archives beyond `--keep` are moved into `archive/logs/`, never removed. `lib/retention_tripwire.py` reads that tripwire and treats `archive/logs` as a needle. |
| D8.3 | `disk_hygiene_enforcer.py` archives release-local data before removing a release: every real file under `<release>/data` and `<release>/state` that CURRENT does not hold byte-identically goes to `archive/file_prune/release_local_data/` (tar.gz + manifest + tripwire, verified), then the tree is removed. A failed archive keeps the release and reports it. Measured 2026-10-21 (read-only): the 4 prunable releases hold 8–21 such files each (0.4–1.6 MB); the 112 MB `data/portfolios/reports` copy is byte-identical to CURRENT's and is not re-archived. **Why archive rather than skip:** each release is ~13 GB; skipping any release holding a real data dir would skip every release (all of them have one), and the host-fill / Postgres ENOSPC failures of 2026-09-10 and 2026-09-18 are the larger risk. Archiving only what differs keeps every byte and keeps release pruning working. |
| D8.4 | Portfolio news history (90 d) and the weekly keep-8 / monthly keep-6 report rotations call `retention_archive.archive_prune` (archive-then-unlink; a failed archive removes nothing). |
| D8.5 | `scalp_cycle_receipt.prune` archives the old day ledgers first (under the ledger's own state root); a failed archive removes nothing and never breaks a cycle. The file is `scripts/lib/`, not `scripts/active_trader/**`. |
| D8.6 | The dead `file_prune` row `ingestion_summaries` is removed. |

**Gate (rule 10).** `check_retention_policy.py` has a new `purge_paths` state `RETIRED` (a former owner whose
delete was removed). A RETIRED entry whose script still matches the deleter scan, and that no live entry owns,
fails the gate. `archive_prune(` counts as a deleter call. RETIRED today: `options_chain_snapshot_prune`,
`health_agent_snapshot_prune`, `finviz_market_movers_prune`, `hermes_score_history_retention`.

**Dry run, read-only** (`db_retention.py --dry-run`: the session is opened `readonly=True` and file prunes only
list; CURRENT's `db_retention.py` is byte-identical to this branch's, run with
`env -u DB_PASSWORD -u DB_USER -u DB_HOST -u DB_NAME -u DB_PORT -u PGPASSWORD` so the script resolves its own
credential; the branch registry passed by `TRADEAI_RETENTION_REGISTRY`; back to back, 2026-10-21 ~13:40 ET):

```
origin/main registry:  125 enforced  Total would delete: 199,365 rows; would archive first: 59,903  (44 files)
this branch registry:  126 enforced  Total would delete: 200,182 rows; would archive first: 60,720  (44 files)
only difference:       options_chain_snapshots  captured_at  45  817  ARCHIVE+DELETE
```

The +817 rows are the duplicate owner moving: they are the 45 d rows the inline delete removed unarchived
until now. `market_movers` shows 0 tonight (the inline 7 d delete ran every 15 minutes until this change).

**Operator host action (cron freeze; not done by the agent).** The live crontab still has the inline
`youtube_transcripts` purge (inventory id `cron:L156`, line 158 of `crontab -l` on 2026-10-21; the packet's
"line 28" numbering is stale). It parses `.env` itself and deletes without an archive (the inventory notes it
never authenticates: the list-comprehension `exec` cannot rebind `pw`). Retire it by commenting it per
`docs/ops/LANE_REGISTRY_AND_RETIREMENT_CONVENTION.md`:

```
# RETIRED 2026-10-21 lane=set-purge-dates reason=youtube_transcripts purge moved to purge_youtube_transcripts.py (monthly platform maintenance, archive-first; operator D3.2) owner=platform review_by=2026-12-01
# 0 3 1 * * cd $PROJ && $PY -c "…set_purge_dates()" && $PY -c "…DELETE FROM youtube_transcripts…"
```

Overlay approval key (`~/n8n-maturity-verification/cron-inventory/funnel/overlay.py` `EXTRA_APPROVALS`):
`"cron:L156": "Approved 2026-10-21 (operator D3.2): retire the inline youtube_transcripts purge; owner purge_youtube_transcripts.py (monthly, archive-first)"`.
The monthly step already stamps `purge_after` (`set_purge_dates`) and purges, so nothing is lost.

## 1. Who deletes what

| Job | Scheduler (read-only check, 2026-10-11) | Scope | Archives? |
|---|---|---|---|
| `scripts/db_retention.py` | systemd `tradeai-platform-maintenance-nightly.timer` 01:15, which runs `CURRENT/scripts/pipelines/run_platform_maintenance_pipeline.sh` step `db_retention` (`add_step db_retention 30m /tmp/db_retention.lock …`). It has **no crontab line**: `crontab -l` has only a comment that mentions it. | Every DELETE and ARCHIVE_THEN_DELETE row of `config/data_retention_policy.json`, plus four file globs | ARCHIVE_THEN_DELETE rows always; DELETE rows with `archive_first: true` (93 of 96 since 2026-10-11, §3); file globs archive-then-unlink (§6). |
| `scripts/run_hermes_librarian_retention.py --apply` → `scripts/lib/hermes_librarian/retention.py` | systemd `hermes-librarian-retention.timer` 05:10 (+≤180 s). The service `cd`s into CURRENT. It has **no crontab line**. | `hermes_research_intelligence` lifecycle, failed `hermes_embedding_queue` rows, orphan `content_embeddings` (news and hermes_research) | **yes, since 2026-10-11** (`archive_first: true` in the librarian policy; receipt per run) |
| `scripts/db_trim.py --apply` | operator-run only, under a db-write grant (§4, D7) | duplicate indexes, backup tables and schemas, row trims | yes: `archive/db_trim/<stamp>/` plus `TRIPWIRE.jsonl` |

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

**Update 2026-10-20: two operator db_trim-convention records.** Both are archive-first and recorded in
`archive/db_trim/TRIPWIRE.jsonl`. Detail is in `docs/ops/LIVE_CHANGES_20261020.md` §4.
- `20261020T165931Z`, `kind rows`: 531 empty-payload `analyst_data_history` rows (`as_of >= 2026-10-18`, written
  by pre-fix dev-checkout code), archived to `db_trim/20261020T165931Z/rows_analyst_data_history.jsonl.gz`.
- `20261020T173035Z`, `kind rows_settled`: 205 stuck `communication_deliveries` reservations were settled, not
  deleted: CANCELLED 150, SUPPRESSED 52, SENT 3. The pre-image is archived to
  `db_trim/20261020T173035Z/rows_communication_deliveries_stuck.jsonl.gz`.

## 3. `archive_first` on DELETE rows (all of them now)

Each DELETE row carries `archive_first`. When it is `true`, the row goes through the same path as
ARCHIVE_THEN_DELETE: archive, manifest and tripwire. As of 2026-10-11, these are the counts:

| | rows |
|---|---|
| DELETE rows | 96 |
| `archive_first: true` | **93**, including `content_embeddings`, which the operator approved earlier on 2026-10-11 |
| `archive_first: false` | 3, each with a written `archive_first_hold` |
| ARCHIVE_THEN_DELETE rows (always archive) | 29 |
| **enforced rows that archive first** | **122 of 125** |

The three holds:

| table | why it is held | decision |
|---|---|---|
| `market_quotes` | Over the per-row cap: about 94k rows/day, projected 0.19 GB/month archived | D1 |
| `schwab_stream_book`, `schwab_stream_quotes` | Broker-adjacent (AGENTS §0 rule 2): not modified without an execution grant | D2 |

**What changed in `db_retention.py` on 2026-10-11:**
- `archive_rows` streams the rows through a server-side cursor. Before, a client-side fetch held the whole
  night's archive in memory.
- The archive is re-read from disk and its sha256 and row count are checked against the manifest
  **before** the DELETE runs.
- The DELETE's rowcount must equal the number of rows archived. If a row matched between the archive and
  the DELETE, the batch rolls back, and the next night archives the full set again.
- `--dry-run` opens a **read-only session** and prints the action for each row (`ARCHIVE+DELETE` or
  `DELETE (no archive)`).
- Parsers read the `Total …: N rows; archived first: M` line, so its format is unchanged. A dry run prints
  `archived first: 0` there, followed by `; would archive first: M`.

**Gate.** `check_retention_policy.py` rule 8 refuses `archive_first: false` on a row that has no
`archive_first_hold` of at least 20 characters.

**Rollback.** Set `archive_first: false` on the row and add a hold. The change applies at the next release.

### 3.1 Archive-growth projection and cap (read-only)

```
python3 scripts/db_retention.py --archive-projection [--json] [--table T]
```

For each enforced row, the projection reports:
- the rows due tonight;
- rows per day, taking the larger of two rates: rows crossing the window boundary (the week just past it)
  and rows arriving (the last 7 days);
- gzip bytes per row, from a 200-row sample at the archive's codec and level;
- GB/month.

It compares the total against `archive_growth_cap_gb_month`, which is **2.0** in the registry. The
session is read-only.

| measured 2026-10-11 (ET) | archive-first GB/month | notes |
|---|---|---|
| 09:51, before the flip | 1.74 | `content_embeddings` 1.57 at 7.5 KB/row (eligible-row sample) + 29 ARCHIVE_THEN_DELETE rows 0.17 |
| 10:04, after the flip | 1.19 | `content_embeddings` 0.79 at 3.8 KB/row (newest-row sample) + 0.41 for everything else |
| `content_embeddings` bytes/row by sample (1,000 rows each) | | oldest 6.4 KB · random 4.2 KB · newest 3.8 KB → **0.8–1.6 GB/month** at about 7k rows/day |
| hard-DELETE rows, if they were archived | 0.27 | `market_quotes` 0.19, `schwab_stream_*` 0.08 |

**Conservative total after the flip: about 1.97 GB/month,** inside the 2.0 cap. File archives add about
0.1 GB/month (§6). Above roughly 1.9 GB/month of row archive, the measured `ARCHIVE_GROWTH` finding can
fire, and that is intended: it is the signal to look. The cap is an operator number (D1).

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

**`db_trim.py --apply` (D7, 2026-10-21).** The same check (`scripts/lib/db_write_grant.py`) gates every
`db_trim.py <action> --apply`. Without an active db-write grant it prints `db_trim: REFUSED --apply: db-write
grant: <reason>` to stderr and exits **2** before any `psql` call. The verdict is written under `grant` in
`data/runtime/db_trim_last.json`. `inventory` and the dry run (no `--apply`) need no grant.

```
python3 scripts/db_trim.py purge-dead-queues                                   # dry run, quote it
TRADEAI_DB_WRITE_GRANT=<id> python3 scripts/db_trim.py purge-dead-queues --apply
```

```
python3 scripts/db_retention.py --junk-fused-signal-embeddings                 # dry run, quote it
TRADEAI_DB_WRITE_GRANT=<id> python3 scripts/db_retention.py --junk-fused-signal-embeddings --apply
```

## 5. Archive lifecycle: size, age, growth (report only)

All archives sit on the **same disk as the database** (`/`), under `<state>/archive/`. The stores are
`db_retention/<table>/`, `file_prune/<id>/`, `db_trim/` and `comms_lifecycle/`.

**Nightly finding.** `report_db_hygiene.py` (platform-maintenance step 11) adds `archive_usage`
(`RetentionArchiveUsage@v1`) to its report. That object holds, per store, the bytes, file count,
oldest and newest files, and bytes written in the last 30 days. The report raises **`ARCHIVE_GROWTH` (P2)** when any of these is true:
- the last-30-day rate is above `archive_growth_cap_gb_month` (2.0);
- the archive is larger than `archive_total_budget_gb` (25);
- free disk is below 20 GB.

**Read-only measurement, 2026-10-11 10:00 ET:**
- **0.41 GB in total**, all written in the last 30 days. 322 MB of that is the one-time junk-embedding
  archive of 10-11.
- On disk: `db_retention` 358 MB, `comms_lifecycle` 30 MB, `db_trim` 8 MB.
- `/` has 114 GB free.
- **No findings.**

**What is not automated.**
- **No job deletes or rotates an archive** (AGENTS §0 rule 6).
- An **off-box copy** of the archive (and of `persistent-state`) is an operator decision (AGENTS §17,
  §18), listed as D9. **Update 2026-10-21:** the operator ruled D9 = (a) for the archive. The copier is
  built (§5.1); its timer is proposed, not installed. Off-box backup of the rest of `persistent-state` is
  still open.
- If disk pressure ever needs archive space back, the operator chooses: move the archive off-box, then
  delete the local copy under a grant.

### 5.1 Off-box copy to Google Drive (D9 = (a), 2026-10-21)

The operator ruled on 2026-10-21 that the archives are copied off-box to Google Drive over the existing Drive
path. `scripts/archive_offbox_sync.py` does this. Lane `archive-offbox-sync` in `config/lane_registry.json`
is `NEVER_SCHEDULED` until the operator installs the timer. Install packet:
`docs/ops/packets/archive-offbox-20261021/`.

**Mechanism.** It uses the same mechanism as `scripts/backup_secrets_state.sh`:
- `gog drive` with the same account and the same `Trade_AI_Backups` folder id.
- `gpg --cipher-algo AES256 -c` with `--passphrase-file`.

Both credential files are passed **by path**. gpg reads the passphrase file itself. gog's keyring password is
read inside a `bash -c` child. Neither value enters the Python process, an argv, a log or the receipt.
Plaintext never leaves the box: each archive file becomes one `.gpg` blob.

**Layout.** `Trade_AI_Backups/archive/<area>/<YYYYMM of file mtime>/<path within area, '/'→'__'>.gpg`.

**Manifest.** `<state>/data/runtime/archive_offbox_manifest.json` (`ArchiveOffboxManifest@v1`) holds one
entry per archive file, keyed by its path under `<state>/archive`. Each entry has:
- sha256, size, mtime_ns and `uploaded_at`;
- the Drive file id, name and folder;
- the ciphertext size and md5, and `verified_by`.

A file whose bytes change (an appended `TRIPWIRE.jsonl`) is uploaded again under a sha-suffixed name. The
earlier entry is kept in `versions`.

**Guarantees** (each one is tested in `tests/test_archive_offbox_sync_20261021.py`, gate
`archive_offbox_sync_20261021`):
- **Dry run by default.** It writes nothing: no manifest, no receipt, no lock, no gog or gpg call.
- **Verify before record.** After each upload it runs `gog drive get`. Drive's size must equal the
  ciphertext size, and Drive's `md5Checksum`, when reported, must equal the ciphertext md5. If Drive reports
  neither, the upload counts as a failure and is retried next run.
- **Never deletes.** It never deletes a local archive or anything on Drive. The local copy stays
  authoritative and tripwired.
- **Bounded.** Each run is capped at 1 GiB of plaintext and 1500 files. It stops at the first file that does
  not fit, except that the first file of a run always goes. The next run resumes.
- **In-flight and symlink guards.** Files modified in the last 15 minutes are skipped. Symlinks are skipped,
  never followed.
- **Per-file failures.** One file failing never stops the others. Each failure is written to the receipt as
  `{path, stage, error type}`, and the run exits 1.
- **Receipt.** `data/runtime/archive-offbox-sync_last.json` (LaneRunReceipt@v2). `produced_count` is the
  number of files uploaded and verified.

**Tripwire.** `scripts/archive_offbox_sync.py` is in `retention_tripwire.ALLOWLIST_REL`, with its reason. It
reads archive bytes only to hash and encrypt them. It never parses rows back into a live store. The
installed `.service` unit does not name an archive path, so the nightly reference scan stays clean.

**Read-only dry run, 2026-10-21 (live state root, this branch):**

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

After the run, neither `archive_offbox_manifest.json` nor `archive-offbox-sync_last.json` existed, so the dry
run wrote nothing. At 1500 files a night, the backlog of about 4,757 files drains in four runs.

**Not yet proven** (`[DOC-CLAIM]` until the first observed `--apply`):
- The JSON shape of `gog drive get`. The verifier looks for `size` and `md5Checksum` anywhere in the document.
  If gog omits both, every upload fails closed as `verify`, and nothing is recorded.
- How many gog calls fit in the unit timeout.

The packet README gives the observed first run (`--max-files 3`).

## 6. File prunes: archive-then-unlink

**Registry rows.** The four globs that were hard-coded in `db_retention.py` (and unlinked with no archive)
are now `file_prune` rows in the registry (`FilePrunePolicy`). All have `archive: true`. The dead
`ingestion_summaries` glob was removed on 2026-10-21 (D8.6); three rows remain.

**How a prune runs:**
1. The selected files are tarred to `<state>/archive/file_prune/<id>/<stamp>-<id>.tar.gz`.
2. A manifest (`kind: files`) records each member's name, source, sha256, bytes and mtime, and a tripwire
   record is written.
3. The tar is re-read from disk, and every member is re-hashed against its manifest entry.
4. **Only then** are the sources unlinked. If that check fails, nothing is unlinked and the run exits 1.

`lib/retention_tripwire.py` reads `file_prune/*/TRIPWIRE.jsonl`. It also treats `archive/file_prune` as a
needle: a live script that references that path raises a P1 finding.

| id | dir (under the run's PROJECT_ROOT) | pattern | days | measured 2026-10-11 |
|---|---|---|---|---|
| `raw_snapshots` | `data/portfolios/state/raw_snapshots` | `*.json` | 14 | 552 files, 18 MB; ~1–2 MB per trading day aging out |
| `ticker_snapshot_history` | `data/portfolios/state/ticker_snapshot_history` | `*.json` | 14 | 552 files, 42 MB; ~3–5 MB per trading day |
| `catalyst_cache` | `data` | `catalyst_cache_*.json` | 3 | ~1 file/day, 280 KB, release-local |

**Governed-universe history.** `hermes_universe_history_retention.py` (platform-maintenance step 7) now
archives the snapshots it thins out the same way, under `file_prune/hermes_governed_universe_history/`.
- About 47 files and **~43 MB/day** age out.
- Consecutive snapshots compress about **25×** (measured on 40 files: 32.4 MB to 1.26 MB), so about
  2 MB/day lands in the archive.
- `--no-archive` restores the plain unlink.

## 7. Every delete and purge on this host: the inventory

**Source.** `config/data_retention_policy.json` `purge_paths` holds 34 owner entries. This table is a
rendering of it.

**Gate.** `check_retention_policy.py --fail-on-new` (rule 9) fails when a script under `scripts/` or
`linux_launchers/` does any of the following and no entry names it:
- contains `DELETE FROM` or `TRUNCATE`;
- calls `managed_purge`, `archive_then_delete_batches` or `archive_files_then_unlink`.

**How this was measured** (2026-10-11, read-only):
- a repo grep on `03b3fb362`;
- live `crontab -l` and `systemctl --user` timers and units;
- the stage manifests in `config/pipelines/*.json`;
- per-row volumes from `--archive-projection`.

**Inventory counts:**
- **245** grep hits for delete patterns across **153** files.
- **50** non-test files hold a SQL `DELETE FROM` or `TRUNCATE`. All are registered.
- **34** `purge_paths` entries.

**Archive state of the entries:**

| state | entries |
|---|---|
| archive-first (`MANAGED`, this change) | 8 |
| own archive (`MANAGED_OWN_ARCHIVE`) | 3 |
| unarchived, operator decision (`UNARCHIVED_DECISION`) | 12 |
| superseded in practice (`DEFERS_IN_PRACTICE`) | 2 |
| unarchived by the AGENTS mentions rule (`UNARCHIVED_BY_RULE`) | 1 |
| unscheduled | 2 |
| rebuild, operator API action, or test | 3 |
| not data | 2 |
| broker-adjacent, listed only | 1 |

### 7.1 DB row purges

| owner (script) | scheduler (live) | deletes | archive | state |
|---|---|---|---|---|
| `db_retention.py` | platform-maintenance-nightly 01:15 (CURRENT), the **only** scheduler. (Until 2026-10-21 the Sun 06:30 weekly disk cleanup also ran it from the dev tree; removed, D6, §10.) | 125 registry rows + 4 file globs; 64,656 rows would go tonight (dry run, §8) | archive-first on 122 of 125 rows; files archive-then-unlink | MANAGED |
| `lib/hermes_librarian/retention.py` via `run_hermes_librarian_retention.py` | `hermes-librarian-retention.timer` 05:10 (no longer also run by the weekly disk cleanup: D6, §10) | `hermes_research_intelligence` archived >180 d; `hermes_embedding_queue` failed >14 d; `content_embeddings` news + hermes_research orphans. The 90 d rail defers to db_retention | archive-first (`archive_first: true` in `config/hermes_librarian_policy.yaml`); receipt `data/runtime/hermes_librarian_retention_last.json` | MANAGED |
| `siem_retention_purge.py` | platform-maintenance-nightly | `system_health_events` >14 d; `alert_events` at the registry's 30 d (2026-10-21, D5.1) | archive-first (`--no-archive` lever) | MANAGED |
| `prune_protection_proposals_retention.py` | `run_protection_pipeline.sh`, cron every 30 min | `paper_protection_adjustment_proposals` SUPERSEDED >30 d | archive-first | MANAGED |
| `research_critique_pipeline.retention_purge` | hermes coordinator */15 → curator `--apply` | `watch_directives` curator-archived >60 d; `hermes_research_intelligence` archived >180 d by `created_at` (2026-10-21, D5.2); `hermes_directive_hits_staging` drained >14 d | archive-first. The dry run used to EXECUTE the DELETEs uncommitted; it now only counts | MANAGED |
| `hermes_autonomous_self_tune.self_purge` | stage manifests `hermes_learning.json`, `after_close.json` | failed embed queue >7 d; research rejected/superseded/expired >180 d; 3 dead tables (score_history and external_research purges retired 2026-10-21, D4.2/D5.4) | archive-first; an archived DELETE replaces TRUNCATE (the dead tables held 0 rows) | MANAGED |
| `comms_lifecycle.py` | cron `17 * * * *` | `communication_*` rows past TTL. Since #1885 (served in `1d00a5181`, 2026-10-20 20:45 ET) there is also an opt-in `--steps reservations` step. It settles `communication_deliveries` left RESERVED/SENDING for over an hour (INBOUND → CANCELLED, unclaimed outbound → EXPIRED, SENDING → UNKNOWN; at most 500 per run). It changes only the delivery status. It **deletes nothing and sends nothing**. It is **not** in the cron's default `classify,expire,purge` steps until the cron-inventory row is approved. | its own jsonl.gz archive, count-checked | MANAGED_OWN_ARCHIVE (`communication_thread_membership` is exempt and never purged, KEEP_FOREVER: D5.3, §10) |
| `db_trim.py` | operator-run | backup tables, duplicate indexes, row trims | pg_dump / jsonl.gz + `db_trim/TRIPWIRE.jsonl` | MANAGED_OWN_ARCHIVE (`--apply` requires `TRADEAI_DB_WRITE_GRANT`, else exit 2: D7, §4) |
| quarantine / scrub / `purge_error_synthesis` / `archive_trade_closed_probe_rows` | manual | condition rows | quarantine table or json | MANAGED_OWN_ARCHIVE |
| `options_desk_enterprise.py` | cron 15:45 `options_iv_snapshot.py` + inline on every API persist | nothing since 2026-10-21 | n/a | RETIRED (D3.1): db_retention owns `options_chain_snapshots`, ARCHIVE_THEN_DELETE 45 d |
| `finviz_market_movers.py` | cron */15 06–16 M–F | nothing since 2026-10-21 | n/a | RETIRED (D4.3): registry row `market_movers` DELETE 7 d `archive_first` |
| `purge_youtube_transcripts.py` + `transcript_processor.py` | monthly pipeline (11-01). The live inline crontab line (`cron:L156`) is the operator's to retire (§0) | `youtube_transcripts` past `purge_after` | archive-first (`managed_purge`) | MANAGED (D3.2) |
| `news_symbol_guard.py` | API + health-agent remediation | mis-tagged `news_articles` / `catalyst_events` (+ impact children) | archive-first (`managed_purge` by id) | MANAGED (D3.3) |
| `hermes_source_registry.py` | cron 23:30 | RSS stub rows in `research_sources` | archive-first (`managed_purge`) | MANAGED (D3.4) |
| `reports_portal.py` purge | operator API `POST /api/v2/reports/purge` | notification_log / alert_events / telegram_outbox / ai_reports | archive-first (`managed_purge` per table) | MANAGED (D3.5) |
| `health_agent.py` | `tradeai-health-agent.timer` | nothing since 2026-10-21 | n/a | RETIRED (D4.1): db_retention owns `health_agent_snapshots` at 30 d |
| `hermes_score_history_retention.py` | stage `hermes_learning.json` (step kept, see §0) | nothing since 2026-10-21 (counts only) | n/a | RETIRED (D4.2): db_retention is the one owner of `hermes_score_history` |
| `prune_document_mentions.py` | platform-maintenance-nightly | orphaned / aged `document_mentions` | none | UNARCHIVED_BY_RULE: a mention is a projection (AGENTS "Mentions: retention") |
| `lib/hermes_librarian/graph.py`, `market_quotes_downsample.py` | none found | co-occurrence edges; quote downsample | none | UNSCHEDULED |
| rebuild-in-place (12 scripts), operator API row deletes (3), tests/probes (3) | various | delete-then-insert of derived rows; one operator-owned row | n/a | NOT_RETENTION |
| `n8n_coordination_ledger` nonces | inline | expired replay nonces (sqlite) | n/a | NOT_DATA |
| alpaca reconciler, snaptrade/schwab ingest + journal, positions_sync, schwab_transport, stop_lifecycle_monitor | cron | broker data | not investigated | BROKER_OUT_OF_SCOPE (rule 2) |

### 7.2 File prunes

| owner | scheduler | deletes | archive | state |
|---|---|---|---|---|
| `db_retention.py` `file_prune` (4) | as db_retention | §6 | archive-then-unlink | MANAGED |
| `hermes_universe_history_retention.py` | platform-maintenance-nightly | thinned universe snapshots, ~43 MB/day | archive-then-unlink, ~25× | MANAGED |
| `rotate_runtime_logs.sh` | platform-maintenance-nightly step 1 | logs ≥100 MB: head archived to `archive/logs/` (verified, tripwire) before truncation; last 25 MB kept beside the log; surplus tail `.gz` moved to `archive/logs/` | archive-then-truncate | MANAGED (D8.1) |
| `disk_hygiene_enforcer.py`, `weekly_disk_cleanup_notify.py` | timers 04:15 daily, Sun 06:30 | release dirs (keep 2; release-local data CURRENT does not hold is archived first, D8.3); `~/backups` >45/60 d; preclean dirs | release-local data: archive-then-unlink; backup piles: none | UNARCHIVED_DECISION (backup piles) |
| `backup_enforcer.py`, `run_pg_backup.sh`, `n8n_lab_backup.sh`, `backup_secrets_state.sh` | hourly; 02:30; nightly | pg_dump keep 1 (partials <1.5 GB older than 2 h are moved to `archive/`); n8n keep 14; Drive families | rotation of backups | UNARCHIVED_DECISION (D8.2 fixed: `.part` + size + `gzip -t` + atomic rename; the enforcer skips `.part` and anything younger than 2 h, §10) |
| `portfolio_news.py`, `portfolio_weekly_report.py`, `portfolio_monthly_report.py`, `portfolio_monthly_synthesis.py` | portfolio cadences | news history >90 d; keep 8 weekly / 6 monthly LLM reports | archive-then-unlink (`archive_prune`) | MANAGED (D8.4) |
| `lib/scalp_cycle_receipt.py` | scalp-live cron | day ledgers >30 d (directory absent today) | archive-then-unlink (`archive_prune`) | MANAGED (D8.5) |
| `docs_retention.sh`, `artifacts_retention.sh`, `docs_hygiene.py` | weekly / manual | dry-run docs, Playwright artifacts | none | UNARCHIVED_DECISION (D8) |
| `agent_worktree_retention.py` | timer 04:40 | merged clean agent worktrees | git history | NOT_DATA |
| `lib/advisory/kb_lessons_retention.py`, `lib/agent_file_lease.py`, `weekly_hygiene.py` | manual / runtime | rotate or move | yes (gzip + SHA256SUMS, or a move) | archive already (no scheduler for kb_lessons) |
| about 15 temp, lock and atomic-write cleanups (`*.tmp`, pid and lock files, stage dirs, deploy scratch) | runtime | the writer's own scratch | n/a | NOT_DATA, not registered |

## 8. The nightly step, dry run with the new registry (read-only, 2026-10-11 10:03 ET)

**How it was run.** From this branch, with these settings:
- `PGOPTIONS=-c default_transaction_read_only=on`;
- the session itself opened `readonly=True` (the new dry-run path);
- `PROJECT_ROOT` set to CURRENT;
- the DB credential from the rendered env, loaded into the process environment.

**Proof that it wrote nothing.** The `archive/db_retention` listing had the same entry count before and
after.

```
DRY RUN — DB Retention Policy — 2026-10-11 10:03
  registry …/config/data_retention_policy.json: 125 enforced, 11 KEEP_FOREVER (…)
  fused_signals                               created_at            90      4074  ARCHIVE+DELETE
  market_ohlcv_bars                           bar_time             365     40887  ARCHIVE+DELETE
  market_quotes                               fetched_at            90         6  DELETE (no archive)
  scope_governor_audit                        created_at            30     15968  ARCHIVE+DELETE
  …  (39 rows with work tonight; full output in the decision packet)
  Total would delete: 64,656 rows; archived first: 0 (+0 source-window rows, archive-first); would archive first: 64,650
  rows with archive_first: 122 of 125; hard DELETE (no archive): 3
DRY RUN — File Pruning
  …/raw_snapshots            *.json   14   2  ARCHIVE+UNLINK
  …/ticker_snapshot_history  *.json   14   2  ARCHIVE+UNLINK
  Total would prune: 4 files
rc=0
```

## 9. Still open

The operator decisions D1–D9 are in
`~/n8n-maturity-verification/packets/retention-all-managed/OPERATOR_DECISION.md`.

Still open:
- `source_windows_enabled: false` (`social_post` / `fused_signal` at 30 d). The `created_at` loop bug is
  fixed (D10, §10); enabling is a separate operator ruling.
- The 48 junk-purge archives from 2026-10-11 have no tripwire records. A backfill needs a `state-write`
  grant.

## 10. Operator rulings 2026-10-21, priority set (D6, D8.2, D7, D5.3, D10)

The operator approved all leans on 2026-10-21 and set the priority order D6, D8.2, D7, D5.3, D10
(`OPERATOR_DECISION.md`, bottom). Tests: `tests/test_retention_priority_20261021.py`, CI gate
`retention_priority_20261021` (ANCHOR `RETENTION_PRIORITY_20261021`). Each takes effect at the next release,
except D6, which the Sunday timer picks up from the dev tree as soon as this lands there.

| # | Change | Where |
|---|---|---|
| D6 | `weekly_disk_cleanup_notify.py` no longer runs `run_hermes_librarian_retention.py` or `db_retention.py`. It keeps disk hygiene and the preclean-dir cleanup. Row retention has one owner per table: platform-maintenance-nightly from CURRENT, and `hermes-librarian-retention.timer` (CURRENT) for its own scope. The Telegram summary says so instead of reporting `DB rows deleted: 0`. | `scripts/weekly_disk_cleanup_notify.py`; `purge_paths` `db_retention`, `hermes_librarian_retention`, `disk_hygiene_enforcer` |
| D8.2 | `run_pg_backup.sh` writes `<name>.part`, keeps the size check, adds `gzip -t`, then renames in the same directory (atomic). A failed or corrupt dump is moved to `archive/` (`.incomplete`, `.corrupt`, `.failed` from an `EXIT` trap), never unlinked. `backup_enforcer.py` (already on main since `ba371f978`) skips `.part`/`.partial` and anything younger than 2 h, and moves older partials to `archive/`. | `linux_launchers/run_pg_backup.sh`; `scripts/backup_enforcer.py`; `purge_paths` `backup_rotation` |
| D7 | `db_trim.py <action> --apply` requires `TRADEAI_DB_WRITE_GRANT` (§4), else exit 2 before any DB call. | `scripts/db_trim.py`; `purge_paths` `db_trim` |
| D5.3 | `comms_lifecycle.py` purge no longer archives or deletes `communication_thread_membership` (`KEPT_TABLES`). Threads are kept; the registry row stays KEEP_FOREVER. Deliveries, outbox and entity links keep their archive-first purge. The table has no FK to `communication_events`, so an event purge leaves membership rows intact. | `scripts/comms_lifecycle.py`; `docs/ops/COMMS_HUB_2026-10-07.md`; `purge_paths` `comms_lifecycle` |
| D10 | The `content_embeddings` source-window predicate measures the **source document's** age: `EXISTS (SELECT 1 FROM <source table> s WHERE s.<key> = t.source_id AND s.<ts> < now() - <days>)`. The registry row names the source per type in `source_windows_source_tables` (`fused_signal` → `fused_signals.created_at`, `social_post` → `social_posts.ingested_at`) and `source_key_column: source_id`. A missing or malformed mapping is a config error (fail closed), and `check_retention_policy.py` rejects it. An embedding whose source row is gone is not selected; the 90 d rail owns it. **`source_windows_enabled` stays `false`**: no source-window row runs. | `scripts/db_retention.py` (`_source_table_spec`, `source_window_predicate`); `scripts/check_retention_policy.py`; `config/data_retention_policy.json` |

**Host change for D6 (operator, not made by the agent).** The code change removes the DB steps whatever
tree the unit runs from. The unit's `WorkingDirectory` is still the dev tree; the proposal in the commit message (PR body)
moves it to CURRENT. Until then the Sunday job runs disk hygiene from dev-tree code.

**Dry run.** Not re-run for this change: the read-only `--dry-run` from the worktree could not open a DB
session (the worktree has no `.env`, so `db_retention.py` refused with `DB_PASSWORD is empty`), and supplying
the credential another way was denied. The hermetic test `test_d10_still_disabled_so_nothing_runs` shows
the disabled source windows reach no cursor. The operator or a session with credential access should run
`db_retention.py --dry-run` from CURRENT and from this branch and compare the totals; they should be equal.

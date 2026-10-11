# DB retention — owners, archive + tripwire, grants

Status:      ACTIVE
as_of:       2026-10-11T10:30:00-04:00
Measured at: branch n8nmat/retention-all-managed (on 03b3fb362 + af5b1ef36) / live pin 464524b1b, not changed by this document

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

## 1. Who deletes what

| Job | Scheduler (read-only check, 2026-10-11) | Scope | Archives? |
|---|---|---|---|
| `scripts/db_retention.py` | systemd `tradeai-platform-maintenance-nightly.timer` 01:15, which runs `CURRENT/scripts/pipelines/run_platform_maintenance_pipeline.sh` step `db_retention` (`add_step db_retention 30m /tmp/db_retention.lock …`). It has **no crontab line**: `crontab -l` has only a comment that mentions it. | Every DELETE and ARCHIVE_THEN_DELETE row of `config/data_retention_policy.json`, plus four file globs | ARCHIVE_THEN_DELETE rows always; DELETE rows with `archive_first: true` (93 of 96 since 2026-10-11, §3); file globs archive-then-unlink (§6). |
| `scripts/run_hermes_librarian_retention.py --apply` → `scripts/lib/hermes_librarian/retention.py` | systemd `hermes-librarian-retention.timer` 05:10 (+≤180 s). The service `cd`s into CURRENT. It has **no crontab line**. | `hermes_research_intelligence` lifecycle, failed `hermes_embedding_queue` rows, orphan `content_embeddings` (news and hermes_research) | **yes, since 2026-10-11** (`archive_first: true` in the librarian policy; receipt per run) |
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
  §18), listed as D9.
- If disk pressure ever needs archive space back, the operator chooses: move the archive off-box, then
  delete the local copy under a grant.

## 6. File prunes: archive-then-unlink

**Registry rows.** The four globs that were hard-coded in `db_retention.py` (and unlinked with no archive)
are now `file_prune` rows in the registry (`FilePrunePolicy`). All four have `archive: true`.

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
| `ingestion_summaries` | `data/logs` | `ingestion_summary_*.json` | 7 | **dead glob**: 0 matches, and `CURRENT/data/logs` does not exist |
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
| `db_retention.py` | platform-maintenance-nightly 01:15 (CURRENT). **Also** `tradeai-weekly-disk-cleanup.timer` Sun 06:30, which runs it from the **dev tree** (D6) | 125 registry rows + 4 file globs; 64,656 rows would go tonight (dry run, §8) | archive-first on 122 of 125 rows; files archive-then-unlink | MANAGED |
| `lib/hermes_librarian/retention.py` via `run_hermes_librarian_retention.py` | `hermes-librarian-retention.timer` 05:10 (also run by the weekly disk cleanup) | `hermes_research_intelligence` archived >180 d; `hermes_embedding_queue` failed >14 d; `content_embeddings` news + hermes_research orphans. The 90 d rail defers to db_retention | archive-first (`archive_first: true` in `config/hermes_librarian_policy.yaml`); receipt `data/runtime/hermes_librarian_retention_last.json` | MANAGED |
| `siem_retention_purge.py` | platform-maintenance-nightly | `system_health_events` and `alert_events` >14 d | archive-first (`--no-archive` lever) | MANAGED (14 d vs 30 d window: D5) |
| `prune_protection_proposals_retention.py` | `run_protection_pipeline.sh`, cron every 30 min | `paper_protection_adjustment_proposals` SUPERSEDED >30 d | archive-first | MANAGED |
| `research_critique_pipeline.retention_purge` | hermes coordinator */15 → curator `--apply` | `watch_directives` curator-archived >60 d; `hermes_research_intelligence` archived >45 d; `hermes_directive_hits_staging` drained >14 d | archive-first. The dry run used to EXECUTE the DELETEs uncommitted; it now only counts | MANAGED (45 d vs 180 d window: D5) |
| `hermes_autonomous_self_tune.self_purge` | stage manifests `hermes_learning.json`, `after_close.json` | failed embed queue >7 d; score_history >30 d; research rejected/superseded/expired >180 d; external_research >180 d; 3 dead tables | archive-first; an archived DELETE replaces TRUNCATE (the dead tables held 0 rows) | MANAGED |
| `comms_lifecycle.py` | cron `17 * * * *` | `communication_*` rows past TTL | its own jsonl.gz archive, count-checked | MANAGED_OWN_ARCHIVE (deletes `communication_thread_membership`, which is KEEP_FOREVER: D5) |
| `db_trim.py` | operator-run | backup tables, duplicate indexes, row trims | pg_dump / jsonl.gz + `db_trim/TRIPWIRE.jsonl` | MANAGED_OWN_ARCHIVE (no grant check: D7) |
| quarantine / scrub / `purge_error_synthesis` / `archive_trade_closed_probe_rows` | manual | condition rows | quarantine table or json | MANAGED_OWN_ARCHIVE |
| `options_desk_enterprise.py` | cron 15:45 `options_iv_snapshot.py` + inline on every API persist | `options_chain_snapshots` >45 d | **none** | UNARCHIVED_DECISION. The registry says ARCHIVE_THEN_DELETE 365 d, but this 45 d delete runs first (D3) |
| `finviz_market_movers.py` | cron */15 06–16 M–F | `market_movers` >7 d | none | UNARCHIVED_DECISION. No registry row (D4) |
| `purge_youtube_transcripts.py` + `transcript_processor.py` | monthly pipeline (11-01) **and** live crontab line 28: inline python that reads `.env` (two schedulers) | `youtube_transcripts` past `purge_after` | none | UNARCHIVED_DECISION (D3) |
| `news_symbol_guard.py` | API + health-agent remediation | mis-tagged `news_articles` / `catalyst_events` | none | UNARCHIVED_DECISION (D3) |
| `hermes_source_registry.py` | cron 23:30 | RSS stub rows in `research_sources` | none | UNARCHIVED_DECISION (D3) |
| `reports_portal.py` purge | operator API `POST /api/v2/reports/purge` | notification_log / alert_events / telegram_outbox / ai_reports | none (deletes `telegram_outbox`, which is ARCHIVE_THEN_DELETE) | UNARCHIVED_DECISION (D3) |
| `health_agent.py` | `tradeai-health-agent.timer` | `health_agent_snapshots` >90 d | none | DEFERS_IN_PRACTICE: db_retention archives and deletes at 30 d first (D4) |
| `hermes_score_history_retention.py` | stage `hermes_learning.json` | `hermes_score_history` >21 d, thinned | none | DEFERS_IN_PRACTICE: db_retention deletes everything >21 d. This is the third owner (D4) |
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
| `rotate_runtime_logs.sh` | platform-maintenance-nightly step 1 | logs ≥100 MB: keeps the last 25 MB gzipped, **discards the head**, keeps 2 `.gz` per log | partial | UNARCHIVED_DECISION (D8) |
| `disk_hygiene_enforcer.py`, `weekly_disk_cleanup_notify.py` | timers 04:15 daily, Sun 06:30 | release dirs (keep 2, and **release-local data dirs die with them**); `~/backups` >45/60 d; preclean dirs | none | UNARCHIVED_DECISION (D8) |
| `backup_enforcer.py`, `run_pg_backup.sh`, `n8n_lab_backup.sh`, `backup_secrets_state.sh` | hourly; 02:30; nightly | pg_dump keep 1 (plus partials <1.5 GB **at any age**); n8n keep 14; Drive families | rotation of backups | UNARCHIVED_DECISION (D8: the hourly enforcer can unlink a dump that is still being written) |
| `portfolio_news.py`, `portfolio_weekly_report.py`, `portfolio_monthly_report.py`, `portfolio_monthly_synthesis.py` | portfolio cadences | news history >90 d; keep 8 weekly / 6 monthly LLM reports | none | UNARCHIVED_DECISION (D8) |
| `lib/scalp_cycle_receipt.py` | scalp-live cron | day ledgers >30 d (directory absent today) | none | UNARCHIVED_DECISION (D8) |
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

Two items are still unchanged from earlier:
- `source_windows_enabled: false` (`social_post` / `fused_signal` at 30 d; the `created_at` loop bug).
- The 48 junk-purge archives from 2026-10-11 have no tripwire records. A backfill needs a `state-write`
  grant.

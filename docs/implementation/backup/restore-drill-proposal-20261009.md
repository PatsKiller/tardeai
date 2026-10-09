# Backup and recovery coverage: inventory, gate, and monthly restore drill proposal

Status: PROPOSED. The gate and manifest ship in this PR. The drill is a proposal only.
as_of: 2026-10-09
Measured at: base 3b5c24856 (origin/main), host read-only 2026-10-09 10:30–11:15 EDT
Authority: READ_ONLY_ADVISORY. Nothing here was run, installed, restored or deleted. No backup ran.
Owner: Agent A (supervisor), operator decides section 5.

## 0. Why

Operator question 2026-10-09: "should each push check whether it needs to edit the recovery
scripts, to keep backup and recovery in sync?" Agreed answer: a CI check that **fails when a change
adds something backup/restore does not cover, and names the gap**. It never edits a recovery script.
The author updates `config/backup_coverage_manifest.json` in the same PR.

- Gate: `python3 scripts/check_backup_coverage.py --fail-on-new`, run in the required cio-hardening
  job through GATES entry `backup_coverage_gate_20261009`
  (`tests/test_backup_coverage_gate_20261009.py`). The workflow file is not touched.
- Manifest: `config/backup_coverage_manifest.json` (`BackupCoverageManifest@v1`). It holds 15 mechanisms
  and 37 asset classes. Each class has a mechanism, a coverage of FULL, PARTIAL or NONE, a restore
  procedure, and a gap note when coverage is PARTIAL or NONE.
- Baseline: `config/backup_coverage_baseline.json` (`BackupCoverageBaseline@v1`) lists 58 known gaps.
  It works as a ratchet. A new gap fails the gate. A baselined gap is reported. A baseline entry that
  is no longer a gap is reported so the list can shrink.

The gate reads these declared assets. Every input is a repo file, so CI and a laptop give the same
verdict:

| Kind | Source | Count today |
|---|---|---|
| `store:` | `config/data_source_authority.json` domains | 52 |
| `persistent_tree:` | `served_from.linked_dirs`, `persistent_state_root.py` PERSISTENT_TREES, `persistent_overlay.py` OVERLAY_RELS | 10 |
| `unit:` | `config/systemd/user/*` (unit files and `.d` dirs) | 132 |
| `secret:` | `config/secret_registry.yaml` names | 21 |
| `pg_table:` | CREATE TABLE in `migrations/`, `sql/migrations/`, `sql/*.sql`, `linux_port_v2/linux/migrations/` | 405 |
| fixed | databases, roles, n8n DB/workflows/key, coordination ledger, crontab, host units/drop-ins, code, docs, local secrets, memory, apps | 17 |
| `ps:` | `--state-root <dir>` only: the top-level entries of persistent-state and of `persistent-state/data` (a host check, never run in CI) | 21 |

The rules for adding an asset:

- A store, unit, secret or persistent tree must be listed by its exact id. A wildcard cannot let a new
  one through.
- Tables are matched by schema pattern, because pg_dump covers a whole schema. A table in an
  excluded schema becomes a new gap. A new schema is unmapped until someone adds its pattern.
- The gate also checks the manifest's pg claim against the backup script. It parses
  `--exclude-table-data` from `linux_launchers/run_pg_backup.sh`, so a new exclusion fails the gate
  until the manifest is updated.

Result on this branch: 637 declared assets, 594 covered, 43 known gaps (58 with `--state-root`),
0 new gaps, 0 unmapped. PASS.

## 1. Inventory (read-only, measured 2026-10-09)

Commands used: `crontab -l` (1,047 lines), `systemctl --user list-timers --all`, `systemctl --user
cat` on the backup units, `ls` and `du` of persistent-state, `df -h`, one read-only Postgres session
(`pg_database` and `pg_namespace` only), and reads of receipts under
`persistent-state/data/runtime` and `persistent-state/backups/n8n`.

### 1.1 Mechanisms

| Mechanism | What | Where to | How often | Restore drilled? |
|---|---|---|---|---|
| pg_dump_local | plain `pg_dump` of trade_ai, gzip. Table **data** of `intelligence.*` and `memory_r10_m2.*` is excluded (`linux_launchers/run_pg_backup.sh:82-83`, because RLS blocks COPY) | `~/db_backups/trade_ai_<stamp>.sql.gz`, keep 1, same disk | daily 02:30, step `portfolio_backup` (`run_portfolio_maintenance_pipeline.sh:123`), `tradeai-portfolio-backup-cadence.timer` | **Never.** No receipt of a restore into a scratch database. `backup_verify.py` checks only that files exist. |
| db_offsite | newest dump, gpg AES-256, to Drive `Trade_AI_Backups`, keep 1 | Drive | weekly-gated (`run_portfolio_maintenance_pipeline.sh:130`); stamp 2026-10-08 02:56 | Decrypt round-trip claimed for 2026-07-17 (`docs/runbooks/BARE_METAL_RECOVERY.md:88`). No receipt. Never loaded into Postgres. |
| env_offsite | `config/broker_credentials.env` + `.env` and `.env.*`, dereferenced | Drive, keep 7 | daily | same 2026-07-17 claim |
| memory_offsite | Claude file memory | Drive, keep 7 | daily | same |
| ops_offsite | `crontab -l` (`backup_secrets_state.sh:73`); `~/.config/systemd/user/*.service` and `*.timer` (`:74`, **no `.d` drop-ins**); dpkg, pip and ollama manifests; pg conf; `.pgpass`; gog auth | Drive, keep 7 | daily | same |
| data_offsite | dev-tree `data/` dereferenced (`:126`) **excluding `data/runtime`**. It follows only the six dev-tree symlinks (audit, cio, health, paper_trading, runtime, state) plus `portfolios/state`. | Drive, keep 1 | weekly-gated; stamp 2026-10-08 02:52 | same |
| apps_offsite | `~/.openclaw` subset + `~/nyc-dof-auction` | Drive, keep 1 | weekly-gated | same |
| n8n_lab_dump_local | `pg_dump -Fc` of the n8n lab DB inside `m8m-n8n-db` (`scripts/n8n_lab_backup.sh:37`) | `persistent-state/backups/n8n`, keep 14, **same disk** | nightly 01:15, step of platform-maintenance-nightly (`run_platform_maintenance_pipeline.sh:132`); last receipt 2026-10-09T05:15Z ok, 157 tables | **Yes.** `N8nLabRestoreDrill@v1` 2026-10-07T14:40Z: 157/157 tables, 4 workflows, drill DB dropped |
| n8n_lab_restore_drill | throwaway DB restore inside the lab container | receipt only | weekly Sun 03:00, step of platform-maintenance-weekly (`:150`). **Not fired on schedule yet.** The 10-07 run was manual. | the only scheduled restore drill |
| backup_verify (monthly) | checks that a dump exists and state files are fresh | Telegram report | platform-maintenance-monthly (`:158`) | Not a restore. **Defect:** it looks under `<release>/backups/db` (`scripts/backup_verify.py:31`), not `~/db_backups`, so the 2026-10-01 run reported `FAIL: 1 backup_dir not found` |
| git_remote | tracked code, config, docs, unit files, workflow JSON | GitHub | per merge | clone-equivalent on every worktree; no bare-metal drill |
| generated_docs_git | gitignored generated docs | branch `generated-docs-backup` | crontab line 541, 23:50 daily (NO_SIGNAL) | never |
| drive_docs_sync | CURRENT `docs/` + dev code mirror | Drive | crontab line 1031, hourly `:05` (`run_drive_syncs.sh`) | never (it is a mirror) |
| claude_memory_drive | `~/.claude/sync-memory-to-drive.sh` (outside the repo) | Drive | crontab line 611, 03:10 | never |
| bitwarden_sm | all registry secret values (source of truth since 2026-07-21, `backup_secrets_state.sh:29-33`) | Bitwarden SM | per rotation | every `sm-render` reads values back. No new-host drill. |
| bitwarden_vault_operator | gpg backup passphrase + gog keyring password | operator vault | on rotation | round-trip verified 2026-07-17 (runbook) |

`tradeai-backup-enforcer.timer` runs hourly. It enforces retention only (`backup_enforcer.py`, max 1
local dump). `scripts/backup_all.sh` is the manual "refresh every family now" button.
`scripts/full_system_backup.py` is not scheduled: 0 crontab lines and no pipeline step.

### 1.2 Stores and layout

- Postgres: databases `trade_ai` (23 GB) and `postgres` (7.5 MB). trade_ai has three schemas:
  `public` (682 tables), `intelligence` (11), `memory_r10_m2` (6). Migrations also declare
  `agentic_runtime`, `memory_r10_shadow` and `tradeai_memory_shadow`, none of which exists in the
  live database.
- persistent-state top level: `PERSISTENT_STATE_ROOT.json archive backups config data exports logs
  state tools`.
- `persistent-state/data`: `active_trader audit cio governance health hermes options_intent
  paper_trading portfolios research runtime state`.
- Dev-tree `data/` symlinks into persistent-state: `audit cio health paper_trading runtime state`,
  plus `portfolios/state`. Nothing else is linked.
- Live-write check (files modified since 2026-10-08):
  - persistent-state `active_trader` 79, `governance` 6, `options_intent` 3.
  - dev-tree `active_trader` 3. Dev-tree `governance` and `options_intent` do not exist.
- The coordination ledger is `persistent-state/data/governance/n8n_coordination_ledger.sqlite`
  (`scripts/lib/n8n_coordination_ledger.py:102`).
- Disk: `/` has 468 GB with 60 GB free (87% used). That is already below the 15% warn floor in
  `config/backup_policy.yaml`.

### 1.3 What is backed up, and what is not

Covered with an offsite copy:

- the public-schema data (weekly offsite; RPO up to 7 days)
- crontab and installed `.service` and `.timer` files (daily)
- the symlinked persistent dirs `audit cio health paper_trading portfolios/state state` (weekly)
- secrets (Bitwarden SM)
- local-only secrets (env_offsite + vault)
- code, docs and workflow JSON (git)
- Claude memory and OpenClaw/DOF apps

Not covered. These are the 58 baseline gaps, grouped by manifest class:

1. **intelligence and memory_r10_m2 table data** (17 tables + 5 authority stores). The data is
   excluded from pg_dump. Only the DDL is dumped. That covers embeddings, GIR, heartbeats, breaches,
   approval packages, the research index and R10 memory facts.
2. **persistent-state/data/governance**: the n8n coordination ledger sqlite (RunReceipts, claims,
   nonces), approval_packages, maturity_scores, conformance_gate_receipts and platform_conformance.
   No family reaches this directory.
3. **data/runtime**: excluded by design (5.4 GB of logs). It also holds 6 authority stores, among them
   the append-only `model_chooser_receipts`, `supervisor_ladder_receipts`, `supervisor_recoveries`
   and `supervisor_breaches` ledgers, plus the runtime projection of `sector_momentum`.
4. **persistent-state `active_trader`, `options_intent`, `state/` (data_broker, 283 MB),
   `archive`, `exports`, `config`, `tools`, `logs`, `backups`**. Each is live or durable, and none
   is in any family. The n8n dumps in `backups/` sit on the same disk as the database they protect.
5. **Forks**: persistent-state `hermes` and `research` are separate directories from their dev-tree
   namesakes. Only the dev-tree copies are backed up.
6. **Postgres cluster roles**: no `pg_dumpall --globals-only` runs. The runbook recreates roles by
   hand.
7. **Installed systemd `.d` drop-ins**: 35 exist on the host. ops_offsite copies only `*.service` and
   `*.timer`. The repo carries 12 drop-in dirs.
8. **No restore drill** for anything except the n8n lab DB. The offsite families were last proven by
   a decrypt round-trip on 2026-07-17, and no receipt exists.

## 2. How the gate behaves on a PR

| Change in the PR | Gate result | What the author does |
|---|---|---|
| new authority domain, unit file, secret name, persistent tree | FAIL `[NOT IN MANIFEST] <id>` naming the candidate classes | add the id to the class whose mechanism copies it |
| new asset that nothing copies | FAIL `[NEW GAP] <id>` | back it up, or add it to the baseline with a reason the reviewer can challenge |
| new table in public (or another dumped schema) | pass (pg_dump covers it) | none |
| new table in `intelligence` or `memory_r10_m2` | FAIL `[NEW GAP]` | as above |
| new schema | FAIL `[NOT IN MANIFEST]` | add a schema pattern |
| `run_pg_backup.sh` gains or loses an exclusion | FAIL (manifest drift) | update `pg_exclude_table_data` and the classes |
| a gap gets fixed | pass + `[baseline can shrink]` | remove the entry |

## 3. Proposal: monthly restore drill as an n8n lane (AGENTS.md §23)

This is not a new timer or cron line (§9.3, §23.2). It is one lane, `backup-restore-drill-monthly`,
scheduled by n8n and executed on the host by `tradeai-n8n-run-executor.service` through
`coordination/run`.

### 3.1 Artifacts (a follow-up PR, after operator decisions in section 5)

1. `scripts/backup_restore_drill.py --dry-run | --apply --receipt`. A real `--dry-run` prints, per
   class, the source artifact, scratch path, checks and disk estimate, and writes nothing.
2. Registry row in `config/lane_registry.json`: `scheduler.kind = "n8n"`, `expression` = the
   workflow id, cadence `30 4 2 * *` (2nd of the month, 04:30 local; no paid model calls, so §17
   off-peak rules do not bind), and `output_signal`
   `data/runtime/backup_restore_drill_last.json`. This goes in under the registry lock (one
   registry-touching PR in flight).
3. Allowlist entry in `config/n8n_run_allowlist.json`:
   - `command ["$PY","scripts/backup_restore_drill.py"]`
   - `lock /tmp/tradeai_backup_restore_drill.lock` (flock)
   - `dry_run_arg ["--dry-run"]`, `live_arg ["--apply","--receipt"]`
   - `timeout_s 5400`, `market_gate false`, plus the output_signal above
4. Workflow JSON under `docs/implementation/n8n-parallel/workflows/`, generated by the existing
   generator. The operator imports it under a grant (§23.2): shadow (`dry_run`), then one manual
   canary, then live.
5. Receipt `BackupRestoreDrill@v1` with one row per asset class: `{class, artifact, artifact_sha256,
   scratch, checks, result, duration_s}`. The lane's `RunReceipt@v1` is the run evidence; exit 0
   alone is not (§0 rail 8).

### 3.2 Per-class drill, always into a scratch root the drill created

| Class | Drill | Pass criterion |
|---|---|---|
| pg (local dump) | `gunzip -t`, then restore into a **network-less throwaway container** (`pgvector/pgvector:pg17`, `--network none`) on a scratch volume. Never the production cluster on 5432. Then drop the container and volume. | table count per schema equals live `pg_namespace` counts; row counts for 10 named tables within the dump-time window |
| pg (offsite) | `gog drive download` the newest `db_backup_*`, gpg decrypt into scratch, compare sha256 to the local dump of the same stamp | decrypt ok + hash match |
| env, memory, ops, data, apps (offsite) | download the newest of each prefix, decrypt, then **`tar -t` only**. The listing is streamed and never extracted. env contents are never written to disk. | expected member paths present (for example `ops_state/crontab.txt`, `data/portfolios/state/holdings.json`); member count within 10% of the previous drill |
| crontab + units | from the decrypted ops tar, extract `crontab.txt` and the `systemd_user/` listing into scratch and diff against `crontab -l` and `ls ~/.config/systemd/user` (read-only) | diff empty, or only lines edited since that backup's stamp |
| n8n lab DB | read the weekly `N8nLabRestoreDrill@v1`; fail if older than 8 days or not ok | fresh and ok |
| secrets (SM) | read the newest sm-render receipt (names only, never values) | fresh, and every registry name rendered |
| coordination ledger | after gap 2 is fixed: `sqlite3 .backup` copy into scratch + `PRAGMA integrity_check` | `ok` |

Cleanup removes only paths under the drill's own scratch root, and only paths recorded in its own
manifest file for that run. It never touches `~/db_backups`, Drive or any live path.

## 4. Gap fixes this proposal does not make

These are separate PRs, each needing a grant:

- ops_offsite: also copy `*.d` drop-ins, and add `pg_dumpall --globals-only`.
- data_offsite: add `persistent-state/data/{governance,active_trader,options_intent}`, `state/` and
  `backups/n8n`, or a new `state` family. Use `sqlite3 .backup` for the ledger, not a live-file tar.
- A privileged dump for `intelligence.*` and `memory_r10_m2.*` (role with BYPASSRLS, read-only).
- `backup_verify.py`: point at `~/db_backups` (`config/backup_policy.yaml local_pg.dir`).
- The append-only receipt ledgers in `data/runtime`: either move them out of runtime or back them up
  explicitly.

## 5. What the drill needs from the operator

1. **Approve the lane**: id `backup-restore-drill-monthly`, cadence `30 4 2 * *`, scheduler n8n.
2. **Scratch location and disk floor.** A full trade_ai restore needs about 25–30 GB. Free space is
   60 GB, already under the 15% warn floor, and a full restore would cross the 8% critical floor.
   Options:
   - (a) an external or second disk as the scratch root
   - (b) a schema-plus-sample drill only (DDL + 10 tables)
   - (c) free space first
3. **Container image**: allow pulling `pgvector/pgvector:pg17`. Only pg16 images are present, and
   production is v17 per the runbook.
4. **Drive read from the drill**: gog download of the newest artifact per family into scratch, plus
   gpg decrypt with the existing passphrase file. env stays list-only.
5. **Allowlist classification**: confirm that scratch-only cleanup is not "destructive retention"
   under the allowlist never-list (§23.3).
6. **Grants, in order**: config-write for the registry row + allowlist (registry lock), then the
   import, shadow, canary and live grants for the workflow.
7. **Gap decisions (section 1.3)**: for each item, back it up or accept it. An accepted gap stays in
   the baseline with the operator's reason.

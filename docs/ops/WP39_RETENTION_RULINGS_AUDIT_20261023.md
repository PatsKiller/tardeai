# WP-39: retention rulings source and runtime evidence

Design-Task: DSN-20261010-db-retention-iris-P6-T1

All **21 D1–D5/D8 ruling groups have corresponding source/configuration evidence**
on `325ff34f2b3b272090b78d5210a2847c8c30bd2a`. The existing hermetic retention
suites pass **90 tests**. This is source coverage, not 21 accepted runtime
outcomes: per-ruling production acceptance remains `NOT_MEASURED`.

The approval record is
`/home/johnclaw/n8n-maturity-verification/packets/retention-all-managed/OPERATOR_DECISION.md`
(October 21, “Approve all leans”). This audit changes documentation only; it does
not change policy, schedules, retention windows or data.

## Ruling map

The companion [21-row matrix](packets/retention-rulings-audit-20261023/rulings.csv)
records source paths, existing test references, runtime boundaries and next
actions for each ruling. [Verification evidence](packets/retention-rulings-audit-20261023/VERIFICATION.json)
preserves source hashes and a bounded, read-only cached runtime observation.

| Ruling | Source/configuration finding |
|---|---|
| D1 | `market_quotes` keeps approved hard-delete 90d; archive growth/total caps are 2 GB/month and 25 GB. |
| D2 | Both Schwab stream tables keep approved hard-delete 7d. |
| D3.1 | Options snapshots are archive/delete 45d; both inline prune entry points are retired. |
| D3.2 | YouTube managed purge archives first; processor delegates to it. The registry still explicitly says the separate host inline purge requires operator retirement. |
| D3.3 | News guard archives dependent rows before parent removal. |
| D3.4 | RSS stub cleanup uses managed archive-first purge. |
| D3.5 | Reports purge archives `telegram_outbox` and other managed tables. |
| D4.1 | Health snapshot inline 90d purge removed; registry owner retains 30d, archive-first. |
| D4.2 | Score history has one registry owner 21d; thinning/self-tune duplicate purge removed. |
| D4.3 | Market movers has registry 7d archive-first; inline prune retired. |
| D4.4 | Document mentions remain an unarchived derived projection under external policy. |
| D5.1 | SIEM reads the 30d alert-events registry window. |
| D5.2 | Archived research follows librarian 180d by `created_at`. |
| D5.3 | Thread membership is `KEEP_FOREVER` and excluded from comms purge. |
| D5.4 | Redundant external-research self-tune purge removed. |
| D8.1 | Log head is archived/verified before truncation; surplus tails are archived. |
| D8.2 | Backups write `.part`, verify gzip and rename; enforcer skips young files for 2h. |
| D8.3 | Unique release-local data archives first; archive failure retains the release. |
| D8.4 | News and weekly/monthly report removal archives output first. |
| D8.5 | Scalp receipt 30d pruning archives first; archive failure retains files. |
| D8.6 | Dead ingestion-summaries file-prune row is absent. |

The policy validator reports 140 rows: 11 `KEEP_FOREVER`, 29
`ARCHIVE_THEN_DELETE`, 97 `DELETE`, and no errors. The remaining three rows use
external policy. All 25 relevant source/config files were byte-identical to files
under CURRENT at the observation, whose directory was
`d0c8b70d8-main-exact-phase2-20261023-182515`. This compares installed files; it
does not independently establish which code each running process loaded.

## Natural cached evidence is partial

The existing nightly receipt is timestamped **2026-10-23T05:15:44Z**, with served
SHA `f7c1e96cbcab399082de186e6367fa834df48e1c`. Its retention children report
exit0, including `db_retention`; the parent reports **failed** because
`report_db_hygiene` failed. These are historical cached observations, not a fresh
database query or current-head execution proof.

The retained retention log reports 122,530 rows removed and 118,132 archived
first. The 4,398 difference exactly matches its `market_quotes` line, an approved
hard-delete exception. Arithmetic consistency does not independently verify each
archive's contents, restorability or off-box copy.

The accompanying hygiene report still has:

- A database size-budget finding: 16,095,434,419 bytes against its 16 GB budget.
- `hermes_external_research` 526 MB against 256 MB table budget.
- `options_approval_queue` 22 MB without a retention row.
- Eight duplicate-index findings.
- Three stale-window findings: `aegis_steph_escalations` 3 rows,
  `decision_packets` 483 rows and `news_articles` 1 row older than 90+2 days.

These are findings to investigate; this audit authorizes no additional deletion,
index removal, new retention policy or change to the held D11 decisions.

## Remaining actions and verification

1. Operator: supply a fresh approved read-only cron census to verify the exact
   YouTube inline purge is retired. Its registry note explicitly leaves this
   host action outstanding. No crontab was read or changed in this audit.
2. Platform/retention owner: correlate the next authorized nightly receipt with
   its actual deployed SHA, table-level actions, archive manifests and consumer
   tripwires. Preserve the parent failure until its hygiene findings are resolved.
3. Respective data owners: decide the uncovered table and over-budget/stale rows
   under existing authority. Do not turn D11 holds into deletion by inference.
4. Operator/backup owner: demonstrate archive recovery and approved off-box
   backup (D9). An archive directory or empty incident list is not recovery proof.

The existing test command was:

```bash
python -m pytest -q -p no:cacheprovider \
  tests/test_retention_registry_owned_20261021.py \
  tests/test_retention_priority_20261021.py \
  tests/test_retention_all_managed_20261011.py \
  tests/test_retention_registry_20261007.py
python scripts/check_retention_policy.py --fail-on-new --json
```

Tests used isolated fixtures under `$HOME/.cache/rtc`; no live database,
credential load, model call or retention apply occurred. D6/D7/D9/D10/D11 remain
separate rulings: this audit neither arms the disabled source-window experiment
nor changes the requirement for grants, off-box backup or owner decisions.

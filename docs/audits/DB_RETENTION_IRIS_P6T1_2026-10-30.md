# DB retention / Iris — P6-T1 audit: D1–D5/D8 rulings vs `config/data_retention_policy.json`

Status: DRAFT (read-only audit; documentation only)
Design-Task: DSN-20261010-db-retention-iris-P6-T1
as_of: 2026-10-30
Measured at: main `f6023b931584111c4ccd1d6a5943dbc553cb68ca` (== `origin/main`), working tree clean
Authority: `config/data_retention_policy.json`, `scripts/check_retention_policy.py`,
  `docs/ops/WP39_RETENTION_RULINGS_AUDIT_20261023.md` (prior audit), DSN-20261010-db-retention-iris
Supersedes: WP39_RETENTION_RULINGS_AUDIT_20261023.md (source-coverage snapshot)
See also: docs/runbooks/DB_RETENTION.md, AGENTS.md §0 rule 6 / §17 / §24.12

## What P6-T1 requires

Per `docs/designs/DSN-20261010-db-retention-iris.md` P6-T1: **"Audit D1-D5/D8 rulings against
config/data_retention policy and list the unimplemented ones."** This is a read-only audit: it changes no
policy, schedule, retention window or data. It verifies, against the current policy registry, which of the
operator's 2026-10-21 D1–D5/D8 rulings are implemented in source/config, and lists the ones that remain
unimplemented (pending operator action or runtime acceptance).

## Method

Read `config/data_retention_policy.json` (the declarative registry `DataRetentionPolicy@v1`), the
`purge_paths[]` ownership map it carries, and the prior WP39 ruling map. Re-ran the policy validator
read-only. No database, broker, model, credential or `--apply` path was touched.

Fresh validator output (quoted):

```
$ .venv/bin/python scripts/check_retention_policy.py --fail-on-new --json
{"rows": 142, "keep_forever": 13, "archive_then_delete": 29, "delete": 97, "errors": []}
```

Deltas vs the 2026-10-23 WP39 audit (140 rows / 11 KEEP_FOREVER): **+2 rows, +2 KEEP_FOREVER** — the
`cio_prospect` and `cio_prospect_events` rows added 2026-10-24 (KEEP_FOREVER). No errors. No DELETE/ARCHIVE
row was added or removed for the D1–D5/D8 tables in the interim.

## Ruling-by-ruling verification (D1–D5/D8)

| Ruling | Ruling text (approved 2026-10-21) | Config evidence at HEAD | Implemented? |
|---|---|---|---|
| D1 | `market_quotes` DELETE 90d; archive caps 2 GB/month and 25 GB total | `market_quotes` `DELETE`/90d, `archive_first:false`, `archive_first_hold` (OVER_CAP, D1); `archive_growth_cap_gb_month:2.0`, `archive_total_budget_gb:25.0` | ✅ source |
| D2 | `schwab_stream_book` + `schwab_stream_quotes` DELETE 7d, no archive | both rows `DELETE`/7d, `archive_first:false`, `archive_first_hold` (BROKER-ADJACENT, D2) | ✅ source |
| D3.1 | `options_chain_snapshots` archive/delete 45d; inline owner retired | `ARCHIVE_THEN_DELETE`/45d; `options_chain_snapshot_prune` purge_path `state:RETIRED` | ✅ source |
| D3.2 | YouTube managed archive-first; **operator retires inline host purge** | `youtube_transcripts` `EXTERNAL_POLICY`; `purge_youtube_transcripts` `MANAGED` archive-first | ⚠️ partial — inline crontab line is **outside the repo**, retirement still operator-owned |
| D3.3 | news guard archives children before parent | `news_symbol_guard` `MANAGED` archive-first | ✅ source |
| D3.4 | RSS stub cleanup archive-first | `hermes_source_registry_cleanup` `MANAGED` archive-first | ✅ source |
| D3.5 | reports portal archives `telegram_outbox` etc. | `reports_portal_purge` `MANAGED` archive-first | ✅ source |
| D4.1 | health snapshot inline 90d purge removed; registry 30d archive-first | `health_agent_snapshots` `DELETE`/30d `archive_first`; `health_agent_snapshot_prune` `RETIRED` | ✅ source |
| D4.2 | score history one owner 21d; thinning/self-tune purge retired | `hermes_score_history` `DELETE`/21d; `hermes_score_history_retention` `RETIRED` | ✅ source |
| D4.3 | `market_movers` registry 7d archive-first; inline prune retired | `market_movers` `DELETE`/7d `archive_first`; `finviz_market_movers_prune` `RETIRED` | ✅ source |
| D4.4 | `document_mentions` derived projection, no archive | `EXTERNAL_POLICY`; `prune_document_mentions` `UNARCHIVED_BY_RULE` | ✅ source |
| D5.1 | `alert_events` 30d; SIEM follows registry | `alert_events` `DELETE`/30d; `siem_retention_purge` `MANAGED` | ✅ source |
| D5.2 | archived research 180d by `created_at` | `hermes_research_intelligence` `EXTERNAL_POLICY`; `research_critique_retention` note (180d) | ✅ source |
| D5.3 | thread membership KEEP_FOREVER, exempt from comms purge | `communication_thread_membership` `KEEP_FOREVER`; `comms_lifecycle` note (KEPT_TABLES) | ✅ source |
| D5.4 | redundant external-research self-tune purge removed | `hermes_self_tune_purge` note (hermes_external_research purges retired) | ✅ source |
| D8.1 | log head archived/verified before truncate | `rotate_runtime_logs` `MANAGED` | ✅ source |
| D8.2 | backup `.part` verified+renamed; enforcer skips young files 2h | `backup_rotation` note (D8.2) | ✅ source |
| D8.3 | release-local data archives first; failed archive keeps release | `disk_hygiene_enforcer` note (D8.3) | ✅ source |
| D8.4 | news/weekly/monthly report removal archives first | `portfolio_report_rotation` `MANAGED` | ✅ source |
| D8.5 | scalp receipt 30d archive-first | `scalp_cycle_receipts` `MANAGED` | ✅ source |
| D8.6 | dead `ingestion_summaries` file-prune row removed | no `ingestion_summaries` entry in `file_prune[]` (only raw_snapshots, ticker_snapshot_history, catalyst_cache) | ✅ source |

## The unimplemented list (what P6-T1 was asked to produce)

All 21 D1–D5/D8 ruling groups are **present in source/config** at HEAD. The items that remain
**unimplemented / pending** are:

1. **D3.2 — inline YouTube host purge retirement (operator-only, outside the repo).** The registry note reads
   "the inline crontab line is outside the repo and must be retired by the operator … it also never
   authenticates." No fresh cron census was available; a read-only cron census is required to close it. No
   crontab was read or changed in this audit.
2. **D9 — off-box backup of the retention archives (operator install).** Tracked separately as
   DSN-20261010-db-retention-iris-P5 / packet `docs/ops/packets/archive-offbox-20261021`; the install is
   operator-only (§17). Not part of P6-T1's table scope, listed here as the open dependency.
3. **Runtime acceptance — every ruling is `NOT_MEASURED`.** Source/config presence is not a runtime outcome.
   Each ruling still needs its next authorized nightly producer receipt correlated against its deployed SHA,
   table-level action, archive manifest and tripwire (WP39 "remaining actions" items 1–2). This audit does not
   re-measure runtime; it re-confirms source/config coverage.
4. **Open hygiene findings (carried, not re-audited):** `hermes_external_research` over its 256 MB table
   budget; `options_approval_queue` with no retention row; database size near the 16 GB budget; stale windows
   on `aegis_steph_escalations`, `decision_packets`, `news_articles`. These are owner decisions under existing
   authority; they do not turn the held D11 rulings into deletion by inference.

## Verdict

No D1–D5/D8 ruling is missing from the policy registry, and the validator reports 0 errors at 142 rows. The
gap is not missing rows — it is (a) one operator-owned cron retirement (D3.2), (b) operator install of the
off-box sync (D9/P5), and (c) `NOT_MEASURED` runtime acceptance across all rulings. P6-T1's "list the
unimplemented ones" resolves to items 1–4 above; the audit changes nothing and authorizes no deletion.

## Evidence

- `config/data_retention_policy.json` at `f6023b931` (read in full; `policies[]` + `purge_paths[]`).
- `scripts/check_retention_policy.py --fail-on-new --json` → `{"rows":142,…, "errors":[]}` (quoted above).
- `docs/ops/WP39_RETENTION_RULINGS_AUDIT_20261023.md` + `rulings.csv` (prior source-coverage snapshot, 21 groups).

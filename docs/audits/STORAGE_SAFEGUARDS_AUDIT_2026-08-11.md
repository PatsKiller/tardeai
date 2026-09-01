# Storage Safeguards Audit — 2026-08-11

Status:      HISTORICAL
as_of:       2026-08-11T09:14:53-04:00
Measured at: efcc51365 / not measured

## Incident

Health-agent auto-remediation of `db_dump_stale` / `db_dump_missing` / `backup_cadence_stale`
invoked `run_pg_backup.sh` on a short cooldown while dumps take ~10–12 minutes. Combined with
weak local retention, this produced a **backup storm** (~250 GB reported peak; residual
**38 × ~2.3 GB = 86 GB** local dumps observed 2026-08-11 morning).

## Phase 0 — Containment (done)

| Action | Result |
|--------|--------|
| Prune `~/db_backups` to newest full dump only | **1** dump kept (final: `trade_ai_20260811_090357.sql.gz`, **1.9G**) |
| Disk free | **~145 GB → ~229 GB free** (≈84 GB recovered from dumps) |
| Orphan embeddings purged | **60,460** news orphans deleted via Librarian retention |
| Stream/history purge | **~4.1M rows** (stream book/quotes, score history, audits) |
| Disable auto-remediate for dump findings | `never_auto_remediate` + removed from `auto_remediate.finding_types` |
| Local interval | **1200 min (20h)** so only daily cadence should write |
| Local max count | **1** via `backup_enforcer.py` + hourly timer |

Drive `Trade_AI_Backups` already had **one** `db_backup_*` (2026-07-31, 1.8 GB). Policy
`KEEP=1` for db target enforced going forward.

## Backup enforcement

| Component | Role |
|-----------|------|
| `config/backup_policy.yaml` | Single source of truth (max_count, intervals, Drive folder) |
| `scripts/backup_enforcer.py` | Hard-cap local dumps; optional Drive prune |
| `linux_launchers/run_pg_backup.sh` | Calls enforcer after dump; 20h skip; max 1 |
| `tradeai-backup-enforcer.timer` | Hourly reconcile even if dump path skipped |
| `collect_backup_health()` | Alerts on count/bytes exceeded (no auto dump) |

Tests: `tests/test_backup_enforcer.py` (2 passed).

## Librarian / Taxonomy

| Agent | Finding |
|-------|---------|
| **Hermes Librarian** | Dry-run `retention` + `rag_health` OK. **57,757 orphan embeddings** (mostly `news`). Policy orphan_purge_days=30 exists but orphan DELETE not yet wired in `lib/hermes_librarian/retention.py` (only failed queue + research archive). |
| **Iris Taxonomy** | Content **routing** agent (YouTube/keywords), not DB row lifecycle. `iris_*` tables already on TINY (14d) retention. Timer present. |

### content_embeddings

- ~**7.7 GB**, ~2.7k live rows reported by `pg_stat` (TOAST/dead tuples dominate size).
- **Next step:** implement orphan purge in Librarian retention `--apply`, then `VACUUM FULL` or `REINDEX` under maintenance window (not auto-run here).

## Database retention

| Change | Detail |
|--------|--------|
| New policies | `schwab_stream_book/quotes` 7d; `hermes_score_history` 21d; audit tables 30d |
| Apply run | **4,091,016 rows deleted** (incl. ~1.78M each stream book/quotes, 69k score history) |
| FK blockers | `aegis_steph_escalations`, `watchlist_agent_jobs` — child refs; need cascade-order later |
| Report | `scripts/db_storage_report.py` |

Still uncovered large tables (do not auto-delete without design): `content_embeddings`,
`market_ohlcv_bars`, `screener_symbol_membership`, `decision_packets`, `hermes_external_research`.

## Docs hygiene

| Action | Result |
|--------|--------|
| `scripts/docs_hygiene.py --apply` | Pruned **120** generated dryrun/payload files |
| Home archives | Multi-GB tarballs remain for **manual** review (`doc_hygiene_backup_*.tgz`, etc.) — not auto-deleted |

## Verification checklist

- [x] Exactly 1 local full dump
- [x] Drive db_backup count = 1 (pre-existing)
- [x] Health agent cannot storm dumps
- [x] Hourly enforcer timer enabled
- [x] Stream/score_history purge applied
- [ ] Embedding orphan purge + VACUUM FULL (follow-up)
- [ ] Fix backup cadence service failed unit
- [ ] Offsite a fresh db_backup after next daily cadence

## Operator commands

```bash
# Status
.venv/bin/python scripts/backup_enforcer.py --status
.venv/bin/python scripts/db_storage_report.py

# Manual dump (respects 20h interval + cap 1)
bash linux_launchers/run_pg_backup.sh

# Force local cap reconcile
.venv/bin/python scripts/backup_enforcer.py

# Docs generated churn
.venv/bin/python scripts/docs_hygiene.py --apply --report-home
```

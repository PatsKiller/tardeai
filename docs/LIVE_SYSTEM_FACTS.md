# Live System Facts — Authoritative Counts

**Updated:** 2026-06-22 (A1A consolidation)
**Policy:** Do not hard-code table/cron/script/strategy counts in active docs. Point here or regenerate.

## Regenerate

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python3 scripts/generate_system_facts.py
```

Outputs:
- `data/system_facts.json` — machine-readable manifest
- `data/system_fact_drift.json` — docs that still claim stale counts
- `docs/project/SYSTEM_FACTS_LATEST.md` — human summary (Drive-synced; gitignored on main)

## Snapshot (2026-06-22 — regenerate for current)

| Key | Value |
|-----|------:|
| `database.table_count` | 526 |
| `codebase.python_script_count` | 989 |
| `codebase.cron_job_count` | 306 |
| `codebase.strategy_count` | 23 |
| `codebase.sql_migration_count` | 52 |
| `codebase.frontend_page_count` | 94 (v2 page tree; v3 is canonical UI) |
| `database.closed_paper_trades` | 18 |
| `database.open_paper_trades` | 3 |
| `safety.alpaca_mode` | paper |
| `safety.live_trading_gate_allowed` | false |

## What does NOT drift-check

- `docs/CHANGELOG.md` — historical record; past counts are intentional
- *(no `docs/_archive/` — purged 2026-08-16; historical snapshots live in git history / Drive)*
- `docs/project/PHASE*_CLOSEOUT.md` — phase evidence at closeout date

## Canonical docs using live facts

| Doc | Role |
|-----|------|
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | Technical reference — scale via this file |
| `docs/EXECUTIVE_ARCHITECTURE_OVERVIEW.md` | Business overview |
| `docs/CHEAT_SHEET.md` | Operator quick reference |
| `docs/DOCUMENTATION_INDEX.md` | Doc roster + open items |
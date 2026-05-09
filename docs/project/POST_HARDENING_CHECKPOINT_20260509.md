# Post-Hardening Sprint Checkpoint — 2026-05-09

## Validated Baseline Values

| Metric | Value |
|--------|-------|
| DB tables | 249 |
| Python scripts | 321 |
| Strategies | 20 |
| Cron jobs | 141 |
| Holdings value | $1,189,457 |
| Trading mode | PAPER — BLOCKED |
| Doc drift items | 15 |
| Failed tests | None |

## Safety Status

| Check | Status |
|-------|--------|
| ALPACA_MODE | `paper` (explicit in .env) |
| LIVE_TRADING | Not set (defaults to false/blocked) |
| Paper validation gate | BLOCKED — 6 reasons |
| Holdings guard | PASSED ($1,189,457 > $1,000,000) |
| holdings.json authority | File remains authoritative |
| Crontab | Unchanged — proposed files NOT installed |

### Paper Gate Blocked Reasons

1. `policy_live_trading_allowed_false` — DB policy blocks live trading
2. `validation_days_insufficient` — 1/183 days elapsed
3. `closed_trade_sample_insufficient` — 3/100 trades closed
4. `win_rate_below_threshold` — 0.0/0.55
5. `profit_factor_below_threshold` — 0/1.30
6. `governance_not_approved` — no governance approval recorded

## Files and Features Delivered

### New Scripts (13)
- `scripts/audit_config_files.py` — YAML/JSON inventory and classification
- `scripts/import_file_configs_to_db.py` — safe config import to DB with file fallback
- `scripts/config_db_loader.py` — DB-first config loader with file fallback
- `scripts/pipeline_controller.py` — dependency-aware pipeline orchestrator
- `scripts/seed_pipeline_controller.py` — bootstrap pipeline stages from YAML to DB
- `scripts/finviz_health_check.py` — Finviz source health validation
- `scripts/candidate_discovery_orchestrator.py` — multi-source discovery with degraded mode
- `scripts/live_trading_gate.py` — paper validation gate enforcer
- `scripts/generate_system_facts.py` — live facts manifest generator
- `scripts/topic_curator.py` — topic intelligence curation
- `scripts/topic_ingestion.py` — topic data ingestion
- `scripts/discovery_sources/` — 7-file discovery source abstraction package

### SQL Migrations (8)
- `sql/migrations/20260509_config_documents.sql`
- `sql/migrations/20260509_pipeline_controller.sql`
- `sql/migrations/20260509_discovery_source_health.sql`
- `sql/migrations/20260509_paper_validation_gate.sql`
- `sql/migrations/20260509_system_facts.sql`
- `sql/migrations/20260509_topic_curation_layer.sql`
- `sql/migrations/20260509_topic_entity_linking_and_curation.sql`
- `sql/migrations/20260509_topic_monitor_and_gap_fills.sql`

### New DB Tables (15)
`config_documents`, `config_document_history`, `holdings_json_mirror`,
`pipeline_definitions`, `pipeline_stages`, `pipeline_stage_dependencies`,
`pipeline_runs`, `pipeline_stage_runs`, `pipeline_events`,
`data_source_health`, `candidate_discovery_events`,
`paper_validation_policy`, `paper_validation_daily_metrics`,
`governance_approvals`, `system_facts_history`

### API Endpoints (12 new hardening endpoints)
| # | Endpoint | Method | Validated |
|---|----------|--------|-----------|
| 1 | `/api/v2/pipeline-controller/status` | GET | 200 |
| 2 | `/api/v2/pipeline-controller/runs` | GET | 200 |
| 3 | `/api/v2/pipeline-controller/runs/<run_id>` | GET | 200 |
| 4 | `/api/v2/pipeline-controller/runs/<run_id>/stages` | GET | 200 |
| 5 | `/api/v2/pipeline-controller/stages` | GET | 200 |
| 6 | `/api/v2/pipeline-controller/failures` | GET | 200 |
| 7 | `/api/v2/pipeline-controller/runs/<run_id>/retry-failed` | POST | 404 (correct for missing run) |
| 8 | `/api/v2/discovery-source-health` | GET | 200 |
| 9 | `/api/v2/candidate-discovery/recent` | GET | 200 |
| 10 | `/api/v2/paper-validation-status` | GET | 200 |
| 11 | `/api/v2/system-facts` | GET | 200 |
| 12 | `/api/v2/system-fact-drift` | GET | 200 |

### Dashboard
- `/v2/pipeline-controller` — Pipeline Controller page (200 OK)
- Shows pipeline status, stage grid, failures, SLA misses, degraded mode
- Paper validation banner, facts summary, source health

### Config / Launchers
- `config/pipeline_controller.bootstrap.yaml` — 25-stage pipeline definition
- `linux_launchers/run_pipeline_controller.sh`
- `linux_launchers/generate_system_facts.sh`
- `crontab_pipeline_controller_proposal.txt` — proposed, NOT installed
- `crontab_system_facts_proposal.txt` — proposed, NOT installed

### Documentation
- `docs/project/CONFIG_FILE_DB_MIGRATION_AUDIT.md`
- `docs/project/DOC_DRIFT_REVIEW_20260509.md`
- `docs/project/SYSTEM_FACTS_LATEST.md`
- `docs/COST_MODEL.md`

## Crontab Status

Existing crontab is **unchanged**. Two proposed crontab files were generated but
**NOT installed**:
- `crontab_pipeline_controller_proposal.txt`
- `crontab_system_facts_proposal.txt`

These are additive proposals for future manual review and installation.

## Recommended Next Steps

1. **Update stale doc values** — 15 drift items documented in
   `docs/project/DOC_DRIFT_REVIEW_20260509.md`. Primary: update "219 tables" → "249 tables"
   in 5 docs, "14 strategies" → "20 strategies" in MASTER_SYSTEM_DOCUMENTATION.md.
2. **Review proposed crontab entries** — install when ready, not before.
3. **Run pipeline controller in real mode** on a quiet day to validate stage execution.
4. **Monitor paper trade accumulation** — gate requires 100 closed trades (currently 3).
5. **Clean up untracked files** — `126514`, `M` (empty artifacts), `.next/` build dir.

## Rollback Notes

- All SQL migrations are idempotent (CREATE TABLE IF NOT EXISTS). No destructive
  changes were made to existing tables.
- All new scripts are additive — no existing scripts were replaced.
- `scripts/api_v2.py` was modified (POST retry-failed endpoint added, sys import
  bug fixed) — revert commit `eef8daa` to undo.
- DB policy seed (`paper_validation_policy`) uses ON CONFLICT DO NOTHING — safe to
  re-run.
- Config documents imported into DB (38 rows) can be deactivated via
  `UPDATE config_documents SET active=false`.
- holdings.json was never modified. DB mirror is read-only.

## Manual Run Commands

### System facts generation
```bash
.venv/bin/python scripts/generate_system_facts.py
```

### Pipeline controller dry-run
```bash
.venv/bin/python scripts/pipeline_controller.py --pipeline daily --run-label manual --dry-run
```

### Pipeline controller list stages
```bash
.venv/bin/python scripts/pipeline_controller.py --pipeline daily --list-stages
```

### Finviz health check
```bash
.venv/bin/python scripts/finviz_health_check.py
```

### Degraded discovery simulation
```bash
.venv/bin/python scripts/candidate_discovery_orchestrator.py --dry-run --simulate-finviz-failure
```

### Paper validation gate
```bash
.venv/bin/python scripts/live_trading_gate.py --status --json
.venv/bin/python scripts/live_trading_gate.py --assert-safe
```

### Holdings guard
```bash
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000, 'WIPED'; print(f'Holdings OK: \${v:,.0f}')"
```

### Config audit
```bash
.venv/bin/python scripts/audit_config_files.py
```

### Config import (dry-run first, then apply)
```bash
.venv/bin/python scripts/import_file_configs_to_db.py --dry-run
.venv/bin/python scripts/import_file_configs_to_db.py --apply
```

---

Live trading remains blocked. Paper mode remains active. holdings.json remains authoritative.

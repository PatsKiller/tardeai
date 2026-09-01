# Strategy & Monitoring — Audit Remediation (2026-06-26)

Status:      ACTIVE
as_of:       2026-06-26T21:35:28-04:00
Measured at: efcc51365 / not measured

Backup taken before changes: `backups/pre-strategy-monitoring-*/` (crontab-live, `atm_config.yaml`, `pullback_macd_screener.yaml`).

## Implemented

### 1. `pullback_macd_reversal` strategy YAML
- **File:** `config/strategies/pullback_macd_reversal.yaml`
- Aligns with `config/pullback_macd_screener.yaml` `default_strategy_id`
- Appears in `/api/v2/strategy-intelligence` like other strategies

### 2. Proposal lifecycle monitor (cron restored)
- **Script:** `scripts/install_strategy_monitoring_cron.sh`
- **Schedule:** 16:30, 18:00, 06:00, 06:30 ET weekdays — `proposal_monitor.py --pending --apply`
- **Log:** `logs/proposal_monitor.log`

### 3. Daily strategy audits
- **Script:** `scripts/run_scheduled_strategy_audits.sh`
- **Schedule:** 17:05 ET weekdays
- Runs `audit_automated_open_trades.py` + `audit_proposal_source_parity.py` (fails if `all_biases_fixed` is false)
- **Log:** `logs/strategy_audits.log`

### 4. Enrichment throughput (84-pending backlog)
- **`auto_enrichment_runner.py`**
  - Prioritizes `live_2fa` / Schwab broker lane first
  - **Curated light path** for `paper_atm` watchlist/pullback rows (price + risk + readiness; skips heavy technical/LLM)
  - Default batch `--limit 40` (cron updated)
- **`proposal_enrichment_loop.py`**
  - Broker lane first in queue
  - Cron limit raised **5 → 15** (`crontab_backup.txt`)

### 5. Job coverage registry
- **`job_coverage_monitor.py`** now tracks: ATM, protection pipeline, watchlist bridge, pullback screener, auto_proposal, enrichment loop, strategy audits

### 6. Strategy intelligence API
- **`/api/v2/strategy-intelligence`** includes DB-active strategy IDs missing from YAML (`source: db_active`, `governance_state: DB_ACTIVE_NO_YAML`)

## Install on server

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
chmod +x scripts/install_strategy_monitoring_cron.sh scripts/run_scheduled_strategy_audits.sh
bash scripts/install_strategy_monitoring_cron.sh
# Optionally align enrichment lines from crontab_backup.txt (auto_enrichment --limit 40, enrichment_loop --limit 15)
```

## Deferred (P1)

- Restore `min_classifier_health: 0.5` in `atm_config.yaml` after ≥3 closes per active strategy
- Re-enable or replace commented `open_trade_monitor.py` cron line
- Legacy ID migration: `swing_trade` → `swing_breakout`, `earnings_catalyst` → `earnings_post_momentum`
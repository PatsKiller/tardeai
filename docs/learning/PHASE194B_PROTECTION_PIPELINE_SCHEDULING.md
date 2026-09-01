# PHASE 194B — Protection Learning Pipeline Scheduling

Status:      HISTORICAL
as_of:       2026-06-02T13:01:40-04:00
Measured at: efcc51365 / not measured

**Alpaca paper only · read-only/advisory chain · no order/stop/GO-WAIT/strategy mutation**

---

## Orchestrator: `scripts/run_protection_pipeline.sh`
Runs the protection-learning chain in dependency order, each step best-effort (a failure logs a
WARN and the chain continues):
1. `verify_paper_trade_broker_stops.py` — persist/verify broker stop metadata (190B)
2. `trade_execution_analyzer.py` — bar-based MFE/MAE **percent** on newly closed trades (194)
3. `profit_protection_advisory.py` — TradeAI advisories (191)
4. `hermes_profit_protection_check.py` — Hermes second opinion (191E)
5. `generate_paper_protection_adjustment_proposals.py` — adjustment proposals (192D; now
   idempotent — supersedes prior PROPOSED rows so cron doesn't bloat the table)
6. `reconcile_protection_advisory_outcomes.py` — close-loop outcomes (193/194)

**Excluded by design:** `apply_paper_protection_adjustment.py` (the only step that can modify a
paper order) is **NOT** in the pipeline — it runs only on explicit operator approval.

## Cron (system TZ America/New_York, holiday-gated via `market_day_gate.sh`)
```
*/30 9-16 * * 1-5  ... run_protection_pipeline.sh   # market-hours refresh
30 20  * * 1-5     ... run_protection_pipeline.sh   # after-close reconcile (MFE on day's closes)
```
Logs: `logs/protection_pipeline.log` (per-step) + `logs/protection_pipeline_cron.log`.
Rollback: `crontab -l | grep -v phase194 | crontab -` (backup in `backups/crontab_pre_phase194_*`).

## Idempotency / safety
- Advisories + outcomes upsert / latest-wins (API uses `DISTINCT ON ... ORDER BY created_at DESC`).
- Proposals supersede prior `PROPOSED` rows each run → no duplicate growth; APPLIED rows preserved.
- Smoke-tested end-to-end (rc=0); proposal table stays bounded (latest set PROPOSED, rest SUPERSEDED).

## Result
The learning loop now refreshes automatically during market hours and finalizes after close, so as
ANY/SNOW and future advised trades close, their outcomes (give-back, profit-left-on-table, advisory
accuracy) populate without manual runs.

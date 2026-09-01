# Monday ATM Burn-in Command Packet — 2026-05-26

Status:      HISTORICAL
as_of:       2026-05-22T20:13:41-04:00
Measured at: efcc51365 / not measured

**Window:** After 09:35 ET Monday
**ATM mode:** active (limited paper caps already set)

---

## Preflight (09:30 ET)

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
export PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)

# Safety
grep ALPACA_MODE .env                    # must be: paper
grep LLM_DISABLE_LIVE_EXECUTION .env     # must be: true

# Holdings
python3 -c 'import json; d=json.load(open("data/portfolios/state/holdings.json")); print(d["portfolio_totals"]["total_value"])'

# ATM mode (should already be active with caps)
psql -h localhost -U trade_ai -d trade_ai -c "SELECT mode, config_hash FROM atm_state WHERE id=1;"

# B-1 expired? (date must be >= 2026-05-26)
date +%Y-%m-%d
grep observation_end config/atm_config.yaml
python3 -c "import sys;sys.path.insert(0,'scripts');from atm_config_manager import is_bucket2_excluded;print('swing_trade excluded:', is_bucket2_excluded('swing_trade'))"

# Daily counter (must be 0 — new day)
psql -h localhost -U trade_ai -d trade_ai -c "SELECT COUNT(*) FROM atm_decision_log WHERE decided_at::date=CURRENT_DATE AND decision='approved';"

# Concurrent ATM positions
psql -h localhost -U trade_ai -d trade_ai -c "SELECT COUNT(*) FROM paper_trades WHERE status='open' AND atm_decision_id IS NOT NULL;"

# Stop reconciliation
.venv/bin/python scripts/reconcile_stop_v21_broker_stops.py --dry-run --verbose
```

**All must pass before market open.**

---

## Observe (09:35+ ET)

ATM is already active with caps. It will auto-evaluate on the next */15 cycle.

```bash
# Watch ATM log
tail -f logs/atm.log

# Check enrichment
curl -s http://localhost:7777/api/v2/atm/enrichment-status | python3 -m json.tool

# Check queue preview
curl -s http://localhost:7777/api/v2/atm/queue-preview | python3 -m json.tool
```

---

## Post-Cycle Verification

```bash
# ATM decisions today
psql -h localhost -U trade_ai -d trade_ai -c "SELECT decided_at, symbol, strategy_id, decision FROM atm_decision_log WHERE decided_at::date=CURRENT_DATE ORDER BY decided_at DESC LIMIT 10;"

# New trades
psql -h localhost -U trade_ai -d trade_ai -c "SELECT id, symbol, status, entry_price, stop_loss, broker_order_id FROM paper_trades WHERE created_at::date=CURRENT_DATE ORDER BY created_at DESC LIMIT 5;"

# Stop reconciliation
.venv/bin/python scripts/reconcile_stop_v21_broker_stops.py --dry-run --verbose
```

---

## Freeze Conditions

Freeze ATM immediately if:
- Trade without broker-native stop
- Stop reconciliation MISSING_BROKER_STOP
- Quote fetch failure during approval
- Audit log write failure
- >1 trade approved in one day
- Concurrent ATM positions > 6
- Non-paper order detected

```bash
# Emergency freeze
psql -h localhost -U trade_ai -d trade_ai -c "UPDATE atm_state SET mode='dry_run', last_state_change_by='operator_freeze' WHERE id=1;"
```

---

## Current Caps

| Limit | Value |
|-------|-------|
| max_new_per_day | 1 |
| max_concurrent | 6 |
| per_trade_risk | 0.10% |
| daily_loss_pause | 0.25% |
| broker stop | REQUIRED |
| operating hours | 09:35–15:30 ET |
| same_day_skip | momentum_scalp, gap_and_go |

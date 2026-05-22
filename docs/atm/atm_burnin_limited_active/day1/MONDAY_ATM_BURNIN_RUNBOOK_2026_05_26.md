# Monday ATM Burn-in Runbook — 2026-05-26

**Earliest run:** Monday 2026-05-26 after 09:35 ET
**Mode:** Limited paper-active (1 entry max)

---

## Step 1: Preflight (09:30 ET)

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Safety
grep ALPACA_MODE .env                    # must be: paper
grep LLM_DISABLE_LIVE_EXECUTION .env     # must be: true

# Holdings guard
python3 -c 'import json; d=json.load(open("data/portfolios/state/holdings.json")); print(d["portfolio_totals"]["total_value"])'

# ATM status
export PGPASSWORD=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)
psql -h localhost -U trade_ai -d trade_ai -c "SELECT mode FROM atm_state WHERE id=1;"

# Daily counter (must be 0 for new day)
psql -h localhost -U trade_ai -d trade_ai -c "
  SELECT COUNT(*) FROM atm_decision_log
  WHERE decided_at::date = CURRENT_DATE AND decision = 'approved';"

# Concurrent ATM positions (must be < 2)
psql -h localhost -U trade_ai -d trade_ai -c "
  SELECT COUNT(*) FROM paper_trades
  WHERE status='open' AND atm_decision_id IS NOT NULL;"

# Stop reconciliation
.venv/bin/python scripts/reconcile_stop_v21_broker_stops.py --dry-run --verbose
```

**STOP if any check fails.** All must pass before continuing.

---

## Step 2: Apply Config (09:33 ET)

Edit `config/atm_config.yaml`:
```yaml
defaults:
  position_limits:
    max_concurrent: 2
    max_new_per_day: 1
    max_pct_per_trade: 0.10
  kill_switches:
    daily_loss_pct_hard_pause: 0.25
```

---

## Step 3: Enable Active Mode (09:35 ET)

```bash
psql -h localhost -U trade_ai -d trade_ai -c "
  UPDATE atm_state SET mode='active', last_state_change_by='atm-burnin-day1',
  last_state_change_at=NOW() WHERE id=1;
  INSERT INTO atm_state_events (old_mode, new_mode, changed_by, reason)
  VALUES ('dry_run', 'active', 'atm-burnin-day1', 'Limited paper-active burn-in Day 1');"
```

---

## Step 4: Wait for One ATM Cycle (~15 min)

ATM cron fires at */15. Wait for the next tick.

Monitor: `tail -f logs/atm.log`

---

## Step 5: Verify Result

```bash
# ATM decisions
psql -h localhost -U trade_ai -d trade_ai -c "
  SELECT decided_at, symbol, strategy_id, decision
  FROM atm_decision_log WHERE decided_at::date = CURRENT_DATE
  ORDER BY decided_at DESC LIMIT 10;"

# New trades
psql -h localhost -U trade_ai -d trade_ai -c "
  SELECT id, symbol, status, entry_price, stop_loss, broker_order_id
  FROM paper_trades WHERE created_at::date = CURRENT_DATE
  ORDER BY created_at DESC LIMIT 5;"

# Stop reconciliation
.venv/bin/python scripts/reconcile_stop_v21_broker_stops.py --dry-run --verbose
```

---

## Step 6: Freeze After One Cycle

```bash
psql -h localhost -U trade_ai -d trade_ai -c "
  UPDATE atm_state SET mode='dry_run', last_state_change_by='atm-burnin-day1-freeze'
  WHERE id=1;"
```

---

## Immediate Freeze Conditions

Freeze ATM immediately if:
- Any trade created without broker-native stop
- Stop reconciliation shows MISSING_BROKER_STOP
- Quote fetch fails during approval
- Audit log write fails
- More than 1 trade approved in one day
- Concurrent ATM positions exceed 2
- Any non-paper broker order detected

---

## Allowed Strategies

- `dividend_growth_compounder`
- `reit_income`
- `core_growth_compounder`

All others: deferred or rejected by ATM gates.

---

## Risk Limits

| Limit | Value |
|-------|-------|
| Max entries/day | 1 |
| Max concurrent | 2 |
| Per-trade risk | 0.10% (~$120) |
| Daily loss pause | 0.25% (~$300) |
| Broker stop | REQUIRED |
| After-hours | NO execution |

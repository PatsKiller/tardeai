# Getting Started — Momentum Scalp Hermes Swarm

**Recommended first iteration:** Orchestrator + Live Monitor + Stop Adjustment (Phase 1).

---

## Prerequisites

1. Trade AI v12 server running (`http://127.0.0.1:7777`)
2. `MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md` in `docs/`
3. Hermes `tradeai12b` profile with file read/write tools enabled (System → Hermes)
4. OpenClaw Telegram integration for approvals

---

## Step 1 — Verify state directory

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
ls state/momentum_scalp/
# Should show: open_scalps.json, portfolio_heat.json, regime_state.json, etc.
```

---

## Step 2 — Dry-run Live Monitor (once)

```bash
.venv/bin/python3 scripts/hermes_scalp_live_monitor.py --once
```

Expect JSON output with `positions`, `alerts`, `heat_pct`. State files should update with `updated_at` timestamps.

---

## Step 3 — Dry-run Orchestrator (once)

```bash
.venv/bin/python3 scripts/hermes_scalp_orchestrator.py --once --json
```

Review `routes` and `pending_approvals`. No broker writes occur.

---

## Step 4 — Start persistent daemons (tmux)

```bash
chmod +x linux_launchers/hermes_scalp_swarm_tmux.sh
./linux_launchers/hermes_scalp_swarm_tmux.sh start
tmux attach -t hermes-scalp-swarm
```

Windows:
- `orchestrator` — 60s tick, routes + approvals
- `live_monitor` — 30s tick, state sync
- `health` — API status watch

---

## Step 5 — Verify in Command Center

1. Open `http://127.0.0.1:7777/v3/` → **Hermes**
2. Select **Momentum Scalp Swarm** fleet tab
3. Check Overview → Shared State Files show recent timestamps
4. Workflow tab → 7-agent graph with Orchestrator at top

---

## Step 6 — Confirm Stop Management integration

Portfolio → **Stop Management** tab should show:
- Regime column (from `momentum_scalp_regime.py`)
- Dynamic stoplight thresholds
- Policy suggestions in Reasons column

---

## Phase 2 — Signal Scout + Entry Validation (included in tmux)

```bash
.venv/bin/python3 scripts/hermes_scalp_signal_scout.py --once
.venv/bin/python3 scripts/hermes_scalp_entry_validation.py --once
```

The tmux launcher starts all Phase 1+2 daemons. Qualified signals land in `qualified_signals.json`; validated entries queue to `pending_approvals.json` for Telegram approval.

## Phase 3 — Exit Intelligence + Post-Trade Review

```bash
.venv/bin/python3 scripts/hermes_scalp_exit_intelligence.py --once
.venv/bin/python3 scripts/hermes_scalp_post_trade_review.py --once --llm --lane grok
.venv/bin/python3 -m pytest tests/test_hermes_scalp_phase3.py -v
```

Dry test guide: `docs/hermes/momentum_scalp_swarm/PHASE_3_DRY_TEST.md`

Outputs:
- `exit_suggestions.json` — Street-extended profit alerts
- `post_trade_reviews.json` — §5 stop-quality critiques per closed trade
- `validation_tracker.json` — synced §6 gate metrics

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| State files not updating | Check `logs/hermes_scalp_live_monitor.log` |
| API 404 on scalp-swarm | Restart server: `linux_launchers/restart_server.sh` |
| Heat always null | Set `paper_account_equity` in `config/strategies/momentum_scalp.yaml` |
| Lock timeout | Ensure only one writer per state file |
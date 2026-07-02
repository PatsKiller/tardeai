# Phase 3 Dry Test Report — Exit Intelligence + Post-Trade Review

**Date:** 2026-07-02  
**Agents:** `hermes_scalp_exit_intelligence.py`, `hermes_scalp_post_trade_review.py`  
**Mode:** Deterministic (no broker writes, no LLM required)

---

## 1. Purpose

Validate Phase 3 agents before enabling in the full tmux swarm:
- **Exit Intelligence** — Street consensus vs open scalp profit extension
- **Post-Trade Review** — §5 four stop-quality questions + §6 validation tracker sync

---

## 2. Commands

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Unit tests
.venv/bin/python3 -m pytest tests/test_hermes_scalp_phase3.py -v

# Agent dry runs
.venv/bin/python3 scripts/hermes_scalp_exit_intelligence.py --once
.venv/bin/python3 scripts/hermes_scalp_post_trade_review.py --once

# Full swarm status (after server restart)
curl -s http://127.0.0.1:7777/api/v2/hermes/scalp-swarm/status | python3 -m json.tool
```

---

## 3. Expected Outputs (empty book)

With **0 open scalps** and **N closed trades**:

### Exit Intelligence

```json
{
  "scanned": 0,
  "suggestions": 0,
  "enqueued": 0,
  "street_coverage": 0
}
```

State file: `state/momentum_scalp/exit_suggestions.json` updated with `updated_at` timestamp.

### Post-Trade Review

```json
{
  "new_critiques": <N unreviewed closed trades>,
  "total_reviewed": <cumulative>,
  "validation_closed_trades": <from scalp_stop_validation_tracker>,
  "validation_overall": "INSUFFICIENT SAMPLE — gate needs >=150 closed trades",
  "critiques": [ ... ]
}
```

Each critique includes:
- `initial_stop_vs_mae` (Q1)
- `trail_activation_correct` (Q2 — notes L3 config-OFF)
- `r_left_on_table` / `r_left_on_table_narrative` (Q3)
- `recommended_params` (Q4)
- `stop_quality_score` (1–5 heuristic)

State files:
- `state/momentum_scalp/post_trade_reviews.json`
- `state/momentum_scalp/validation_tracker.json` (synced from tracker)

---

## 4. Scenario Tests (unit)

| Scenario | Agent | Expected |
|----------|-------|----------|
| Long +10% above Street μ at +2.5R | Exit Intelligence | `partial_profit_extended_above_street` |
| Stop above Street μ | Exit Intelligence | `stop_over_consensus` |
| Closed trade with MAE 0.3R, MFE 3R | Post-Trade Review | `optimal` MAE, `r_left_on_table` computed |
| < 150 closed trades | Post-Trade Review | `validation_overall` = INSUFFICIENT SAMPLE |

---

## 5. Integration Checklist

- [ ] `exit_suggestions.json` writes atomically
- [ ] Material exit suggestions appear in `pending_approvals.json`
- [ ] Orchestrator audit logs exit routes (no duplicate enqueue)
- [ ] `validation_tracker.json` matches `scalp_stop_validation_tracker.py --json`
- [ ] HermesHub Overview shows Exit suggestions + Post-trade reviews + Validation gate
- [ ] Tmux launcher includes `exit_intelligence` + `post_trade_review` windows

---

## 6. Policy Alignment

| Rule | Agent | Section |
|------|-------|---------|
| Price extended vs Street | Exit Intelligence | §4 monitoring |
| Stop over consensus | Exit Intelligence | stop_over_consensus_monitor |
| Four stop-quality questions | Post-Trade Review | §5 |
| 4.4→4.5 gate metrics | Post-Trade Review | §6 |
| Layer 3 trail OFF in recommendations | Post-Trade Review | §2.1 backtest gate |

---

## 7. Tmux (full 7-agent swarm)

```bash
./linux_launchers/hermes_scalp_swarm_tmux.sh start
```

Windows: orchestrator · live_monitor · signal_scout · entry_validation · exit_intelligence · post_trade_review · health

---

## 8. Live Dry Test Log (2026-07-02)

### Unit tests

```
$ .venv/bin/python3 tests/test_hermes_scalp_phase3.py
OK: all phase3 tests passed
```

Covers: Street-extended long, stop-over-consensus, deterministic critique, `--once` smoke.

### Exit Intelligence

```
$ .venv/bin/python3 scripts/hermes_scalp_exit_intelligence.py --once
{
  "scanned": 0,
  "suggestions": 0,
  "enqueued": 0,
  "street_coverage": 0
}
```

### Post-Trade Review + OAuth LLM

```bash
# Requires Grok OAuth proxy on :8645 (or --lane chatgpt :8646)
.venv/bin/python3 scripts/hermes_scalp_post_trade_review.py --once --llm --lane grok --force-llm
```

Backfills `llm_enhanced`, `llm_summary`, `llm_lane` on existing reviews when no new closed trades.

**Live run (2026-07-02):** `--llm --lane grok --force-llm` → `llm_enriched: 4`, `oauth_lane: grok` (~35s for 4 trades).

### Post-Trade Review (first run — 4 closed trades critiqued)

```
$ .venv/bin/python3 scripts/hermes_scalp_post_trade_review.py --once
{
  "new_critiques": 4,
  "total_reviewed": 4,
  "validation_closed_trades": 2,
  "validation_overall": "INSUFFICIENT SAMPLE — gate needs >=150 closed trades"
}
```

Subsequent runs return `new_critiques: 0` (idempotent — skips already-reviewed trade IDs).

**Note:** `max_adverse_excursion` / `max_favorable_excursion` on `paper_trades` are **% from entry**; the agent converts to R using planned stop distance (see `trade_execution_analyzer.py` Phase 194 fix).
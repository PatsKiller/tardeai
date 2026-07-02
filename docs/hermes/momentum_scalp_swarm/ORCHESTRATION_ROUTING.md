# Orchestration & Routing Logic

**Owner:** Hermes Orchestrator (`scripts/hermes_scalp_orchestrator.py`)

---

## Tick Cycle (60s default)

```
1. Read portfolio_heat.json, stoplight_status.json, pending_approvals.json
2. Run policy gates (heat, breakeven, concurrent limits)
3. Scan stoplight positions for regime shifts + BE overdue
4. Build route table → enqueue material actions to pending_approvals.json
5. Append orchestrator_audit.json event
```

---

## Route Table

| Source Event | Target Agent | Action | Approval Required |
|--------------|--------------|--------|-------------------|
| Qualified signal from Scout | Entry Validation | `validate_entry` | Yes (new entry) |
| Heat pause/kill active | Entry Validation | `block_new_entries` | No (automatic block) |
| Regime shift detected | Stop Adjustment | `propose_tighten` (0.5× ATR) | Yes |
| BE overdue (+1.2R, not secured) | Stop Adjustment | `propose_breakeven` | Yes |
| Freshness decay red alert | Stop Adjustment | `force_breakeven` | Yes |
| Heat > 3.5% | Stop Adjustment | `tighten_all` | Yes |
| Price extended vs Street μ | Exit Intelligence | `suggest_partial_exit` | Yes |
| Trade lifecycle closed | Post-Trade Review | `generate_critique` | No (advisory) |

---

## Policy Gate Functions

### `_policy_gate_heat()`
- Returns `(False, reason)` if `kill_switch_active` or `pause_new_entries`
- Hard reject at ≥ 4.5% aggregate open risk

### `_policy_gate_breakeven(symbol, direction, proposed_stop, entry)`
- If unrealized ≥ trigger_r and BE not secured:
  - Long: reject stop < entry
  - Short: reject stop > entry

---

## Human-in-the-Loop Flow

```
Agent proposes action
    → Orchestrator validates policy gates
    → If material: write pending_approvals.json
    → OpenClaw Telegram notification
    → Operator: approve | reject | modify
    → On approve: target agent executes
    → stop_adjustment_history.json + orchestrator_audit.json
```

Material actions (paper phase):
- New entries
- Stop adjustments (including breakeven)
- Exits / partials
- Tighten-all portfolio actions

---

## Agent Handoff Protocol

All inter-agent messages include:
- `from_agent`, `to_agent`, `action`, `symbol`, `reason`
- `policy_section` (e.g., `§3 L4 #1`)
- `requires_approval: bool`
- `payload` (stops, sizes, tags)

---

## Kill Switches

| Switch | Trigger | Effect |
|--------|---------|--------|
| Portfolio heat kill | > 4.5% | Block entries, global tighten suggestion |
| Daily loss | 3R or 2.5% | Orchestrator blocks new entries |
| Max concurrent | > 3 scalps | Amber alert, block new entries |
| Manual | Operator via Telegram | Halt all agent ticks |
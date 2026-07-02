# Shared State Schema — Momentum Scalp Swarm

**Root:** `state/momentum_scalp/`  
**Library:** `scripts/lib/momentum_scalp_swarm_state.py` (atomic write + file lock)

---

## open_scalps.json

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T14:30:00Z",
  "scalps": [
    {
      "id": 1234,
      "symbol": "NVDA",
      "side": "long",
      "entry": 125.50,
      "price": 127.20,
      "stop": 124.10,
      "current_R": 1.21,
      "stop_distance_R": 2.5,
      "dist_to_breakeven_R": 0.0,
      "breakeven_secured": false,
      "trailing_active": false,
      "entry_regime": "trending",
      "current_regime": "ranging",
      "regime_shifted": true,
      "suggested_stop": 124.85,
      "freshness_s": 32,
      "risk_usd": 280.0,
      "initial_stop_method": "hybrid",
      "initial_stop_atr": 1.2
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `side` | `long` \| `short` | Direction (symmetric stop math) |
| `current_R` | float | Unrealized P&L in R-multiples |
| `breakeven_secured` | bool | Layer 2 satisfied |
| `regime_shifted` | bool | Trending→Ranging while in trade |

---

## portfolio_heat.json

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T14:30:00Z",
  "account_equity": 100000,
  "aggregate_open_risk_dollars": 840,
  "aggregate_open_risk_pct": 0.84,
  "open_scalp_count": 2,
  "heat_tier": "green",
  "pause_new_entries": false,
  "kill_switch_active": false,
  "policy_ref": "MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY.md §3 L4 #2, §7"
}
```

| `heat_tier` | Condition |
|-------------|-----------|
| `green` | < 3.5% |
| `amber` | 3.5% – 4.5% (pause new entries) |
| `red` | > 4.5% (kill switch) |

---

## regime_state.json

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T14:30:00Z",
  "market_regime": "risk_on_trend",
  "symbols": {
    "NVDA": {
      "regime": "ranging",
      "regime_at_entry": "trending",
      "regime_shift_detected": true,
      "regime_shift_direction": "trending → ranging",
      "trail_tighten_atr_mult": 0.5,
      "confidence": 72
    }
  }
}
```

---

## stoplight_status.json

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T14:30:00Z",
  "positions": [
    {
      "symbol": "NVDA",
      "trade_id": 1234,
      "direction": "long",
      "stoplight": "amber",
      "distance_to_stop_r": 2.5,
      "distance_to_breakeven_r": 0.0,
      "current_r": 1.21,
      "regime": "ranging",
      "regime_shift_detected": true,
      "policy_suggestions": ["NVDA at +1.2R but breakeven not secured"],
      "suggested_stop": 124.85
    }
  ]
}
```

Dynamic Y/A/R thresholds come from `stoplight_regime_thresholds.py` per regime.

---

## stop_adjustment_history.json

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T14:35:00Z",
  "adjustments": [
    {
      "id": "adj_20260702_001",
      "trade_id": 1234,
      "symbol": "NVDA",
      "from_stop": 124.10,
      "to_stop": 124.85,
      "reason": "§3 L4 #1 regime shift Trending→Ranging — 0.5× ATR tighten",
      "agent": "stop_adjustment",
      "approved_by": "telegram_operator",
      "approved_at": "2026-07-02T14:34:00Z",
      "applied": true
    }
  ]
}
```

---

## validation_tracker.json

Synced with `scripts/scalp_stop_validation_tracker.py` output. Tracks §6 gate metrics (≥150 closed trades, win rate, expectancy, etc.).

---

## qualified_signals.json

Written by Signal Scout. Signals with `status: pending_validation` are picked up by Entry Validation.

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T15:00:00Z",
  "signals": [
    {
      "symbol": "NVDA",
      "conviction": 78,
      "freshness_s": 28,
      "setup_tag": "social_route_confirmed",
      "regime": "strong_trending_bull",
      "policy_compliant": true,
      "status": "pending_validation"
    }
  ]
}
```

---

## entry_validation_queue.json

```json
{
  "schema_version": "1.0",
  "validated": [{ "symbol": "NVDA", "planned_stop": 124.1, "initial_risk_r": 1.0, "valid": true }],
  "rejected": []
}
```

---

## pending_approvals.json

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-02T14:30:00Z",
  "approvals": [
    {
      "id": "apr_1730000000",
      "status": "pending",
      "target": "stop_adjustment",
      "action": "propose_breakeven",
      "symbol": "NVDA",
      "reason": "§3 L2 mandatory breakeven",
      "requires_approval": true,
      "created_at": "2026-07-02T14:30:00Z"
    }
  ]
}
```

---

## Atomic Write Pattern

```python
from lib.momentum_scalp_swarm_state import read_json, write_json, append_audit

heat = read_json("portfolio_heat.json", {})
heat["aggregate_open_risk_pct"] = 2.1
write_json("portfolio_heat.json", heat)
```

Writes use `.tmp` + `replace()` under per-file `fcntl`-style locks.
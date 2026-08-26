# PHASE 4–5 CLOSEOUT — Attention KPIs + Institutional Sizing

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Versions:** `office_home_1.2.0` · `capital_plan_1.2.0` · `institutional_sizing_1.0.0`

## Phase 4 — Attention counts

### Problem

`decision_count` mixed investment cards with workflow actions, inflating
“Decisions needing you” and double-counting operator attention.

### Model (disjoint)

| KPI | Meaning |
| --- | --- |
| **Investment decisions** | True InvestmentDecision objects needing attention |
| **Workflow actions** | Open action-ledger items only |
| **Open plans** | Durable plans still open |
| **Material today** | Deduped priority set (not sum of the three) |

CIO NOW **cards** = at most **5 investment decisions** (actions no longer appear as cards).

### Code

`build_cio_now` in `cio_command_center.py` returns:

```json
{
  "decisions": [/* ≤5 investment cards */],
  "attention": {
    "investment_decisions": 7,
    "workflow_actions": 20,
    "open_plans": 12,
    "material_today": 4,
    "labels": { ... },
    "note": "KPIs are disjoint..."
  },
  "decision_count": 7,
  "open_actions_count": 20,
  "open_plans_count": 12,
  "material_today_count": 4
}
```

## Phase 5 — Institutional sizing

### Problem

TRIM always used **10% of position value**, even when the objective was
“clear concentration fire” or “return to policy cap.”

### Engine

`scripts/lib/cio_institutional_sizing.py`

| Method | When |
| --- | --- |
| `clear_fire_staged` | weight > fire → stage between clear-fire and full policy |
| `policy_normalize_staged` | fire ≥ weight > policy → stage toward policy |
| `advisory_fallback_10pct` | within policy + advisory TRIM only (explicit fallback) |
| `full_exit` | EXIT |
| `headroom_bounded_default` | ADD / RE_ENTER |

Each decision carries:

- `recommended_delta_usd` (objective)
- `trim_to_clear_fire_usd` / `trim_to_policy_usd`
- `sizing_objective` prose
- `sizing_why_not_min` / `sizing_why_not_max`
- `fallback_candidate_only`

### Example (SCHD-shaped)

Current ~17.6% · Fire 16.5% · Policy 12%  
→ min clear fire ~$14k · full policy ~$72k · **staged recommend between them**  
(not automatic −10% of $226k).

## Tests

```
tests/test_cio_institutional_sizing.py
tests/test_cio_command_center.py  (attention KPIs)
+ capital_plan / decision_semantics / office_consistency
81 passed in related suites
```

## CI

`institutional_sizing` gate added to `run_cio_hardening_ci.py`.

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next

Phase 6+ per acceptance program (report print, strategy layer, E2E acceptance).

# PHASE 8 CLOSEOUT — Alex / Command Center / Report Consistency

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**Versions:** `office_home_1.1.0` · `report_v2_1.5.0`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Goal

The same decision must look like the same decision everywhere: `/v3/cio` CIO NOW,
institutional report Decisions Now, and (later) Telegram.

## Delivered

### 8.1 CIO NOW cards (≤5)

Each material card now carries:

| Field | Purpose |
| --- | --- |
| `decision_id` | Stable `dec_<hash>` shared with report |
| `action` | Professional stance (Trim / Add / …) |
| `delta_usd` | Dollar recommendation |
| `weight_pct` / `target_weight_pct` | Current / target |
| `why_now` | Desk signal |
| `counter_thesis` | Disagreement on record |
| `what_changes_call` | CIO-speak reverse condition |
| `next_review` | Cadence |
| `operator_actions` | ACK / DEFER / DONE / REJECT / RATE |

Neutral “hold because nothing changed” rows are omitted.

### 8.2 Capital Plan surface

| Field | Rule |
| --- | --- |
| Settled cash | `cash_total_usd` |
| Reserve | policy floor |
| Earmarked redeploy | **label on cash** — not a new raise |
| Free unearmarked | cash − earmark |
| Investable / deployable | Phase 2 arithmetic |
| Prospective raise | trims+exits only |
| Account cash | per-account breakdown |
| `plan_digest` | equals engine `digest` when present |

### 8.3 Report consistency

`part_a.consistency` and `office_home.consistency` both expose:

- `decision_ids`
- `capital_plan_digest`
- `plan_version`

Tests assert ID sets and digests match for the same capital-plan input.

### 8.4 Evidence drawer

Internal codes, digests, run ids, constraint kinds, source SHA live in
`evidence` — not in CIO NOW narrative. Sector recommendations are professional
prose; pseudo-sectors (Iwm−Spy) dropped.

## Exit gate

| Gate | Status |
| --- | --- |
| CIO NOW decision IDs == report decision IDs | **PASS** (tests) |
| Capital Plan digest == report plan digest | **PASS** (tests) |
| Top-level raw telemetry in CIO NOW | **0** |
| Page-load model calls in composition | **0** (pure) |

## Files

| File | Change |
| --- | --- |
| `scripts/lib/cio_decision_semantics.py` | `make_decision_id`, digests, what_changes_call, operator actions |
| `scripts/lib/cio_command_center.py` | office_home_1.1.0 cards + capital surface |
| `scripts/lib/cio_report_v2.py` | report consistency block + plan_digest |
| `tests/test_cio_office_consistency.py` | **NEW** |
| `tests/test_cio_command_center.py` | raise/earmark labels |

## Tests

```
tests/test_cio_office_consistency.py   7 passed
with command center / capital / report  99 passed
```

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next phase allowed

Phase 9 — Telegram Alex product behavior + dedupe (canary only after explicit approval).

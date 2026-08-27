# PHASE 3 CLOSEOUT — Freshness & Materiality Gate

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `freshness_materiality_1.0.0`

## Goal

**Nothing can say ACT NOW merely because it has a non-zero delta.**

Each decision gets an explicit action label driven by financial-truth quality,
evidence freshness, and material stance — not by `recommended_delta_usd != 0`.

## Labels

| Label | Display | Meaning |
| --- | --- | --- |
| `ACT_NOW` | ACT NOW | Fresh, material, multi-source, truth OK |
| `REVIEW` | REVIEW | Actionable interest but incomplete evidence |
| `WATCH` | WATCH | Hold / thin signal |
| `REVALIDATE` | REVALIDATE | Required evidence undated/missing |
| `DATA_CONFLICT` | DATA CONFLICT | FinancialTruthGate conflict / suppressed |
| `STALE_REFRESH_REQUIRED` | STALE — REFRESH REQUIRED | Required timestamps stale |

## ACT NOW requirements

1. FinancialTruthGate: symbol not suppressed; quality not CONFLICTED/UNAVAILABLE  
2. Holdings freshness PASS (≤ 48h)  
3. Quote / market-value freshness PASS (≤ 15m RTH; after-hours latest-supported up to 24h)  
4. Cash freshness PASS  
5. Decision revalidated within 24h (or evaluated_now)  
6. Risk timestamp PASS when concentration risk is cited  
7. ≥ 2 evidence sources  
8. Material stance (TRIM/EXIT/ADD/RE_ENTER) with non-trivial delta  

## Module

`scripts/lib/cio_freshness_materiality_gate.py`

| API | Role |
| --- | --- |
| `evaluate_decision_actionability` | One decision → label + freshness board |
| `apply_to_decisions` | Batch annotate + summary counts |
| `attach_to_capital_plan` | Wire after FinancialTruthGate |

## Wiring

| Surface | Change |
| --- | --- |
| `build_capital_plan_from_sources` | Attaches freshness gate after truth gate |
| `GET /api/v2/cio/capital-plan` | `freshness_materiality_gate` + per-decision `action_label` |
| CI | `freshness_materiality` suite |

## Tests

```
tests/test_cio_freshness_materiality_gate.py  9 passed
tests/test_cio_financial_truth_gate.py       12 passed
tests/test_cio_capital_plan.py               43 passed
```

Core invariant covered: **non-zero delta without freshness ⇒ not ACT NOW**.

## Live observation (hot-deploy)

Capital plan decisions currently surface **DATA CONFLICT** / non-ACT_NOW while
FinancialTruthGate reports dual-price / meta conflicts — correct fail-closed
behavior. `act_now_count: 0` until truth+freshness clear.

## Exit gate

| Gate | Status |
| --- | --- |
| Module | **PASS** |
| Delta-alone cannot ACT NOW | **PASS** |
| Conflict → DATA_CONFLICT | **PASS** |
| Stale holdings path | **PASS** |
| Capital plan + API wired | **PASS** |
| CI suite | **PASS** |
| Broker authority | **unchanged** |

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next

Phase 4 — CIO attention counts (investment decisions vs workflow actions vs plans; Material Today 0–5).

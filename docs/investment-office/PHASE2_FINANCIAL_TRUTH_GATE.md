# PHASE 2 CLOSEOUT — FinancialTruthGate

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `financial_truth_gate_1.0.0`

## Goal

Before Alex may treat portfolio arithmetic as actionable, run a **reusable
FinancialTruthGate** that:

- reconciles cash + MV + account totals,
- checks shares × canonical price ≈ market value,
- checks weight and unrealized P&L identity,
- attaches a **timestamp contract** per meta/field,
- classifies publication quality,
- **suppresses ACT NOW** on conflicted symbols (does not round away errors).

## Module

`scripts/lib/cio_financial_truth_gate.py`

| API | Role |
| --- | --- |
| `evaluate_holdings_document` | Full book gate |
| `check_position_row` | Per-position invariants |
| `analyst_upside_vs_canonical` | Target upside labeling (no false “vs current”) |
| `attach_gate_to_capital_plan` | Merge into capital plan decisions |
| `field_meta` | source / as_of / ingested_at / age / quality |

### Publication states

`VERIFIED_CURRENT` · `VERIFIED_AS_OF` · `STALE` · `CONFLICTED` · `DATA_UNAVAILABLE`

### Tolerances

| Kind | Rule |
| --- | --- |
| Dollars | max($1, 0.01% of row) |
| Weights | 0.02 percentage points |
| Price-derived | 0.1% (dual quote conflict uses ~0.2%) |

## Wiring

| Surface | Change |
| --- | --- |
| `build_capital_plan_from_sources` | Attaches gate by default (`attach_financial_truth_gate=True`) |
| `GET /api/v2/cio/capital-plan` | Includes `financial_truth_gate` + per-decision suppress flags |
| Compact capital plan | Surfaces gate summary + actionable flags |
| CI | `financial_truth_gate` suite in `run_cio_hardening_ci.py` |

## DXCM regression

Fixture matches Phase 0 failure: 225 shares, dual prices (91.26 vs 90.98), MV not
equal to shares × canonical price → **CONFLICTED**, `act_now_suppressed=true`.

## Live observation (post hot-deploy)

Gate on live holdings (illustrative at closeout):

- `overall_quality`: **CONFLICTED** (expected until price/MV sources unify)
- Dual-price and shares×price exceptions widespread (SCHD, V, DXCM, …)
- Meta: `updated_at` lag vs `as_of` → **meta_timestamp_conflict**
- `earmark_eq_full_cash` warning when earmark labels 100% of cash

This is **honest fail-closed quality**, not a silent pass.

## Tests

```
tests/test_cio_financial_truth_gate.py   12 passed
tests/test_cio_capital_plan.py           43 passed
```

## Exit gate

| Gate | Status |
| --- | --- |
| FinancialTruthGate module | **PASS** |
| DXCM regression | **PASS** |
| Analyst upside labeling | **PASS** |
| Capital plan attachment | **PASS** |
| CI suite wired | **PASS** |
| Live API exposes gate | **PASS** (hot-deployed to CURRENT) |
| Silent formatting of conflicts | **NO** |
| Broker authority | **unchanged** |

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next

Phase 3 — Freshness & materiality gate (ACT NOW requires truth + freshness + evidence).

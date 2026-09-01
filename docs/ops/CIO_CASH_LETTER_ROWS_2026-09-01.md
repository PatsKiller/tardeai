Status:      ACTIVE  
as_of:       2026-09-01T16:30:00-04:00  
Measured at: origin/main `b11086081` (contains #831 / #832)  
Canonical repo path: docs/ops/CIO_CASH_LETTER_ROWS_2026-09-01.md  
Authority:   ops record for cash_letter ↔ capital_plan dollar agreement  
See also:    docs/ops/litmus/LITMUS_MONEY_2026-09-01.md  
             docs/audits/CIO_SURFACE_ASOF_2026-09-01.md  
             PR #777 (cash as-of freshness — open, conflicts; **not** merged here)

# Cash letter publishes row-sum cash, not the CASH_SLEEVE fossil

## Verdict

**Promote: NO** unless the operator says `promote cash`.  
Wake persist (#832) out of scope. `$PROJ` not fast-forwarded. #777 not merged.

## Problem (LITMUS_MONEY)

`/api/v3/cio/home` published two cashes in one body:

| figure | surfaces | clock |
|---:|---|---|
| **630,513.62** | overview · capital_plan · temperament · is_cash row sum | LIVE 2026-09-01 |
| **630,784.82** | `cash_letter.cash_usd` + letter evidence_refs | `CASH_SLEEVE` · `cash_written_at` 2026-08-29 |

Delta **$271.20**. Two stores. `api_v2.py` still commented the Saturday proof of
`630,784.82` gap 0.00 — that sentence was no longer a live claim.

## Change

| piece | what |
|---|---|
| `scripts/lib/cio_record_narrative.py` `build_cash_letter` | Published `cash_usd` = `capital_plan.cash_total_usd` only. Sleeve disagreement → `prior_cash_usd` + `prior_cash_written_at` + note. `as_of` remains PP3 cash-rows clock from the plan; `composed_at` stays the build clock. |
| `scripts/api_v2.py` ~2605 comment | Historical 630,784.82 gap-0 proof marked **no longer true as a live claim**; points at LITMUS_MONEY / letter prior. |
| `tests/test_cash_letter_rows.py` | Equality + prior + mutations (sleeve-as-dollar → red; 630513 vs 630784 → red). |
| `tests/test_cio_cc_record_narrative_slice_c.py` | Updated fixtures/asserts (not deleted). |

### Explicit non-goals

- Do not write a new amount into `CASH_SLEEVE` to "fix" it  
- Do not average the two numbers; do not pick 630,784.82  
- Do not touch earmark clamp  
- Do not explain Moomoo $500 (operator-only)  
- Do not merge or rebase #777  
- Do not edit `wake_research_persist.py`  
- No holdings.json write / no broker refresh  

## Expected after promote

`cash_letter.cash_usd == capital_plan.cash_total_usd == 630513.62` (live row sum).  
`$271.20` remains visible as `prior_cash_*` (or documented fossil) — not vanished.
)

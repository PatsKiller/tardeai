# Night Three Wave 3b — frozen fields that imply judgment but never move

**Wave:** Night Three Wave 3b  
**Date:** 2026-09-01  
**Authority:** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0`  
**Branch:** `fix/overnight-w3-3b-frozen-fields`  
**Store set:** none  
**Deploy:** none (orchestrator merges wave PRs in order; AFTER is post-deploy)

## Contract

A6 confirmed `next_reviews` identical across inputs and `standing_policy_template`
unconditional. A field whose value never moves regardless of input is a
**constant**, not a judgment.

Either make it conditional on real state, **or** stop rendering it in a register
that implies judgment (demote / relabel / omit).

This tranche chooses demotion.

## BEFORE (A6 / Part 2 §5.1 + night-two V4)

Quoted from Census Part 2 and Wave V verification:

```
decisions[].next_review (×25) =
  "next material generation or next session — standing cadence, not a dated catalyst"

operator_product.next_reviews =
  [same sentence repeated per entry]

temperament.portfolio_implication =
  PORTFOLIO_IMPLICATION_CONSTANT   # rendered as situation guidance historically
```

Constructed-input probe (five materially different rows) left `next_review` /
`next_review_at` **byte-identical** on every card that did not supply a date.
`standing_policy_template` (post-B5 name) remained unconditional.

## Change this tranche

| file | change |
|------|--------|
| `operator_decision_contract.py` | `STANDING_CADENCE_TEMPLATE`; when producer supplies no date, clear `next_review` / `next_review_at`, stamp `standing_cadence_template` + role; completeness treats demotion as partial (like confidence) |
| `cio_p90_voice.py` | `NEXT_REVIEWS_NOTE` records demotion; empty judgment list + template role |
| `cio_investment_product.py` | `build_temperament` writes `standing_policy_template` at source; `portfolio_implication=None` |
| `cio_operator_product.py` | `_temperament_display` idempotent; `next_reviews` only dated catalysts; standing cadence on template |
| `cio_operator_renderers.py` | standing_policy demotion idempotent when source already demoted |
| `cio_command_center.py` | home temperament demotion idempotent (not `build_reentry_book_labels`) |
| `tests/test_overnight_w3_3b_frozen_fields.py` | constructed-input identity + demotion locks |
| `scripts/run_cio_hardening_ci.py` | register under `money_surface_honesty` |

**Not touched:** reentry population projection, writer/footer provenance,
broker paths, notify.

## AFTER (constructed inputs)

```
next_review / next_review_at     → null   (omitted from judgment register)
standing_cadence_template        → "next material generation or next session — standing cadence, not a dated catalyst"
next_review_role                 → "standing_cadence_template"
next_review_is_dated_catalyst    → false

operator_product.next_reviews    → []     (when no producer dates)
standing_cadence_template        → <constant>
next_reviews_is_judgment         → false

temperament.portfolio_implication → null
temperament.standing_policy_template → PORTFOLIO_IMPLICATION_CONSTANT
portfolio_implication_role       → "standing_policy_template"
```

When a producer **does** supply `next_review` (e.g. `"2026-09-15 earnings"`),
that value stays on the judgment register and in `next_reviews`.

## Fields that remain byte-identical — and why that is now honest

| field | identical across inputs? | why honest |
|-------|--------------------------|------------|
| `standing_cadence_template` | yes | Labeled standing cadence / class T; **not** on `next_review` judgment fields |
| `standing_policy_template` | yes (unconditional) | Labeled standing-policy template; `portfolio_implication` cleared so it cannot render as situation guidance |
| `next_review` / `next_review_at` when undated | yes (`null`) | Honest **omit** — no dated catalyst was supplied |
| `next_reviews` when undated | yes (`[]`) | Judgment register empty; constant demoted to template |

Titles, decisions, urgency, entities, and dated catalysts still move with input.

## Proof commands

```bash
python3 -m pytest -q tests/test_overnight_w3_3b_frozen_fields.py
python3 -m pytest -q tests/test_overnight_b4_b5_asof_provenance.py
python3 scripts/run_cio_hardening_ci.py
# gate money_surface_honesty must PASS
python3 scripts/check_test_coverage.py --fail-on-new
```

Results filled at ship time under `[VERIFIED]` in the PR body.

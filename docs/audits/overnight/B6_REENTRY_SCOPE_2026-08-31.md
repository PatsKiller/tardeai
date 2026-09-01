# Overnight B6 — Surface scope labels (re-entry books)

**Wave:** Overnight B6 / WAVE_12 E2  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0` (shorthand; rail is the unconditional raise)  
**Branch:** `fix/overnight-b6-reentry-scope-labels`  
**Store set:** none  
**Deploy:** none

## Contract

The two re-entry books answer different questions and are both correct. Each
states **the question it answers** and **the population it scores**. Do not
merge them. Do not introduce a precedence winner.

## Finding — labels already present [CODE]

Prior Wave 2 / Slice 3 / Wave 2C 131–160 already shipped:

| Surface | Producer | Question (pre-B6) | Scope (pre-B6) |
|---------|----------|-------------------|----------------|
| A | `cio_investment_product.build_reentry_book` | which former holdings are near their re-entry trigger? | former holdings vs exit trigger |
| B | `cio_desk_depth.build_reentry_book` | which candidates have acceptable risk-reward at the current cash stage? | candidates vs cash-stage R:R under desk thesis |

Canonical module: `scripts/lib/cio_reentry_surface_labels.py`.  
Stamp sites: investment product (A), desk depth (B). Home dual-pipe labels via
`cio_command_center.build_reentry_book_labels` (`merged=false`) — **not edited
this tranche** to avoid overlap with overnight B4/B5 (as_of / provenance).

Gap against the WAVE wording: books carried `question` + `scope` but no
explicit **`population`** field naming who is scored.

## Change this tranche

1. **`population` on both surfaces** and through `stamp()`:
   - A → `former holdings (exited / previously traded)`
   - B → `desk cash-stage candidates under desk thesis`
2. **`banner()`** now includes `scores {population}` while keeping scope +
   not-this-book disclaimer (desk note / investment note continue to work).
3. **`tests/test_overnight_b6_reentry_scope.py`** locks question + population on
   canonical defs, stamp, and both builders; asserts no precedence-winner
   language; asserts producers stay separate in source.
4. **Hardening CI allowlist** — gate `overnight_b6_reentry_scope` in
   `scripts/run_cio_hardening_ci.py` so the new file is run, not invisible.

`cio_command_center.py` / `cio_operator_product.py` untouched. Home already
shows question + scope from the canonical module; stamped book payloads now
also carry `population`.

## Invariants

- No merge of Surface A `names` with Surface B `cards`.
- `precedence` remains a **disclaimer of authority**, not a winner rule.
- Labels class `T` (template). Authority `READ_ONLY_ADVISORY`.

## Proof commands

```bash
python3 -m pytest -q tests/test_overnight_b6_reentry_scope.py
python3 -m pytest -q tests/test_cio_pipeline_slice3_reentry_book_labels.py
python3 scripts/check_test_coverage.py --fail-on-new
```

Results filled at ship time under `[VERIFIED]` in the PR body.

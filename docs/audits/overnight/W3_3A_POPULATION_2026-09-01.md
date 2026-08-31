# Night Three Wave 3a — project `population` onto operator / home surfaces

**Wave:** Night Three Wave 3a  
**Date:** 2026-09-01  
**Authority:** `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0`  
**Branch:** `fix/overnight-w3-3a-population`  
**Store set:** none  
**Deploy:** none (orchestrator merges wave PRs in order; AFTER is post-deploy)

## Contract

B6 stamped `population` on Surface A/B book dicts via
`cio_reentry_surface_labels.stamp()`. Home and the operator product projection
must pass that field through — not omit it, not re-word it.

| Surface | Expected `population` |
|---------|------------------------|
| A | `former holdings (exited / previously traded)` |
| B | `desk cash-stage candidates under desk thesis` |

## BEFORE (live `/api/v3/cio/home`, pre-change)

Quoted from the serving release before this PR:

```bash
curl -sS http://127.0.0.1:7777/api/v3/cio/home \
  | jq '.reentry_books.a.population,.reentry_books.b.population'
```

```
null
null
```

`reentry_books.a` keys on the live payload lacked `population` entirely
(`class`, `not_this_book`, `precedence`, `producer`, `question`, `scope`,
`surface`, `surface_name` only). Canonical stamps already carried the field;
`_view` dropped it.

## Change this tranche

1. **`scripts/lib/cio_command_center.py`** — `build_reentry_book_labels` /
   `_view` only: add `"population": sfc["population"]` so
   `home["reentry_books"].a/b.population` is the canonical stamp.
2. **`scripts/lib/cio_operator_product.py`** — `reentry` projection dict only:
   add `"population": reentry.get("population")` from the stamped book.
3. **`tests/test_overnight_b6_reentry_scope.py`** — extend with W3 3a
   projection locks (labels `_view` + operator product pass-through).
4. **This audit** — BEFORE quote + expected AFTER.
5. **`docs/INDEX.md`** — regenerated via `report_docs_inventory.py --write-index`
   so G3 / `docs_index_drift` stay green after adding this audit.

Do **not** edit `cio_reentry_surface_labels.py`, temperament / next_reviews,
or writer / footer code.

## Expected AFTER (post orchestrator deploy of served release)

```
"former holdings (exited / previously traded)"
"desk cash-stage candidates under desk thesis"
```

Same curl as BEFORE. Values come from the canonical module via projection —
not a second copy of the strings in command-center / operator-product.

## Invariants

- No merge of Surface A `names` with Surface B `cards`.
- `precedence` remains a disclaimer of authority, not a winner rule.
- Labels class `T`. Authority `READ_ONLY_ADVISORY`.
- Projection only — producers / stamp sites unchanged this tranche.

## Proof commands

```bash
python3 -m pytest -q tests/test_overnight_b6_reentry_scope.py
python3 -m pytest -q tests/test_cio_wave2c_131_160_books.py
python3 scripts/run_cio_hardening_ci.py
# gate overnight_b6_reentry_scope must PASS
python3 scripts/check_test_coverage.py --fail-on-new
```

Results filled at ship time under `[VERIFIED]` in the PR body.

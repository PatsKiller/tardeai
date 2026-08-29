# The $52,677.32 cash gap — writer identified

Authority: **READ_ONLY_ADVISORY** · detect-then-name, **no merge**, nothing written.
Authorised as the next slice of the operator's Decision 2.

---

## Answer

**`portfolio_totals.total_cash` is never written by the reprice path. It is
inherited forever.**

`scripts/portfolio_loader.py:332`:

```python
prev_pt = dict(current.get("portfolio_totals", {}))   # carry EVERYTHING forward
prev_pt["total_value"]     = portfolio_total          # refreshed
prev_pt["day_change"]      = portfolio_day_change     # refreshed
prev_pt["day_change_pct"]  = portfolio_day_change_pct # refreshed
prev_pt["as_of"]           = today                    # refreshed
prev_pt["last_pipeline_run"] = ...                    # refreshed
updated["portfolio_totals"] = prev_pt
```

`total_cash` is not in that list, and **no other writer sets it into
`portfolio_totals`** (`git grep` over `scripts/` returns no assignment). Every
reprice copies the previous value forward unchanged.

That is why `total_mv_excluded` matches the row sum to the cent while
`total_cash` does not: `total_mv_excluded` **is** recomputed; `total_cash` is a
fossil.

## None of the four hypotheses; it is a fifth

| hypothesis | verdict |
|---|---|
| pending / unsettled | no |
| money-market sleeve | no |
| unmapped lot | no |
| stale positions (08-26) vs reprice (08-28) | no — staleness affects both fields equally |
| **field never refreshed by any writer** | **yes** |

## This has happened before, and was fixed on the read side only

`scripts/api_v2.py:2593`, from commit `c7d02bc8`, **2026-07-21**:

> *Cash = sum of the actual CASH positions. The stored
> `portfolio_totals.total_cash` had drifted to $478k while the real cash was
> $186k (it did NOT reconcile: $186k cash + $1.069M positions = the $1.255M
> total, whereas $478k would imply a $1.55M book). Recompute from the holdings
> so "cash available" for deploy/rotation sizing is correct. (2026-07-21 audit.)*

The same field, the same failure, five weeks ago — a **$292k** gap that time.
The fix recomputed cash *at the read site in `api_v2`* and left the stored field
alone. It has been drifting again ever since.

## Which is why the two surfaces disagree

```
/api/v2/overview  total_cash        630,784.82   recomputed from rows (the 07-21 workaround)
/v3/cio           cash.cash_usd     630,784.82   row sum
/v3/cio           temperament.cash  578,107.50   raw stored field  ← the odd one out
```

`cio_investment_product.collect_cash` falls through
`doc.cash → doc.cash_value → doc.total_cash → totals.total_cash` and lands on
the fossil, because the CIO path was built after the `api_v2` workaround and
never inherited it. One surface routes around the bug; the other reads it
straight.

## The odd field is `total_cash`

`$630,784.82` (position rows) is corroborated twice — by `total_mv_excluded` in
the same document, and by the five per-account cash rows summing exactly to it.
`$578,107.50` is corroborated by nothing and refreshed by no one.

## Recommended fix — not made here

Two candidates, operator's call:

1. **Write it at the source.** Add `total_cash` to the refreshed keys in
   `portfolio_loader`, so the document is internally consistent and every reader
   is correct without knowing this history. Removes the class of bug.
2. **Delete the field.** If it has no writer, it has no owner; readers already
   compute it correctly from rows. Removing it makes the fossil impossible.

Either way the third option — copying the `api_v2` workaround into the CIO path
— would be the *third* place recomputing the same number, and would leave the
fossil in the document for the next reader to trip over.

Until one is chosen, the display law from Decision 2 holds: both printed, gap
named `UNRECONCILED`, `cash_for_S5 = DATA_UNAVAILABLE_UNTIL_RECONCILED`.

## Rails

Nothing written. No field merged, reconciled or averaged. No writer changed.
READ_ONLY_ADVISORY · MBI 0 · INTERDICT 0.

# B4 + B5 — Per-block `as_of` and provenance at display

**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0  
**Rails:** Labelling only — **no dollar amount changed**.  
**Branch:** `fix/overnight-b4-b5-asof-provenance`

## Finding (from Wave A6)

| Surface | Before | Problem |
|---|---|---|
| `OP.cash` | `{cash_usd, cash_n, status}` | No own `as_of` — readers inherited product composition time |
| `home.cash` | copy of OP.cash | Same inheritance gap; `home.as_of` is request composition |
| `temperament.portfolio_implication` | constant standing-policy sentence | Rendered as situation guidance (class T ignored by UI) |
| Morning / EOD footer | authority line only | No honest "no model produced this" stamp |
| Cash letter `as_of` | composition `now` | Dollars can be weeks older than the stamp |
| Narrative `writer` | process lane id | Needed explicit `author` alias (writer = author) |

Live probe before fix (`/api/v3/cio/home`, pin `c3e98d4d…`):  
`cash = {cash_usd: 630784.82, cash_n: 5, status: PRESENT}` — no `as_of`.  
Five cash rows spanned 2026-08-03 → 2026-08-26; product/home composition was 2026-08-31.

## B4 — Per-block `as_of` (cash first)

Block age = **oldest contributing balance**, never composition time. Reuses
`cio_capital_plan.cash_evidence_as_of` so OP / home / capital_plan share one rule.

### Before / after field shapes (dollars unchanged)

**`OP.cash` / `home.cash`**

```
BEFORE:
  cash: { cash_usd, cash_n, status }

AFTER:
  cash: {
    cash_usd,              # unchanged
    cash_n,                # unchanged
    status,
    as_of,                 # oldest cash-row stamp
    cash_as_of: {          # full evidence object
      as_of, oldest_row_as_of, newest_row_as_of,
      mixed_ages, distinct_stamps, unstamped,
      unstamped_accounts, by_account[], document_as_of,
      source, note
    },
    class: "D",
    provenance_class: "D"
  }
```

**`OP.block_as_of` / `home.block_as_of`** (new)

```
{
  cash,                    # evidence age
  portfolio,               # holdings doc stamp
  product_composition,     # brief/product compose time (NOT cash age)
  note
}
```

Morning / EOD cash lines now append `· as_of <oldest> (oldest cash balance)`.

## B5 — Provenance at display

1. **Constant cash guidance** (`portfolio_implication`): moved to
   `standing_policy_template`; `portfolio_implication` cleared at OP / CC view /
   home so it stops rendering as situation guidance. Flagged
   `portfolio_implication_is_guidance: false`.
2. **Footer**: morning / EOD / OP / home carry
   `provenance_footer.model_produced: false` and the text footer
   `_Provenance: D counts/sums · T templates · no model produced this brief. writer = author._`
3. **`writer` = author**: narratives and cash letter stamp `author` and set
   `writer` to the same value. Cash letter `as_of` prefers
   `capital_plan.cash_as_of` (oldest balance) over composition `now`.

## Files

- `scripts/lib/cio_operator_product.py` — cash block stamp; temperament display
- `scripts/lib/cio_operator_renderers.py` — cash age lines; honest footer; CC view
- `scripts/lib/cio_command_center.py` — home stamps; letter provenance; author
- `tests/test_overnight_b4_b5_asof_provenance.py` + CI allowlist
- this audit note

**Not changed:** dollar totals, holdings math, capital-plan money fields,
broker paths, notify, PR #736, hooks/secrets.

## Separate finding (not fixed)

The two cash writers (`position_rows` vs `portfolio_totals` / temperament.cash)
can still disagree (~$52.7k historically). That is a **correctness** finding,
not a labelling fix — reported, not averaged or silently picked.

## Verification

```
python3 -m pytest -q tests/test_overnight_b4_b5_asof_provenance.py
```

Register: `scripts/run_cio_hardening_ci.py` → `money_surface_honesty` gate.

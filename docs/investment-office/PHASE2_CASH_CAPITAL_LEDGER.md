# PHASE 2 CLOSEOUT — Cash / Capital Ledger (Double-Count Fix)

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify` (continues Phase 1 worktree)  
**Version:** `capital_plan_1.1.0`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Problem (Phase 0)

Live report figures:

| Layer | Phase 0 value |
| --- | ---: |
| Settled cash | $578,107.50 |
| Policy reserve (~20%) | $256,485.20 |
| Investable | $321,622.30 |
| Recommended raise | $623,009.02 |
| Recommended deploy | $603,114.70 |

`total_raise` included open redeploy `remaining_usd` **and** those proceeds already sit inside `cash_total`. Deployable became `investable + raise`, double-counting earmarked cash and inflating deploy capacity by ~$623k.

## Fix

| Concept | Rule |
| --- | --- |
| `cash_total` | Canonical settled cash from holdings (`is_cash`) |
| `earmarked_redeploy_usd` | Open redeploy remaining — **label on cash**, not new money |
| Cap | `earmark = min(book_remaining, cash_total)` |
| `total_raise_usd` / `total_prospective_raise_usd` | Trims + exits only (prospective, not yet cash) |
| `deployable_usd` | `investable_usd + prospective_raise` only |
| `post_plan_cash` | `cash + prospective_raise - net_deploy` |

### Invariants (`build_cash_ledger`)

1. `earmark_le_cash` — earmark ≤ cash  
2. `investable_eq_cash_minus_reserve`  
3. `post_cash_identity` — post ≈ cash + prospective − deploy  
4. `deploy_le_investable_plus_prospective`  

## Live first-principles regen (2026-08-14)

Source: `data/portfolios/state/holdings.json` + DB `build_opportunity_set` open events.

### Account cash (sums to settled)

| Account | Settled cash |
| --- | ---: |
| alpaca_taxable_live | $5,000.00 |
| moomoo_taxable_live | $500.00 |
| schwab_rollover_ira | $533,243.97 |
| schwab_roth | $1,469.22 |
| schwab_taxable | $37,894.31 |
| **Total** | **$578,107.50** |

### Open redeploy book vs cash

| Metric | Value |
| --- | ---: |
| Book open remaining (32 events) | **$623,009.02** |
| Settled cash | $578,107.50 |
| Book − cash (overstatement) | $44,901.52 |
| Earmark after cap | $578,107.50 |
| Prospective raise (no queue trims/exits) | $0.00 |

**Finding CLOSED:** Phase 0 raise $623,009.02 equals the live redeploy book sum. That book is already (over-)represented in cash; adding it again as raise was pure double-count (and over-count).

### Old vs new

| | v1.0.0 (buggy) | v1.1.0 (fixed) |
| --- | ---: | ---: |
| total_raise | $623,009.02 | $0.00 (prospective only; earmark excluded) |
| deployable | $321,622.30 + $623,009.02 = **$944,631.32** | **$321,622.30** |
| inflation avoided | — | **$623,009.02** |
| ledger invariants | n/a | **all ok** |

Evidence artifact: `data/audit/cio_phase2_2026-08-14/LIVE_CASH_REGEN.json`

## Code changes

| File | Change |
| --- | --- |
| `scripts/lib/cio_capital_plan.py` | v1.1.0 arithmetic; `build_cash_ledger`; `account_cash_breakdown`; earmark cap; double-count guard |
| `tests/test_cio_capital_plan.py` | Phase 2 double-count, ledger, 578k regen, account cash tests |
| `docs/investment-office/PHASE6_CAPITAL_PLAN.md` | Arithmetic model updated for earmark vs prospective |

## Tests

```
tests/test_cio_capital_plan.py   43 passed
tests/test_cio_report_v2.py      (with capital fixtures) passed
tests/test_cio_command_center.py passed
```

Combined related: **82 passed**.

## Non-goals / safety

- No broker, order, stop, or 2FA changes  
- No Telegram sends  
- No mutation of redeploy book or holdings  
- Advisory authority only  

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next phase allowed

Phase 3+ only after this closeout is reviewed. Report $/% bugs and dual HOLD/TRIM remain later phases.

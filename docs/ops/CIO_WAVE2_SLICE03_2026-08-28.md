# CIO Wave 2 Slice 03 — observational S1 for held-without-open-plan

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0
Notify: false

## Dry

Held equities 19. Open S1 symbols before apply: 10 (including NOC SCHD SPCX ARKX BND JEPI SRNE XLB XLI). CUSIP/CASH excluded.

Held without open S1 (walk order): PFLT SCHG RTX LDOS DIV BAH CSWC V XAR AMANX.

Cap 5 would: **PFLT, SCHG, RTX, LDOS, DIV**.

CUSIP rows not in universe. Skip if open S1 exists.

## Apply once

`scripts/cio_observational_s1.py --cap 5 --apply`

| symbol | plan_id | status |
|--------|---------|--------|
| PFLT | plan_71df2716fe7d | draft observational |
| SCHG | plan_240454cce9cc | draft observational |
| RTX | plan_0eac8dbb5e48 | draft observational |
| LDOS | plan_c85dca5a62f2 | draft observational |
| DIV | plan_e257f25e000d | draft observational |

applied_n=5 notify=false. Idempotent: those five now skip.

Leftover held-without-open-S1 (not this slice): BAH CSWC V XAR AMANX. Not applied (cap 5).

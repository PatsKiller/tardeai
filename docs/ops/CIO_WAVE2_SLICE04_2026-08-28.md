# CIO Wave 2 Slice 04 — Surface A former-sold status

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## Rule

`surface_a_status`: **HELD | EXITED | UNAVAILABLE**. No invented prices.

- **HELD** = material held (≥1 share)
- **EXITED** = previously_traded row **or** residual dust (<1 share)
- **UNAVAILABLE** = neither

Operator correction: **SCHG is former**, not held. Dust residual 0.2294 sh / ~$8 is EXITED, not HELD.

## Live dry

| Symbol | Status | Reason |
|--------|--------|--------|
| SCHG | EXITED | residual_dust_not_material_held (0.2294) |
| AXTI | EXITED | previously_traded |
| FATN | EXITED | previously_traded |
| FANG | UNAVAILABLE | not_in_holdings_or_former_table |

Hygiene: cancelled observational S1 `plan_240454cce9cc` (premise said SCHG held). Notify off.

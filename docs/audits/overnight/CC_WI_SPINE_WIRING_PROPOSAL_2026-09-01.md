# CC_WI_SPINE_WIRING_PROPOSAL_2026-09-01

**Status:** PROPOSAL ONLY — not implemented in Wave 3  
**Agent:** Cursor  
**as_of:** 2026-08-31T17:10Z  
**Authority:** READ_ONLY_ADVISORY

## Finding (Wave 2)

Watch Intelligence is **rich-but-parallel**. Synopsis is `operator_meaning` /
`one_line_thesis` from `watchlist_intelligence.card.v1` — a two-value decision
projection. It does **not** read `InstrumentRecord` (`cc_narrative`, `thesis`,
`operator_turns`, `lessons`). Star writes membership only.

CIO Home is **sparse-but-honest**: 40 spine records; ~10/26 displayed rows
`from_record`.

## What Wave 3 did instead

Labeled the synopsis on the surface:

`Decision projection — not InstrumentRecord spine (cc_narrative / lessons)`

R24-aligned constants in `surfaceFreshness.ts` (`WI_SYNOPSIS_PROVENANCE`).
No second provenance model. No spine write path. No WI→IR wiring.

## Proposed follow-on (separate PR, architecture review)

1. **Read path (additive):** when an `InstrumentRecord` exists for the symbol,
   show a secondary “Spine” callout with `cc_narrative.what` + `as_of` +
   `from_record`, without replacing the broker card.
2. **Do not** teach Star to write the spine — starring is membership; cognition
   writes belong to wake/cognition paths.
3. **Do not** invent a third index — use `InstrumentRecordStore` only.
4. Acceptance: sparse spine remains honest; WI cards stay broker projections;
   disagreement between synopsis template and spine narrative is visible, not
   silently merged.

Owner for implementation: TBD after operator prioritization. Not Cursor Wave 3.

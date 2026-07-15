# Stop Management desk redesign (CC v3)

**Date:** 2026-07-15  
**Surface:** Portfolio → Stop Management  
**Code:** `apps/command-center-v3/src/components/StopManagement.tsx`

## Problems addressed

| Before | After |
|--------|--------|
| Dense 11-column table + always-open evidence sub-rows → clutter | **One card per holding** with left accent, clear section borders |
| Color badges without *why* | Status badge + one-line **why** under ticker; desk **legend** |
| Actions buried in last table column | **Primary CTA** top-right + full **Recommended action** band |
| Weak hierarchy (Street/Grok equal to stop $) | Ordered sections: Header → Protection metrics → Health (≤4 bullets) → Action → collapsible detail |
| Hard to find what to do first | **Actions needed** strip + **Needs Action** filter; cards sorted by urgency |

## Card structure

1. **Header** — ticker, account, price, qty · status badge (PROTECTED / PARTIAL / NO STOP / …) · primary CTA  
2. **Protection** — live stop, distance, at-risk $, coverage, advised, unrealized (metric grid)  
3. **Holdings health** — max 4 bullets (LLM verdict, unrealized, heat, earnings, regime)  
4. **Recommended action** — plain-language CTA + reason + large button  
5. **Detail (collapsed)** — exit ladder, Street, Grok evidence, narrative (existing `ReasonsSubRow`)

## Semantic colors

| Color | Status | Meaning |
|-------|--------|---------|
| Green | PROTECTED | Live stop, size aligned |
| Amber | PARTIAL / REVIEW / TRAIL ELIGIBLE | Undersized, looser than plan, or trail not placed |
| Red | NO STOP / OVERSIZED / NEEDS ATTENTION | Unprotected or hard misalignment |
| Blue | MONITORED | Fidelity / software path |

## Filters

`All` · `Needs Action` · `Partial Coverage` · `No Stop` · `All Protected` · `Trailing Stops` · `Trailing Eligible` · `High Heat` · `Regime Shift`

## Unchanged (intentionally)

- Audit / Policy sub-tabs  
- Adjust modal + HoldingProtectionActions 2FA path  
- API `/api/v2/stops/management` payload  

## Operator note

Primary buttons still **stage** only; Schwab requires 2FA, Fidelity uses manual ticket. Nothing auto-submits.

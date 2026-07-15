# Stop Management desk redesign (CC v3)

**Date:** 2026-07-15  
**Surface:** Portfolio → Stop Management  
**Code:** `apps/command-center-v3/src/components/StopManagement.tsx`

## Problems addressed

| Before | After |
|--------|--------|
| Dense 11-column table + always-open evidence sub-rows | **No table** — compact scan strip per holding |
| Color badges without *why* | Status badge + why text; desk **legend** |
| Actions buried in last column | **Primary CTA** on every strip; action-plan band for urgent lots |
| Street/Grok equal weight to stop $ | Deep detail only behind **▸ details** |
| Hard to find what to do first | Default filter **Needs Action**; urgency sort; Actions needed strip |

## Layout (v2 strip cards)

1. **Scan strip (always)** — color rail · symbol · status · chips (Stop / Dist / At risk / Cover / Plan / P/L) · primary CTA  
2. **Action plan** (auto for NO STOP / PARTIAL / REVIEW; else after expand) — Next action + Protection snapshot  
3. **Deep detail** (▸ details only) — exit ladder, Street, Grok (`ReasonsSubRow`)

Default filter: **Needs Action**. Sort: urgency, then $ at risk.

## Semantic colors

| Color | Status | Meaning |
|-------|--------|---------|
| Green | PROTECTED | Live stop, size aligned |
| Amber | PARTIAL / REVIEW / TRAIL ELIGIBLE | Undersized or moderate concern |
| Red | NO STOP / OVERSIZED / NEEDS ATTENTION | Act first |
| Blue | MONITORED | Fidelity / software path |

## Filters

`All` · `Needs Action` · `Partial Coverage` · `No Stop` · `All Protected` · `Trailing Stops` · `Trailing Eligible` · `High Heat` · `Regime Shift`

## Deploy (important)

UI is served from `apps/command-center-v3/dist` (**gitignored**). After source changes:

```bash
cd apps/command-center-v3 && npm run build
```

Confirm `http://127.0.0.1:7777/v3/` loads a new `index-*.js` hash and build footer updates. Hard-refresh the browser (cache-bust via `cc-boot.js` / build-meta).

## Unchanged

- Audit / Policy sub-tabs  
- Adjust modal + 2FA path  
- API `/api/v2/stops/management`  

Primary buttons still **stage** only; nothing auto-submits.

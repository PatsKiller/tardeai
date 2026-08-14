# PHASE 5 — CIO UX (attention KPIs)

**UTC:** 2026-08-14  
**Surface:** `/v3/cio` → CIO NOW  
**File:** `apps/command-center-v3/src/pages/CioHub.tsx`  
**Authority:** `READ_ONLY_ADVISORY` unchanged — no broker

The backend already returns **disjoint** attention KPIs on `cio_now.attention`.
This phase only updates the office home so the operator sees those four counts
instead of the legacy mixed tiles.

## Four attention KPIs

| Tile | Source (prefer / fallback) | Meaning |
| --- | --- | --- |
| **Investment decisions** | `attention.investment_decisions` / `decision_count` | True investment decisions needing attention |
| **Workflow actions** | `attention.workflow_actions` / `open_actions_count` | Open action-ledger items only |
| **Open plans** | `attention.open_plans` / `open_plans_count` | Durable plans still open |
| **Material Today** | `attention.material_today` / `material_today_count` | Deduped priority set (**not** the sum of the other three). Cards show at most 5. |

These four buckets are **disjoint**. Material Today is a priority set, not
`investment + workflow + plans`.

## Capital-plan copy

**Recommended raise** help text (not “trims/exits/maturities” as a lump):

> Prospective raise = future trims/exits not yet cash. Earmarked redeploy already in cash is not new capital.

## Decision cards

When present, each card also surfaces (plain-English labels, dollars first):

- decision id
- action label
- current / target weight
- recommended dollar change
- trim to clear fire / trim to policy
- sizing method + sizing objective
- freshness
- next review

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

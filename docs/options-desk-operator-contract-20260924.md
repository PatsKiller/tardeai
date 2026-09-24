# Options Desk — operator contract (skim)

```
Status: ACTIVE
as_of: 2026-09-24T11:55:00-04:00
Authority: companion skim only
Canonical SoT: plan-options-desk-holdings-strategies-20260924.md (same folder)
```

**Read the full plan for stages, acceptance IDs, and evidence.** This page is a pocket card.

## What you asked for

1. Covered calls / puts / CSPs / spreads on the book — **Schwab chains + Path B 2FA**
2. Open legs: **P&L, margins, sell/hold/roll with criteria**
3. **CIO fluent** on every strategy the desk supports — real CIO replies, no fake specialists
4. Option ideas tied to **goals** on **securities / sectors / industries**
5. **BUY_READY** notices: equity plan **plus** a capital-efficient **options alternative** when thesis warrants (your V example)
6. **Holdings funnel** so silence is named (need 100 shares / IV / edge / …)

## What is true today

| Piece | Truth |
|---|---|
| Schwab chain + Path B | **Built** (SPCX live spread proof when ARMED) |
| Owned CC sleeve | Often **1** (V) — other size-eligible names drop silently without funnel |
| Open-leg manage | Logic **exists**; margin honesty + criterion chips = Stage **1B** |
| CIO options fluency | **Gap** — options research demoted; no strategy house-facts path |
| Options goals | **0** of 4 open cio_goals |
| BUY_READY text | **Equity only** — no options alt on the notice |

## Stages (short)

| Stage | What | Status |
|---|---|---|
| **1** | Holdings funnel | **CLOSED** (PR #1215) |
| **1B** | Open-leg P&L / criteria / margin UNKNOWN | Code on branch — push/CI |
| **1C** | CIO fluency + goal lineage stamps | Planned / next wire |
| **1D** | BUY_READY options alternative | Planned / next wire |
| **2 / 2G / 3** | Intent map · mint goals · low-VIX policy | **Your call** |

## Hard rules

- No new strategy types without asking  
- No widening IV/intent gates without asking  
- Never invent margin dollars  
- Never auto-mint goals  
- Never fake an “options specialist” — CIO desk + `finalize_operator_reply` only  
- Path B stays per-order 2FA  

## Links

- Full plan (SoT): `plan-options-desk-holdings-strategies-20260924.md`
- PR: https://github.com/PatsKiller/tardeai/pull/1215

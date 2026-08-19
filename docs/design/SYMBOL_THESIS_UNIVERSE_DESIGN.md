# Living Symbol Thesis + Universe Intelligence (design)

**Authority:** READ_ONLY_ADVISORY · MEMORY_BEHAVIOR_INFLUENCE = 0  
**Base:** `origin/main` @ `ff2037d4` (descendant of handoff `258b11de`)  
**Branch:** `wt/symbol-thesis-universe`  
**Stop condition:** READY_FOR_INTEGRATION (no merge/deploy while R6.9/R6.10 observer is live)

## Problem

`CIOThesisStore` exists and is versioned (`desk@v5` live), but production wiring is
**desk-centric**. There is no enforced contract that every material symbol has:

- `CURRENT` symbol thesis, or
- `RESEARCH_REQUIRED` / `STALE` / `CONFLICTED`, or
- `RETIRED` with reason

Re-entry desk fields (`why`, intel state, advisory action) are **decision-control**,
not an investment thesis.

## Approach (extend, don't replace)

| Layer | Module | Role |
|-------|--------|------|
| Universe | `scripts/lib/symbol_universe.py` | Reconcile HELD/FORMER/REENTRY/WATCHLIST/OPPORTUNITY |
| Role | `scripts/lib/portfolio_role.py` | Operator overrides + weak evidence; SCHG=GROWTH |
| Coverage | `scripts/lib/symbol_thesis_coverage.py` | Classify coverage; research-gap triggers |
| Publish helper | `scripts/lib/symbol_thesis_publish.py` | Publish `symbol_<ticker>` into **existing** `CIOThesisStore` |
| Audit | `scripts/symbol_thesis_baseline_audit.py` | Read-only live baseline JSON |

Thesis IDs: `symbol_schg`, `symbol_csco`, … via `symbol_thesis_id()`.

`CIOThesisStore.publish(..., notify=False)` added for bulk/tests (no Telegram spam).

## Explicit non-goals (this PR)

- No production backfill of symbol theses (observer session still open)
- No systemd/cron/Telegram/CURRENT changes
- No broker/order/stop/risk mutations
- No second thesis store / vector DB / new CIO agent

## Integration after observer completes

1. Merge draft PR when operator authorizes
2. Optional controlled backfill: publish scaffold theses for material missing symbols
3. Wire coverage report into CC + `/cio thesis symbol SCHG`
4. Connect research-gap triggers → Hermes request queue (budgeted)
5. On research completion → reassessment → new `symbol_*@vN` (existing #389 loop)

## Operator role context

`config/operator_portfolio_roles.json` records SCHG=GROWTH as operator declaration
(not a buy recommendation).

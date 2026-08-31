# Overnight F3 — Per-provider search budget survives process

**Wave:** Overnight F3  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0` (shorthand; rail is the unconditional raise)  
**Branch:** `fix/overnight-f3-search-budget`  
**Deploy:** none  
**Overlap:** does **not** edit F1/F2 exclusive `scripts/lib/cio_residual_web.py` or bulk-caller census files; exposes shared `check` / `try_consume` / `guard` for those waves to call.

---

## Finding

PR #719 shipped `scripts/lib/search_budget.py` — per-provider daily/monthly ceilings, durable path under `production_state_root()/data/runtime/search_budget.json`, and DENY-on-unreadable for `check()`. Two gaps remained for the AGENTS.md §12 "Search providers" rail ("Budget state **persists to disk or DB, per provider**. An in-memory cache does not survive cron"):

1. **Write-side fail-open.** `record()` caught `BudgetUnavailable` and rebuilt `{"providers": {}}`, then atomically replaced the corrupt file — resetting counters to near-zero and permitting spend.
2. **Cross-process race.** `guard()` was check-then-record without a lock. Two cron invocations observing the last free unit could both spend.
3. **Representative caller fail-open.** `scripts/brave_search._check_budget` set `_shared_check = None` on ImportError and fell through to a **release-relative** local ledger — exactly the sensor that under-reported 15% while the provider dashboard hit the ceiling.

---

## STORE SET (dry-run quotes)

Measured 2026-08-31T05:05Z from this worktree against the live persistent root (read-only):

```
production_state_root → /home/johnclaw/trade-ai-releases/persistent-state
budget_path           → …/persistent-state/data/runtime/search_budget.json
exists                → True
schema                → SearchBudget@v1

brave   daily_used=23 / daily_limit=25
        monthly_used=23 / monthly_limit=850  monthly_pct=2.7  alert=ok
tavily  daily_used=0  / 20 ; monthly_used=0 / 500
searxng daily_used=0  / 10000 ; monthly_used=0 / 300000
```

Ledger callers observed this month: `aegis_social_sentiment`, `aegis_transcript_discovery`.  
No write to the live ledger in this tranche — tests use `tmp_path` roots only.

---

## Change this tranche

| File | Change |
|------|--------|
| `scripts/lib/search_budget.py` | Extend (prefer extend over new `provider_search_budget.py`). Exclusive flock sidecar; `try_consume` atomic check+count; `record` refuses to overwrite a corrupt ledger; `guard`/`note` accept `root`/`now`; shared API documented for F1/F2. |
| `scripts/brave_search.py` | Representative caller: ImportError of shared budget → **DENY** (never `_shared_check = None` fall-through). |
| `tests/test_overnight_f3_search_budget.py` | Process-survival, flock race, never-fail-open, per-provider caps, caller source rail. |
| `scripts/run_cio_hardening_ci.py` | Allowlist gate `overnight_f3_search_budget`. |
| This audit note | Evidence. |

---

## Rails (verified by tests)

| Rail | How |
|------|-----|
| Check BEFORE call | `check` / `try_consume` / `guard` — callers return `[]` / False when denied |
| Never fail open | Corrupt ledger → `BudgetUnavailable` / `allowed=False`; record skips overwrite |
| Daily + monthly per provider | Independent counters; env overrides `SEARCH_BUDGET_<P>_<SCOPE>` |
| Survives cron | Durable JSON under `production_state_root/data/runtime`; fresh-process subprocess test |
| Concurrent cron | `try_consume` under exclusive flock — exactly one of two racers spends the last unit |

---

## What F3 deliberately does **not** do

- Does not re-census or re-bind bulk Brave callers (WAVE F1+F2).
- Does not change SearXNG pool health / degradation messaging (WAVE F4).
- Does not install cron, promote CURRENT, or spend a live search credit.
- Does not create `provider_search_budget.py` — existing module extended in place.

---

## Reproduction

```bash
python3 -c "
from scripts.lib.search_budget import budget_path, all_status
from scripts.lib.canonical_store_registry import production_state_root
print(production_state_root())
print(budget_path())
print(all_status())
"
python3 -m pytest -q tests/test_overnight_f3_search_budget.py tests/test_search_budget_and_health.py
```

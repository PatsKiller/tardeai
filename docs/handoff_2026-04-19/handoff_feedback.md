# Handoff Feedback — New Session Architect Review

**Reviewed by:** Claude Opus 4.6 (fresh session, no prior context)
**Date:** 2026-04-20
**Documents reviewed:** All 9 canonical docs in handoff_2026-04-19/
**Purpose:** Identify doc drift, ambiguities, and risks before executing Tier 1

---

## Overall Assessment

The handoff documentation is **exceptionally thorough** — among the best-organized project handoffs I've seen. The tiered structure, pre-flight checks, investigation-before-implementation discipline, and explicit acceptance criteria make it possible to pick up work confidently without the original session context.

**Rating: 9/10** — The 1 point deduction is for the specific issues below, all of which are minor and correctable.

---

## Issues Found

### Issue 1: Password in plaintext in git-tracked file
**File:** `collaboration_handoff_2026-04-19.md`, line 29
**Content:** Plaintext Postgres password was present.
**Risk:** This file is in `docs/` which IS tracked by git. If pushed to GitHub (even a private repo), secrets in repo history are permanent.
**Resolution:** ✅ FIXED 2026-04-20 — All plaintext passwords replaced with `$DB_PASSWORD` references throughout handoff docs.

### Issue 2: Phase 8D-3c status stale in roadmap
**File:** `roadmap_database_and_enhancements_2026-04-19.md`, line 26
**Says:** Previously "8D-3c in progress"
**Resolution:** ✅ FIXED 2026-04-20 — Changed to "✅ COMPLETE (8A through 8D-3c)"

### Issue 3: Holdings producer attribution may be wrong
**File:** `schemas_reference_2026-04-19.md`, line 59
**Says:** `holdings` table producer is `scripts/portfolio_ai_analyst.py` via `db_adapter.save_holdings()`
**Concern:** Earlier investigation (Phase P0 report) showed `portfolio_loader.py` and `portfolio_repricer.py` write `holdings.json` directly — NOT through db_adapter. The orchestrator (`portfolio_orchestrator.py`) coordinates the pipeline but also does direct JSON I/O. The actual producer chain for the Postgres `holdings` table should be verified during P2-1 pre-flight.
**Impact:** Low — P2-1 investigation will reveal the truth. But the doc could mislead someone who trusts it without checking.

### Issue 4: Line number references in rewrite scope are stale
**File:** `portfolio_ai_analyst_rewrite_scope.md`, lines 19-30
**Says:** References like "lines 260-335", "lines 365-424", "lines 733-748"
**Reality:** Phase 8C added ~200 lines of personal situation helpers, shifting all subsequent line numbers. The duplicate `__main__` block (Issue 2 in the doc) was already fixed in commit `fd19709`. The dead code in `_exec_summary` (Issue 3) was already fixed in commit `370d173`.
**Impact:** Low — the doc is background reading, and function names (not line numbers) should be used for navigation. But a developer who grep-by-line-number would be confused.
**Recommendation:** Add a note at the top: "Line numbers reference the pre-Phase-8 state of the file. Use function names (`_portfolio_context`, `_roth_conversion_analysis`, etc.) for navigation, not line numbers."

### Issue 5: Doc paths inconsistency
**File:** `collaboration_handoff_2026-04-19.md`, lines 36-38
**Says:** Previously referenced `/mnt/user-data/outputs/...` paths.
**Reality:** Docs are at `docs/handoff_2026-04-19/` (relative to project root).
**Resolution:** ✅ FIXED 2026-04-20 — All `/mnt/user-data/outputs/` references replaced with `docs/handoff_2026-04-19/`.

### Issue 6: schemas_reference says price_cache has 0 rows
**File:** `schemas_reference_2026-04-19.md`, line 133
**Says:** "Current state: 0 rows (cache loads on-demand from JSON; Postgres mirror not yet populated)"
**Note:** This is correct as of the doc date. P2-2 will populate it. Not a bug, just confirming this matches expectations and pre-flight should verify.

---

## Ambiguities That Need Architect Decision

### Ambiguity 1: Who should produce `holdings` Postgres rows?
The doc says `portfolio_ai_analyst.py` but the actual holdings.json is written by `portfolio_loader.py` → `portfolio_repricer.py`. The `save_holdings` in db_adapter is called by neither. Options:
- **(A)** Wire `portfolio_loader.py` to call `db_adapter.save_holdings()` after writing JSON
- **(B)** Wire `portfolio_orchestrator.py` to call it after the full pipeline completes
- **(C)** Wire `portfolio_repricer.py` to call it after repricing

P2-1 investigation will surface this. Recommend discussing with architect after investigation.

### Ambiguity 2: Snapshot data shape for db_adapter.save_snapshot
The `save_snapshot` function expects a dict with `date`, `total_value`, `source`, and optional full JSONB `data`. But `snapshot_index.json` is a flat `[{date, fidelity_401k, schwab_rollover_ira, ...}]` array — different structure. The investigation needs to confirm whether `save_snapshot` gets called with the right shape.

### Ambiguity 3: Phase 0 (Data freshness gate) scope
The roadmap mentions Phase 0 but the tier_1 doc doesn't include a detailed prompt for it. It's listed as Task 4 in Tier 1 but the investigation/implementation prompts appear less developed than Tasks 1-3.

---

## Positive Observations

1. **Dual-write semantics** are extremely well-documented with the "NEW value, not OLD" rule called out in 3 separate docs. This prevents the exact bug that was found and fixed during Phase 8D-1.

2. **The dormancy pattern** (8D-3c historical context block) is elegant — code ships now, activates naturally as data accumulates. No flag-day migrations needed.

3. **Backfill timestamp at midnight** is a smart invariant that prevents ordering bugs. Well-documented.

4. **Tier 4 readiness checklist** is the right call — refusing to write implementation prompts for work that can't be tested prevents stale-prompt drift.

5. **Investigation-before-implementation** discipline is critical and well-enforced across all tier docs.

---

## Recommendation

Proceed with P2-1 pre-flight. The issues above are all minor and don't block execution. The password issue (Issue 1) should be addressed before any GitHub push.

---

*Feedback written 2026-04-20 by fresh Claude session after reading all 9 handoff documents.*

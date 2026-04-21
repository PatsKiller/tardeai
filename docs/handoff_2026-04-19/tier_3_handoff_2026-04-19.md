# Trade AI v12 — Tier 3 Handoff: Forward-Looking Features

**Version:** 1.0  
**As-of:** 2026-04-19  
**Tier:** 3 — Forward-looking features (~15-20 hours)  
**Audience:** Developer executing tasks via Claude Code  
**Prerequisites:** Tier 1+2 complete  
**Status:** Investigation prompts ready; implementation prompts TBD after architect review

---

## Important: Tier 3 is design-heavy

Tier 1+2 tasks were straightforward database wiring with established patterns. **Tier 3 tasks require design decisions** that benefit from human (architect) input after investigation.

**Workflow change for Tier 3:**

1. Run pre-flight checks
2. Paste investigation prompt into Claude Code
3. Send investigation report to architect
4. **STOP and wait for design discussion**
5. Architect provides implementation prompt based on findings
6. Execute implementation
7. Verify, commit

Don't skip step 4. The investigation reports are designed to surface unknowns that need decisions, not to provide enough context to skip discussion.

---

## Task 10: Phase 1 — Remove remaining hardcoded numbers

**Effort:** ~3-4 hours  
**Risk:** Medium (changes AI prompt outputs)  
**Why:** 8C completed personal_situation hardcoded values. But other functions still have hardcoded benchmark thresholds, scoring weights, etc.

### Context

Phase 8C (commits 64e9243, ae32fdf) eliminated hardcoded personal values from `_personal_context()` and `_roth_conversion_analysis()`. But `portfolio_ai_analyst.py` is large (~3000+ lines) and likely contains many other hardcoded values: scoring weights, percentile thresholds, "good vs bad" cutoffs, sector concentration limits, etc.

### Pre-flight

```bash
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
git status --short

# Quick scan for likely candidates
grep -nE "= [0-9]+\.?[0-9]*$" scripts/portfolio_ai_analyst.py | head -30
wc -l scripts/portfolio_ai_analyst.py
```

### Investigation prompt for Claude Code

```
Phase 1 investigation: Audit hardcoded numbers in portfolio_ai_analyst.py.

Generate report at /tmp/phase_1_audit.md.

Goal: Find every hardcoded number that should be configuration, NOT logic.

## SECTION A: Scoring weights and thresholds

1. grep portfolio_ai_analyst.py for assignments like "= [0-9]+" 
2. Look at the surrounding context for each
3. Categorize each finding as:
   - LOGIC (e.g., "i = 0" loop counter, "len > 0" guard) - leave alone
   - CONFIG (e.g., "score_weight = 0.4", "percentile_cutoff = 75") - candidate for extraction
   - DATA-DERIVED (e.g., "remaining = ceiling - income") - already correct, leave alone

For each CONFIG candidate, document:
- Variable name and current value
- Function it lives in
- Apparent meaning (best guess from context)
- Estimated impact if changed (sensitivity)

## SECTION B: Sector/category limits

4. Find any references to sector concentration limits, position size limits, etc.
5. Are these hardcoded or pulled from config?

## SECTION C: AI prompt thresholds  

6. Look for thresholds like "if score > 7.5" or "if alpha < 2.0%"
7. These often live near AI prompt construction code
8. Document each with context

## SECTION D: Magic strings that should be enums

9. Search for repeated string literals that act as categories ("BUY", "SELL", "HOLD", "AGGRESSIVE", etc.)
10. List candidates for enum extraction

## SECTION E: Existing config patterns

11. grep scripts/ for "config" or "weights.yaml" 
12. Show how existing config is loaded (if any)
13. Is there a precedent for runtime-configurable values?

## SECTION F: Risk assessment

14. For each CONFIG candidate, rate the risk of refactoring:
    - LOW: pure threshold, easy to test
    - MEDIUM: affects scoring (testable but needs verification)
    - HIGH: affects core logic flow (significant verification needed)

DO NOT modify files. Investigation only.

STOP after producing /tmp/phase_1_audit.md.
```

### After investigation: PAUSE for architect review

Architect tasks:
1. Review the audit report
2. Decide which candidates to extract (might be 5, might be 50)
3. Decide where to put extracted config (existing weights.yaml? new config file? environment variables? Personal Situation modal?)
4. Sequence the extractions (some may have dependencies)

Architect produces:
- Implementation prompt(s) — possibly broken into multiple tasks
- New config schema if needed
- Test plan to verify AI outputs don't degrade

### Anticipated implementation pattern

For each extracted constant:

1. Add to config file
2. Update function to read from config (with safe fallback default)
3. Run an AI prompt before and after, diff outputs
4. Verify expected behavior preserved

### Commit message template

```
Phase 1: Extract hardcoded thresholds from portfolio_ai_analyst.py

Removes N hardcoded values from analyst functions, replaced with
config lookups from [config_file]. Preserves AI behavior while
making thresholds tunable without code changes.

Extracted constants:
- threshold_X (was 7.5) → config.threshold_X
- weight_Y (was 0.4) → config.weight_Y
- ... [list all]

Files modified:
- scripts/portfolio_ai_analyst.py
- [config file]

Verified:
- AI prompt output diffs before/after show no functional change
- Default values preserve existing behavior
- Config changes propagate correctly
```

### Flag back to architect

- Total candidate count from audit
- Any "scary" hardcoded values that affect core logic
- Recommendation on config storage location

---

## Task 11: Phase 4 — Smart cache invalidation

**Effort:** ~5-7 hours  
**Risk:** High (cache bugs are hard to diagnose)  
**Why:** Currently caches are TTL-based. Want event-driven invalidation (e.g., when holdings change, sector mix cache invalidates).

### Context

The system has multiple caches: news_cache.json, analyst_data.json, possibly others. These currently expire on time. But sometimes data changes earlier (you sell a position → analyst data for that ticker is suddenly less relevant). Phase 4 adds smart invalidation triggers.

### Pre-flight

```bash
# Find existing caches
grep -rln "cache" scripts/ | grep -v __pycache__ | head -20
ls -la data/portfolios/state/ | grep -i cache
```

### Investigation prompt

```
Phase 4 investigation: Map the existing cache landscape.

Generate report at /tmp/phase_4_caches.md.

## SECTION A: Cache inventory

For each cache (file, in-memory, or otherwise):
1. Filename or variable name
2. What's stored
3. Producer (what populates it)
4. Consumer (what reads from it)
5. TTL or expiration logic (if any)
6. Invalidation triggers (if any)
7. Size and update frequency

## SECTION B: Cache misses and hits

1. Is there logging of cache hit/miss rates? Show it
2. Are there any obvious cache invalidation bugs (stale data persisting)?

## SECTION C: Events that SHOULD invalidate caches

For common state changes, identify which caches become stale:
1. New position added to holdings → which caches stale?
2. Position sold → which caches stale?
3. Personal_situation field changed → which caches stale?
4. New AI run completed → which caches stale?

## SECTION D: Existing event/notification infrastructure

1. Is there any pub/sub, event emitter, or callback system already?
2. How would caches get notified of state changes today?

## SECTION E: Risk profile of each cache

For each cache, rate:
- Cost of stale read (catastrophic / annoying / ignorable)
- Cost of cold cache (expensive recompute / quick recompute)
- Frequency of staleness vs hits

Cache strategy depends on this risk profile.

DO NOT modify files.

STOP after producing /tmp/phase_4_caches.md.
```

### After investigation: PAUSE for architect review

Architect tasks:
1. Review cache inventory  
2. Decide architecture: event bus vs callback registration vs filesystem-watch vs simpler timestamp comparison
3. Decide which caches to migrate first (highest staleness risk first)
4. Decide whether to add shared cache infrastructure or per-cache custom logic

### Anticipated complexity

Phase 4 could be small (just add timestamp checks where cache is read) or large (build a full event-driven invalidation system). The investigation report will inform this.

### Commit message template (placeholder)

```
Phase 4: [TBD based on chosen architecture]

[Will be filled in after design decision]
```

### Flag back to architect

- Cache inventory size
- Highest-risk staleness scenarios
- Whether existing code patterns support event-driven invalidation

---

## Task 12: P3-3 — action_signals time-series

**Effort:** ~3-4 hours  
**Risk:** Medium (new historical table)  
**Why:** Currently `action_signals.json` always has CURRENT signals. Lose history. Want to query "how often was LMT a BUY over past month?"

### Context

`action_signals.json` is overwritten each run. New table `action_signals_history` preserves the timeline.

### Pre-flight

```bash
ls -la data/portfolios/state/action_signals.json
python3 -c "
import json
d = json.load(open('data/portfolios/state/action_signals.json'))
print(f'tickers: {len(d) if isinstance(d, dict) else len(d)}')
print(f'sample: {json.dumps(list(d.items())[0] if isinstance(d, dict) else d[0], indent=2)[:300]}')"
```

### Investigation prompt

```
Phase P3-3 investigation: Map action_signals.json so we can design action_signals_history table.

Generate report at /tmp/phase_p33_signals.md.

## SECTION A: action_signals.json structure
1. Pretty-print 3 sample entries
2. Document every field
3. Note any nested structures

## SECTION B: Producer
4. Find the script that writes action_signals.json
5. Show the write function
6. When does it run?

## SECTION C: Consumers
7. Files that read action_signals.json
8. What fields do they extract?
9. Does any consumer need historical data? (query like "show me LMT signal history")

## SECTION D: Volume estimation
10. Number of tickers with signals at any given time
11. Update frequency
12. Project: rows per day, rows per year

## SECTION E: Schema design considerations
13. Primary key candidate: (signal_date, ticker)? Or include action?
14. Should we store every run, or only when action changes?
15. JSONB vs columns: which fields need to be queryable?

DO NOT modify files.

STOP after producing /tmp/phase_p33_signals.md.
```

### After investigation: PAUSE for architect review

Architect decisions:
- Schema design (columns vs JSONB)
- Granularity (every run vs change-only)
- Backfill strategy (start fresh or import any existing snapshots)

### Implementation prompt (placeholder — to be designed)

```
Phase P3-3 implementation: action_signals_history table.

[Implementation prompt will be designed after investigation]

Anticipated structure:
- New table action_signals_history with (signal_date, ticker, action, score, ...)
- Daily writer captures every signal
- Backfill: start fresh (no historical data exists)
- Indexes on (signal_date) and (ticker) for common queries
```

### Commit message template

```
Phase P3-3: action_signals historical time-series

Adds action_signals_history table tracking every signal over time.
Enables historical queries like "ticker signal frequency", "consecutive
GO streaks", "signal-vs-outcome correlation analysis".

Files modified:
- linux_port_v2/linux/db_setup.sql - new table
- scripts/db_adapter.py - save_signal_history function
- scripts/[signal_writer].py - dual-write call

Verified:
- Signal generation populates history table
- Sample query: signals per ticker over past 30 days
```

---

## Task 13: P4 — Snapshot completeness pass

**Effort:** ~3-4 hours  
**Risk:** Low (audit + documentation)  
**Why:** Ensure every state file has either a Postgres mirror OR documented decision to remain JSON.

### Context

Catch-up audit. After Tier 1+2 migrations, some state files may have been missed or new ones added. Inventory and document.

### Pre-flight

```bash
ls -la data/portfolios/state/
ls -la data/portfolios/snapshots/ 2>/dev/null
ls -la data/imports/ 2>/dev/null
```

### Investigation prompt

```
Phase P4 investigation: Complete state file inventory and migration audit.

Generate report at /tmp/phase_p4_inventory.md.

## SECTION A: Full file inventory

For EVERY .json file under data/, document:
1. Full path
2. Producer script(s)
3. Consumer script(s)
4. Update frequency
5. Last modified time
6. File size
7. Current state: JSON-only / dual-write / Postgres-only / orphaned

## SECTION B: Migration decisions

For each file marked JSON-only or orphaned, recommend:
- KEEP AS JSON (with reason: configuration / hand-edited / ephemeral)
- MIGRATE TO POSTGRES (with reason: time-series / queryable / volume)
- DEPRECATE (no longer used, remove)

Use decision criteria from schemas_reference.md.

## SECTION C: Existing dual-write coverage

Audit: for each file currently dual-writing to Postgres, verify:
1. Both paths actually fire on writes
2. Read paths can fall back to JSON if Postgres unavailable
3. Schema in DB matches structure in JSON

## SECTION D: Findings

List any:
- Files producers can't be found (orphaned, possibly from old code)
- Files consumed but never updated (stale)
- Files updated but never consumed (dead writes)
- Schemas that drift between JSON and Postgres

DO NOT modify files.

STOP after producing /tmp/phase_p4_inventory.md.
```

### After investigation: PAUSE for architect review

Architect decisions:
- Which files to migrate (any new candidates)
- Which to deprecate
- Update schemas_reference.md with current decisions

### Implementation

Tasks per file:
- Migrations follow same pattern as P3-1, P3-2, P3-3
- Deprecations: delete file, remove producer/consumer code, update docs

### Commit message template

```
Phase P4: Snapshot completeness audit

Reviewed all state files. Decisions:
- Migrated to Postgres: [list]
- Deprecated and removed: [list]
- Confirmed JSON-only: [list]

Updated schemas_reference.md with current state.

Files modified:
- [whatever migrations / deprecations]
- docs/handoff_2026-04-19/schemas_reference_2026-04-19.md
```

### Flag back to architect

- Surprising findings (orphaned files, dead code paths)
- Files that defied easy categorization
- Recommendations for future structural improvements

---

## After Tier 3 completes

Tier 3 is the most variable in scope because of design decisions per task. Could be 15-20 hours as estimated, or 25-30 hours if Phase 4 turns into a substantial event-driven invalidation system.

After Tier 3:
1. Push commits to GitHub
2. Update roadmap (mark Tier 3 complete)
3. Update schemas_reference.md with all new tables
4. Reassess Tier 4 readiness — Phase 11 needs ~30-60 days of P2-1 snapshot accumulation

---

*Tier 3 handoff document created 2026-04-19. Update as design decisions are made and tasks are executed.*

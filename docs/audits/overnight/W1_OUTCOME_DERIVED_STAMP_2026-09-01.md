# W1 — OUTCOME_DERIVED stamp amendment

Status: ACTIVE  
as_of: 2026-08-31T16:54:38Z  
Measured at: hub worktree wt/n3-outcome-derived-stamp · persistent-state lesson_candidates.jsonl  
Authority: READ_ONLY_ADVISORY · MBI=0

## Problem

Night Three settled 152 outcomes but `OUTCOME_DERIVED` stayed 0: `build_lesson_candidates` skipped existing `lesson_id`s, and the SCHD/TRIM row was unstamped with empty `supporting_outcome_ids` + nonempty `counterexamples` — projection alone called it RESEARCH_DERIVED.

## Fix

1. Projection: unstamped rows with `counterexamples` project as OUTCOME_DERIVED.
2. Apply path: append-only provenance amendment for unstamped outcome-evidenced rows (same lesson_id). Never rewrite in place. Never reclassify explicit RESEARCH_DERIVED.

## Validation

```
pytest tests/test_overnight_d3_lesson_provenance.py — 11 passed
```

Dry-run (production state):

```
observations_read    586
amended              1
would-amend SCHD / TRIM  lid=e38856b4febcafbf8b25 → OUTCOME_DERIVED
```

Apply (append-only):

```
written              2
amended              1
```

After fold (last-wins): **OUTCOME_DERIVED raw = 1** (was 0). Projected OUTCOME_DERIVED = 1.

## What did not work

Free-text desk recommendations still fail `_direction` clustering — only one OUTCOME_DERIVED lesson exists despite 586 observations. That is a separate finding; not solved here.

## Ownership

Grok lesson/outcome path. No INDEX.md. No merge/deploy (Claude Code).

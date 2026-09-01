# Overnight D3 — Lesson provenance (`OUTCOME_DERIVED` vs `RESEARCH_DERIVED`)

**Wave:** Overnight D3  
**Date:** 2026-08-31  
**Authority:** READ_ONLY_ADVISORY · `MBI_BEHAVIOR=0` (shorthand; rail is the unconditional raise)  
**Branch:** `fix/overnight-d3-lesson-provenance`  
**Store set:** none rewriting historical lesson JSONL contents  
**Deploy:** none

## Finding

The lesson lane held ~1,617 candidates / ~1,467 applications with **no outcome
references** — research / advisory-KB derived — while
`outcome_to_lesson.build_candidates` began writing candidates backed by
`OutcomeObservation@v1`. Without a permanent field, readers could blur the two
and poison scores by treating research history as outcome evidence.

`cio_agent_brief.learned` already *counted* research vs outcome with heuristics
(`hermes_result_id` vs `supporting_outcome_ids` / `correlated_outcome_ids`). D3
makes the distinction a durable schema field.

## Contract

| Value | Meaning |
|-------|---------|
| `OUTCOME_DERIVED` | Candidate produced from recorded outcomes (`outcome_to_lesson.build_candidates`) |
| `RESEARCH_DERIVED` | Research / CASE_SUMMARY / advisory-KB lineage (no outcome support), including the pre-D3 corpus |

**Schema field:** `lesson_provenance`

## Change this tranche

1. **`scripts/lib/outcome_to_lesson.py`**
   - Constants: `LESSON_PROVENANCE_FIELD`, `PROVENANCE_OUTCOME_DERIVED`,
     `PROVENANCE_RESEARCH_DERIVED`
   - `project_lesson_provenance` / `with_lesson_provenance` — **reader projection
     only**; never rewrite disk
   - `build_candidates` stamps `OUTCOME_DERIVED` (including counterexample-only
     rows where `supporting_outcome_ids` is empty — stamp is load-bearing)
   - `candidates_from_case_summaries` stamps `RESEARCH_DERIVED`
2. **`scripts/build_lesson_candidates.py`** — dry-run / apply detail includes
   `lesson_provenance` (writers already stamp via `build_candidates`)
3. **`scripts/lib/cio_institutional_learning.py`** — docstring on
   `lesson_candidate_v2` notes writers own the stamp (no silent inference there)
4. **`tests/test_overnight_d3_lesson_provenance.py`** + hardening CI gate
   `overnight_d3_lesson_provenance`
5. This audit note

## Projection rule (legacy rows)

Unstamped row:

- nonempty `supporting_outcome_ids` → display `OUTCOME_DERIVED`
- otherwise → display `RESEARCH_DERIVED`

Explicit `lesson_provenance` always wins. Existing JSONL bytes are not
rewritten; apply continues to **append-only** skip-by-`lesson_id`.

## Invariants

- Do not reclassify historical rows in place.
- Do not poison scores by mislabelling research history as outcome-derived.
- `memory_behavior_influence` remains 0; observational / advisory only.

## Proof commands

```bash
python3 -m pytest -q tests/test_overnight_d3_lesson_provenance.py
python3 -m pytest -q tests/test_outcome_to_lesson.py
python3 scripts/check_test_coverage.py --fail-on-new
```

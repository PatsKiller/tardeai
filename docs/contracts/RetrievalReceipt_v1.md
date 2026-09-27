# RetrievalReceipt@v1 — proof the ladder ran before generation

```
Status:      ACTIVE (Wave 1 tranche 1 — SHADOW; emitted by scripts/lib/intelligence_client.py)
as_of:       2026-09-27T19:30:00-04:00
Measured at: cbf603526 (origin/main) / not measured at runtime yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1
```

Emitted by `intelligence_client.retrieve_or_generate(ctx, question, generator)` to `data/cio/retrieval_receipts.jsonl`.

| Field | Meaning |
|---|---|
| receipt_id ("rr_" + 16 hex), context_id, lane_id, subject_guid, symbol | joins |
| question {text, question_class, horizon} | question_class ∈ thesis · stance · bull · bear · risk · catalyst · what_changes (maps to a thesis field) |
| ladder[] | seven rows, always: {step 1..7, key, store, hit, refs[], ms, note?} — 1 deterministic (Hermes fingerprint) · 2 thesis field · 3 evidence (research objects 72 h + Hermes results) · 4 contradiction · 5 citation (URLs already captured) · 6 version (thesis pin) · 7 semantic (`not_installed` until the embedding table + local model) |
| decision | HIT_FRESH (step 1 or 2 hit inside the class SLA) · HIT_STALE (hit outside it) · HIT_PARTIAL (only evidence/citation) · MISS |
| reused_refs[] | what an answer may cite instead of generating |
| generated, generation_reason | SHADOW always generates (reason SHADOW); ENFORCED generates only when not HIT_FRESH (reason = decision) or OPERATOR_FORCED |
| mode, release_sha, created_at | |

**Measure.** Duplicate generation rate = receipts with decision HIT_FRESH and generated = true ÷ all generated (03 §7). A receipt with an empty ladder is a defect.

# MemoryContext@v1 — what an actor holds before it acts

```
Status:      ACTIVE (Wave 1 tranche 1 — SHADOW; emitted by scripts/lib/intelligence_client.py)
as_of:       2026-09-27T19:30:00-04:00
Measured at: cbf603526 (origin/main) / not measured at runtime yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); approval pkg-20260927-cogx-w1-d9e1
```

Emitted by `intelligence_client.open_context(actor, purpose, subjects)` and appended (event `OPENED` / `REFUSED`)
to `data/cio/memory_contexts.jsonl`; the matching `MemoryCommit@v1` row (event `COMMITTED`) is appended by `commit`.

| Field | Type | Meaning |
|---|---|---|
| schema | "MemoryContext@v1" | |
| context_id | "ctx_" + 16 hex | required by Ring 2 refusals (Wave 2) |
| actor | {lane_id, agent_id, release_sha, boot_id} | lane_id required |
| purpose | RESEARCH · DECIDE · ADVISE · MONITOR · CURATE · ANSWER_OPERATOR | DECIDE/ADVISE fail closed in ENFORCED mode |
| mode | SHADOW · ENFORCED | from `TRADEAI_INTELLIGENCE_MODE`, default SHADOW |
| subjects[] | {input, guid ("SEC:<security_guid>" or namespaced), security_guid, issuer_guid, symbol, identity_status} | ticker strings are resolved through the identity registry; UNRESOLVED is degraded (SHADOW) or refused (ENFORCED) |
| opened_at, as_of | iso8601 | as_of is the bitemporal read point |
| facts[] | {fact_id, class, memory_type, subject_guid, symbols, confidence, freshness_state, age_hours, contradiction_state, status, lineage_ref} | from the durable agent memory provider via `retrieve_for_context` |
| fact_ids[] | memory ids | also written to a MemoryConsumptionReceipt@v1 (consumer `intelligence_client`) |
| thesis | {thesis_id, version, pin, stance, summary, evidence_for, counter_evidence, invalidation_conditions, catalysts, what_changes_my_mind, research_gaps, status, age_hours, freshness_state} | the living symbol thesis (30-day SLA) |
| beliefs[] | InstrumentBelief@v1 subset | from the instrument record |
| open_contradictions[] | {contradiction_id, symbol, left, right, opposition, state} | ResearchContradictionCandidate rows for the symbol |
| contradiction_state | NONE · OPEN · UNKNOWN | |
| prior_decisions, operator_turns | {state: UNMEASURED} | join the record in Wave 2 |
| lessons[], lessons_state | [] , NONE_PROMOTED | procedural memory (Wave 3) |
| retrieval_receipt | receipt_id or null | set by `retrieve_or_generate` |
| degraded, degraded_reasons[], failed_classes[] | bool, [str], [str] | every loader failure is named |
| authority, memory_behavior_influence | READ_ONLY_ADVISORY, 0 | invariant |

**Rules.** No field may be a behaviour field (`cio_instrument_record.BEHAVIOR_FIELDS`); `commit` refuses any payload that names one.
A DECIDE/ADVISE actor that cannot open a context in ENFORCED mode HOLDS (`HOLD_MEMORY_UNAVAILABLE`); it never substitutes a raw store.

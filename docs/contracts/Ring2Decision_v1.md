# Ring2Decision@v1 — did this work carry a MemoryContext?

```
Status:      ACTIVE (Wave 2 tranche 1 — SHADOW at every surface; ENFORCED only by operator policy row)
as_of:       2026-09-27T21:20:00-04:00
Measured at: 6fd7b9589 (origin/main) / not measured at runtime yet
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Ring 2 can only refuse, never act.
Package:     docs/architecture/cognitive_transformation_20260927/ (PR #1304); Wave 2 spec docs/ops/COGX_WAVE2_PACKAGE_SPEC.json
```

Emitted by `memory_ring2.check(surface, who, context_id, required=…)` at four chokepoints: `llm_consumption.gate_and_generate`
(research-class processes: registry `memory_context_required` or category ∈ Research/Hermes/Watch/AdvisoryDesk/CIO), the governed model
bridge (:8766, header `X-TradeAI-Context-Id`, 428 when refused), `research_thesis_delta.accept_research_result` (returns
`{ok: false, refused: true, refusal_reason: MEMORY_CONTEXT_MISSING}`) and `CIOActionLedger.create_action` (raises `MemoryContextRequired`).

| Field | Meaning |
|---|---|
| surface, who | chokepoint and the process / actor / research id |
| mode | SHADOW · ENFORCED — from `config/memory_influence_policy.json` `ring2.surfaces[surface]` → `ring2.default`; `TRADEAI_INTELLIGENCE_MODE` overrides all (global kill switch) |
| has_context, required, context_id | what was carried and whether the surface demanded it |
| decision | ALLOW · ALLOW_MISS (SHADOW, recorded) · REFUSE (ENFORCED, recorded as REFUSED with disposition HOLD_MEMORY_CONTEXT_REQUIRED) |
| event | MISS · REFUSED — appended to the memory-contexts JSONL beside MemoryContext rows |

Threading: producers that cannot pass a kwarg use the process-current context (`intelligence_client.set_current_context`, set by
`shadow_open`, cleared by `shadow_commit`); `gate_and_generate` falls back to it; both bridge clients send it as headers.
The façade's `commit` publishes `memory.delta` (MemoryDelta@v1) on the CIO event bus when deltas are present; no consumer wakes on it yet.

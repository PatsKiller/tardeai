# ADR-005 — LangGraph conditional, not a platform rewrite

Status:      ACTIVE
as_of:       2026-08-16T23:13:59-04:00
Measured at: efcc51365 / not measured

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

Trade AI's agent orchestration already owns durable state: a sole wake claimant
with explicit `NEW_RUN` / `RESUME_RUN` intents, a hash-chained append-only event
store, `wake_id` + `trace_id` lineage, a canonical `ContextEnvelope`, a memory
abstraction, and a governed learning loop. Phase 8 must decide whether to
introduce LangGraph (a graph-based workflow framework) on top of this — or
rebuild orchestration around it.

The controlling principle is explicit: *"No new framework may become a second
system of record."*

## Decision

**Do not rebuild Trade AI around LangGraph.** LangGraph is used **only
conditionally**, and only inside **one bounded worker**, if — and only if — the
measured complexity gate (`scripts/lib/langgraph_complexity_gate.py`) triggers a
`PILOTED` verdict from real `AgentRunTrace`-shaped evidence. The default gate
answer is `NOT_REQUIRED`, and `NOT_REQUIRED` is treated as a success.

All cross-boundary identity remains external: `decision_id`, `case_id`,
`trace_id`, and `context_digest`. LangGraph-internal node/checkpoint ids are
never permitted to become the canonical identity of a decision, case, or memory
record.

## Consequences

- The hash-chained event store, `office_truth`, the memory abstraction, and the
  decision identity surface are unchanged and remain authoritative.
- LangGraph, if ever piloted, is scoped to a single bounded worker and is
  **never** a system of record, decision store, memory store, truth store, or
  global runtime.
- A pilot is ineligible to influence synthesis unless it reproduces the same
  lineage and context digest as the incumbent orchestration.
- `letta_decision()` remains `DEFERRED`: Trade AI already owns agent identity,
  plans, cases, decisions, memory abstraction, workflow, and governance.

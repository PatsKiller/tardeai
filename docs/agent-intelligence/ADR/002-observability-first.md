# ADR-002 — Observability before memory activation

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

The program adds memory, MCP read tools, and proactive notification logic. If
these influence live advisory synthesis before we can observe what they change,
a silent regression is indistinguishable from a correct behavior change.

## Decision

Phase 1 builds the trace foundation (`AgentRunTrace@v1`) first. Phase 2
instruments every material wake with `wake_id` + `trace_id` and records tool
calls, notification reasoning, and follow-up bindings. Only after trace coverage
is proven (Phase 2 acceptance) do memory/context influence live behavior
(Phase 11/12 shadow → activation).

## Consequences

- No memory or MCP behavior influence is enabled until shadow acceptance passes.
- `MEMORY_BEHAVIOR_INFLUENCE` defaults to `0` and remains `0` through Phase 11.
- A wake/tool/notification that cannot be traced is not eligible to influence
  synthesis.

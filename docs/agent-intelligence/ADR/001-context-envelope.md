# ADR-001 — ContextEnvelope as canonical agent context

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

Alex and specialists each assemble their own view of the office (book, cash,
risk, plans, research, past operator feedback) with no single, versioned,
digestible context object. This makes it impossible to (a) prove what an agent
reasoned over, (b) detect a memory overriding canonical truth, or (c) replay a
decision deterministically.

## Decision

Introduce a single `ContextEnvelope@v1` (`scripts/lib/agent_context_envelope.py`)
with a deterministic content digest and a `get_context_for_agent()` chokepoint.

Key properties:
- truth and memory are structurally separated (`office_truth` vs `episodic_memory`);
- memory authority is hard-coded `NON_AUTHORITATIVE_CONTEXT`;
- missing providers are represented explicitly (`NOT_CONFIGURED` / `UNAVAILABLE`);
- the digest excludes timestamps so identical content hashes identically.

## Consequences

- All agent entrypoints must migrate to `get_context_for_agent()` (Phase 5).
- Retrieval-before-reasoning becomes auditable: a non-`OK` retrieval status is
  visible in the envelope and the trace.
- Adding a memory provider (Phase 4) does not change the envelope contract.

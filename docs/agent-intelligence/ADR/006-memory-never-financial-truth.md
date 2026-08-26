# ADR-006 — Memory never financial truth

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

If an agent can remember a price, cash balance, holding, risk limit, or broker
state and later treat that recollection as fact, a stale or hallucinated memory
could silently override the canonical system of record — an unacceptable
failure mode for a `READ_ONLY_ADVISORY` system.

## Decision

Memory is permanently `NON_AUTHORITATIVE_CONTEXT`. Canonical financial truth
always outranks memory, at admission time and at retrieval time:

1. `resolve_conflict(memories, canonical_truth_override=True)` never promotes a
   memory to primary — canonical truth wins.
2. `is_forbidden_authoritative(subject_or_field)` rejects any memory whose
   subject names a canonical financial fact (price, market value, shares, cash,
   tax balance, risk limit, broker auth state, order state, stop state,
   freshness, policy config).
3. `admit_status(...)` returns `REJECT` for forbidden-authoritative subjects and
   for records missing provenance.
4. A remembered statement is never a price, holding, cash balance, risk limit,
   or broker fact.

## Consequences

- Memory lives in a sibling section to `office_truth` in the ContextEnvelope and
  can never be written back into canonical truth.
- Disputed memory stays visible as conflict metadata, not primary context.
- Expired / retracted / superseded memory is excluded from primary context.
- This invariant is tested in `tests/test_agent_memory_governance.py` and is
  non-negotiable: no memory feature may weaken it.

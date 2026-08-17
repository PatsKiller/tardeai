# Memory Admission Policy

`READ_ONLY_ADVISORY`. This policy governs what a memory record may be admitted
as, and what it can never become. Implemented in
`scripts/lib/agent_memory_governance.py`.

## Admission statuses

`admit_status(memory_type, *, subject=None, provenance_ok=True)` returns one of:

| Status | Meaning | When |
|--------|---------|------|
| `REJECT` | not admitted | provenance missing, or subject is forbidden-authoritative |
| `ACTIVE` | admissible as primary context | explicit operator statement / preference, agent commitment, or durable case event **with provenance** |
| `CANDIDATE` | admissible as context only, never policy | inferred preference, episodic recollection, research reference, procedural hint |

`CANDIDATE` memory may inform context but can **never act as policy** — it does
not drive a decision, an order, a stop, or a risk-policy change.

### Memory types → default admission

| `memory_type` | Default admission |
|---------------|-------------------|
| `OPERATOR_EXPLICIT_PREFERENCE` | `ACTIVE` |
| `AGENT_COMMITMENT` | `ACTIVE` |
| `CASE_SUMMARY` | `ACTIVE` |
| `OPERATOR_INFERRED_PREFERENCE` | `CANDIDATE` |
| `EPISODIC` | `CANDIDATE` |
| `RESEARCH_REFERENCE` | `CANDIDATE` |
| `PROCEDURAL_HINT` | `CANDIDATE` |

## Provenance requirement

A `MemoryRecord@v1` is admitted only if it carries provenance: at least one of
`source_event_ids` or `source_refs` must be non-empty. `build_memory_record()`
raises `ValueError` otherwise. A memory with no traceable origin cannot be
admitted, regardless of type.

## Forbidden-authoritative fields

Memory whose subject names canonical financial truth is rejected. The full list
is `FORBIDDEN_AUTHORITATIVE_FIELDS` (see `MEMORY_GOVERNANCE_AND_MEM0.md`). Key
members:

- price / current price / market value
- shares / quantity / position(s) / holding(s)
- cash / cash balance
- tax balance
- risk limit
- broker auth state
- order state / status
- stop state / status
- freshness / freshness status
- policy / policy config

`is_forbidden_authoritative(subject_or_field)` is the predicate; `admit_status`
rejects any record whose subject matches it.

## Secret / token rejection

Content or subject that is secret- or token-shaped (e.g. `sk-…`, `ghp_…`,
`xox…-…`, `AKIA…`, 32+ hex literals, or anything `redact_secrets` would redact)
is rejected at build time. Secrets are never stored in memory.

## Inferred vs explicit

- **Explicit** operator statements/preferences carry operator provenance and may
  be `ACTIVE`.
- **Inferred** preferences are the agent's reading of operator behavior; they
  are `CANDIDATE` and must never be treated as an operator instruction.

In conflict, explicit outranks inferred; a newer explicit preference supersedes
an older explicit preference.

## Research memory rules

Research memory (`RESEARCH_REFERENCE`) is **reference + interpretation**, never
policy. It is always `CANDIDATE`, always `NON_AUTHORITATIVE_CONTEXT`, and is
surfaced for interpretation alongside its source refs — it does not change
production policy because something was "learned".

## Conflict resolution

`resolve_conflict(memories, canonical_truth_override=False)`:

1. Canonical truth always wins — with `canonical_truth_override=True`, no memory
   becomes primary.
2. Newer explicit operator preference supersedes older.
3. Disputed memories remain visible as conflict metadata, not primary.
4. Expired / retracted / superseded memories are excluded from primary context.

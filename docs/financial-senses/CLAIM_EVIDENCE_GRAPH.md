# Claim / evidence graph

Exposes the causal evidence behind a recommendation.

## Nodes

`FACT`, `CLAIM`, `SOURCE`, `MEMORY_REF`, `CASE_REF`, `SPECIALIST_OPINION`,
`DECISION`.

## Edges

`SUPPORTS`, `CONTRADICTS`, `DEPENDS_ON`, `QUALIFIES`, `INVALIDATES`,
`DERIVED_FROM`, `USED_BY`.

## Provenance invariants

- Every FACT requires `source` (fact-capable) + `observed_at`/`as_of` + `quality`.
- Every derived CLAIM requires incoming evidence (else `UNSUPPORTED`).
- Contradictions are preserved (support AND counterevidence).
- `MEMORY_REF` edges are `NON_AUTHORITATIVE_CONTEXT`; they cannot replace a FACT.

## Authority

Only a valid, fresh FACT is authoritative: it must have a fact-capable source,
`observed_at`/`as_of`, quality, and not be stale. A FACT that fails these checks
(e.g. `MODEL_INFERENCE` source, missing quality or timestamp) is classified
`invalid_fact_support` — preserved for diagnostics but never counted as
authoritative — and cannot make a claim actionable. Specialist opinions, claims,
cases, memory refs, and source nodes are non-authoritative by construction.

## Validation

`build_graph` runs `validate()` (provenance, edge endpoints, duplicate edge IDs)
and `detect_cycles()`. Unsupported claims and contradictions are surfaced.

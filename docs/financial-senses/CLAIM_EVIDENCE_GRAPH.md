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

## Validation

`build_graph` runs `validate()` (provenance, edge endpoints, duplicate edge IDs)
and `detect_cycles()`. Unsupported claims and contradictions are surfaced.

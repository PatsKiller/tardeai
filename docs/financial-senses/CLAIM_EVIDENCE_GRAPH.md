# Claim / evidence graph

Status:      ACTIVE
as_of:       2026-08-17T13:10:42-04:00
Measured at: efcc51365 / not measured

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

Only a valid, **explicitly FRESH** FACT is authoritative. A FACT must have a
fact-capable source, `observed_at`/`as_of`, a **governed `quality`** (one of
`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`), AND an explicit `freshness == "FRESH"`.
Missing freshness (`None` / `""`), `UNKNOWN`, or an unrecognized freshness value
are NOT fresh and can never be authoritative: they are classified
`invalid_fact_support` (or `stale_fact_support` for `STALE`), preserved for
diagnostics but never counted as authority and never able to make a claim
actionable. An unrecognized quality token is likewise rejected, never treated as
governed quality. Specialist opinions, claims, cases, memory refs, and source
nodes are non-authoritative by construction.

## Validation

`build_graph` runs `validate()` (provenance, edge endpoints, duplicate edge IDs)
and `detect_cycles()`. Unsupported claims and contradictions are surfaced.

# CIO Operator Evidence Surface

Status: IMPLEMENTED LOCALLY · `READ_ONLY_ADVISORY`

## Contract

`GET /api/v3/cio/operator-evidence` returns `CIOOperatorEvidence@v1`, a
read-only composition over existing CIO stores. It is not a second source of
truth and the React page does not infer capability state.

Every block carries:

- `source_as_of`
- `composition_as_of`
- `producer`
- `authority`

## Research provenance

Research artifacts are classified only from explicit canonical receipts:

- `RETRIEVED` — a result artifact exists.
- `USED_IN_JUDGMENT` — a use/consumption receipt is present.
- `REJECTED` — an explicit rejection state or reason is present.
- `UNKNOWN` — the available record cannot prove the relationship.

Retrieval alone never becomes use, and absence of a use receipt never becomes
rejection. Links preserve artifact, decision, entity, source, model, and trace
identity where the producer supplied them.

## Institutional cognition

Memory, prior context, research lineage, and operator feedback are displayed
as `INSTITUTIONAL_COGNITION`. The panel explicitly keeps prices, holdings,
cash, orders, broker state, and risk limits in `OFFICE_TRUTH`. Cognition may
inform advisory context, but it cannot overwrite financial truth or acquire
execution authority. Influence is `PROVEN` only when a producer receipt says so.

## Learning

The learning block exposes settled and pending outcomes, sample size, linked
beliefs/lessons, hypotheses, experiments, and `REVIEW_READY` candidates from
durable stores. It does not manufacture outcomes, calculate maturity in the
browser, or promote a candidate into production. Insufficient evidence remains
visible as insufficient evidence.

## Capability coverage

Coverage is built server-side from producer modules, durable artifacts, and
observed rows. Each capability reports producer, consumer, artifact, last
producer event, source SHA, state, and reason. States are:

`LIVE`, `PARTIAL`, `UNWIRED`, `DARK`, or `UNKNOWN`.

`DARK` means a producer exists but no current operator consumer is proven;
`UNWIRED` means the expected producer/artifact edge has not been observed.
These states are never inferred from a missing React property.

## Operator boundary

The surface cannot place trades, cancel orders, modify stops, alter risk or
policy, request 2FA, send a decision, or self-promote a lesson. Control Plane
pages remain the diagnostic/engineering view; this surface is the CIO
investment-office view.

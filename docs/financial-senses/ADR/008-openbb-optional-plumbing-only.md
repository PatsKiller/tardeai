# ADR-008 — OpenBB optional plumbing only

**Status:** Accepted (`DEFER`)

## Context

OpenBB could reduce provider plumbing, but it also duplicates the existing Data
Broker, has a large dependency footprint, and weaker source-identity guarantees.

## Decision

`OPENBB_DECISION = DEFER`. OpenBB is not installed and not adopted as a direct
agent dependency. It may be revisited only as an
`TradeAI FinancialSenseProvider → optional OpenBBProviderAdapter → provider`
plumbing layer that stays behind Trade AI governance.

## Consequences

- `agent → uncontrolled OpenBB toolbox` is forbidden.
- No dependency is added in this branch.

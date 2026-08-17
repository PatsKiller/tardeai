# ADR-005 — Deterministic stress, no fabricated sensitivity

**Status:** Accepted

## Context

"Technology stock, assume beta 1.5" is fabrication. A stress engine must not
invent sensitivity coefficients.

## Decision

Three tiers: (1) direct deterministic (cash / explicit sector shock), (2) mapped
exposure (verified sector mapping), (3) sensitivity model (only where the
coefficient has a governed source). Anything else is `UNAVAILABLE` and counted
in a mandatory `unmodeled_value`. Each position is modeled by exactly one tier
(no double counting).

## Consequences

- `coverage_pct <= 100%`, unmodeled value explicit.
- No unsourced beta/duration ever drives P&L.

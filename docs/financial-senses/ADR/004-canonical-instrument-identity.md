# ADR-004 — Canonical instrument identity, fail closed

**Status:** Accepted

## Context

A financial agent must know exactly what instrument it reasons about. Tickers
collide (GOOG vs GOOGL, BRK.B vs BRK-A, ADR vs ordinary, same ticker across
exchanges).

## Decision

Introduce `InstrumentIdentity@v1` with FIGI / CUSIP / ISIN / CIK / ticker /
exchange / share-class fields and statuses `RESOLVED / AMBIGUOUS / NOT_FOUND /
CONFLICT / NOT_CONFIGURED`. Resolution is fail-closed: multiple matches yield
`AMBIGUOUS` unless narrowed by exchange / security type / share class. No
guessing.

## Consequences

- Ambiguity is explicit, never silently collapsed to a guess.
- Existing canonical broker IDs are reconciled, not blindly replaced.

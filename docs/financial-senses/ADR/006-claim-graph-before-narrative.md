# ADR-006 — Claim graph before narrative

**Status:** Accepted

## Context

A recommendation should expose causal evidence, not another generated
narrative.

## Decision

Model recommendations as a `FACT → CLAIM → SPECIALIST_OPINION → DECISION` graph.
Every FACT requires source + observed_at/as_of + quality. Every derived CLAIM
requires incoming evidence (else `UNSUPPORTED`). Contradictions are preserved,
never deleted. Memory edges are `NON_AUTHORITATIVE_CONTEXT`.

## Consequences

- Unsupported claims are detected, not silently accepted.
- Stale facts can invalidate actionability.
- Canonical facts stay authoritative over memory.

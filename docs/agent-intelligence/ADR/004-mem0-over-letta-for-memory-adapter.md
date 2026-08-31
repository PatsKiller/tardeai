# ADR-004 — Mem0 (or local test double) as the memory adapter

Status:      ACTIVE
as_of:       2026-08-16T23:13:46-04:00
Measured at: efcc51365 / not measured

- **Status**: Accepted
- **Date**: 2026-08-17

## Context

Phase 4 needs a memory provider behind a stable abstraction, but the program's
rules forbid importing a framework that would become a "second system of
record", and forbid anything that could mutate broker/order/stop/2FA/risk-policy
state or egress operator data. Two candidate adapters were considered for the
provider seam: **Mem0** and **Letta**.

## Decision

Adopt a narrow `MemoryProvider` protocol (`scripts/lib/agent_memory_provider.py`)
with two concrete implementations now:

- `NullMemoryProvider` — always `NOT_CONFIGURED`, the safe default.
- `LocalTestMemoryProvider` — deterministic in-memory test double.

A `Mem0MemoryProvider` adapter (`scripts/lib/agent_mem0_provider.py`) is the
chosen seam for a future self-hosted backend, but it currently reports
`NOT_CONFIGURED` because `mem0` is **not installed** and **no backend is
configured**. Self-hosted / local-controlled hosting is preferred over hosted
SaaS to keep operator data from leaving a controlled path.

**Letta was reviewed and is NOT implemented.** Letta overlaps with the existing
stateful agent runtime (wake jobs, plans, traces, memory-lane persistence) and
would introduce a second agent-execution framework — violating controlling
principle #9 ("no new framework may become a second system of record"). Mem0 (or
the local test double) is only a memory adapter, not a competing runtime.

## Consequences

- Memory is shadow-only (`MEMORY_SHADOW=1`, `MEMORY_BEHAVIOR_INFLUENCE=0`); it
  can be recorded and inspected but cannot influence synthesis.
- The adapter reports `NOT_CONFIGURED` honestly rather than fabricating a
  "PASS" that a live backend does not justify.
- Any provider behind the protocol must fail soft (empty/`None`/`False`), so a
  missing backend never breaks a wake.

## Revisit condition

Revisit Letta only if a future phase demonstrably needs a memory-native agent
**runtime** — not just a memory store — and the existing stateful runtime proves
insufficient. Otherwise Mem0 (self-hosted) or the local double remains the
memory adapter.

# ADR-007 — Independent CIO critic, shadow only

**Status:** Accepted

## Context

An independent adversarial pass should challenge proposed material decisions
without becoming a visible persona or a new authority.

## Decision

The critic is an internal review step with `CRITIC_SHADOW=1` and
`CRITIC_BEHAVIOR_INFLUENCE=0`. It assumes the decision may be wrong and hunts
for counterevidence, missing evidence, unmodeled effects, and identity /
freshness / source problems. It never changes live decisions and never notifies.

## Consequences

- No live behavioral authority in this branch.
- A deterministic engine is the default; an LLM-backed critic stays dry/shadow.

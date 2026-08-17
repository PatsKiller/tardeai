# Memory Governance & Mem0 Shadow Pilot

Phase 4 of the Agent Intelligence Foundation. `READ_ONLY_ADVISORY`.

This document records the memory-provider abstraction, the Mem0 due diligence
and self-hosting preference, the shadow-mode posture, and the hard authority
boundary that memory is **context, never truth**.

## Status summary

| Item | Value |
|------|-------|
| Provider abstraction | `scripts/lib/agent_memory_provider.py` |
| Governance / admission | `scripts/lib/agent_memory_governance.py` |
| Mem0 adapter | `scripts/lib/agent_mem0_provider.py` |
| Mem0 backend | **NOT_CONFIGURED** — package not installed, no backend wired |
| Active provider | `LocalTestMemoryProvider` (in-memory test double) |
| `MEMORY_SHADOW` | `1` |
| `MEMORY_BEHAVIOR_INFLUENCE` | `0` |

Memory is **shadow-only** today. It records candidates and can be retrieved for
inspection, but it cannot influence advisory synthesis.

## Provider abstraction

`MemoryProvider` is a narrow, duck-typed protocol:

- `search(query, scope=None, symbols=None, top_k, budget_tokens) -> dict`
- `add_candidate(record) -> str | None`
- `get(memory_id) -> dict | None`
- `dispute(memory_id, reason) -> bool`
- `expire(memory_id) -> bool`
- `health() -> dict`

Every method fails soft: a missing or broken provider returns empty/`None`/
`False` instead of raising, so a memory outage can never break a wake.

Three implementations exist:

1. **`NullMemoryProvider`** — always `NOT_CONFIGURED`, never raises, never
   stores. The safe default when nothing is wired.
2. **`LocalTestMemoryProvider`** — deterministic in-memory store used by tests
   and as the shadow-pilot reference. Search relevance is substring hits +
   confidence, ties broken by recency then `memory_id`; it returns both
   supporting records and counter-memory (records with a non-empty
   `contradicts` list or `DISPUTED` status), bounded by `top_k` and an
   approximate token budget.
3. **`Mem0MemoryProvider`** — a fail-soft adapter over the (uninstalled) `mem0`
   package. `health()` returns `NOT_CONFIGURED` with an honest reason; `search`
   and `add_candidate` are no-ops. This is the seam to wire a reviewed
   self-hosted backend later without changing callers.

## Mem0 due diligence

Recorded in `MEM0_DUE_DILIGENCE`:

| Field | Value |
|-------|-------|
| Package / version | `mem0`, **none installed** |
| Hosting preference | **self-hosted / local-controlled** |
| OSS vs hosted | self-hosted OSS preferred over hosted SaaS (no operator data egress) |
| Storage backend | TBD |
| Vector backend | TBD |
| Embedding provider | TBD |
| License | TBD (mem0 core Apache-2.0; confirm per backend) |
| Retention | TBD (must carry explicit `expires_at` + retention policy) |
| Privacy | no data leaves a local-controlled path; no operator PII |
| Failure behavior | fail-soft: `NOT_CONFIGURED` health, empty search, `None` add |

**No production memory backend is configured.** Until a self-hosted backend is
reviewed and wired, the `LocalTestMemoryProvider` in-memory test double is the
only provider in use. Mem0 is therefore **NOT_CONFIGURED — not PASS** — and the
system is shadow-only with behavior influence off.

## Shadow mode

- `MEMORY_SHADOW = 1` — memory is recorded (in-memory) but never influences
  behavior.
- `MEMORY_BEHAVIOR_INFLUENCE = 0` — the hard gate that keeps memory from
  affecting synthesis. This remains `0` through shadow acceptance (Phase 11).
- `MEMORY_PROVIDER = "local"` — defaults to the in-process test double.

## Authority boundary: memory is context, not truth

Memory is always marked `NON_AUTHORITATIVE_CONTEXT`. It sits in a sibling
section to `office_truth` in the ContextEnvelope and can never be written back
into canonical truth.

Concretely:

- **Canonical truth always outranks memory.** `resolve_conflict(...,
  canonical_truth_override=True)` never promotes a memory to primary.
- A remembered statement is never a price, holding, cash balance, market value,
  risk limit, or broker fact.
- Disputed memory stays visible as conflict metadata, not primary context.
- Expired / retracted / superseded memory is excluded from primary context.

### The NEVER-admit list

`FORBIDDEN_AUTHORITATIVE_FIELDS` rejects memory whose subject/field names any
canonical financial fact:

- current price / price / market value
- shares / quantity / position(s) / holding(s)
- cash / cash balance
- tax balance
- risk limit
- broker auth state
- order state / order status
- stop state / stop status
- freshness / freshness status
- policy / policy config

`is_forbidden_authoritative(subject_or_field)` returns `True` for any of these
(after normalizing `_`/`-` to spaces), so admission and retrieval both refuse to
treat such memory as a fact.

## Modules

- `scripts/lib/agent_memory_provider.py` — `MemoryProvider` protocol + Null +
  LocalTest providers.
- `scripts/lib/agent_memory_governance.py` — `MemoryRecord@v1`, admission,
  conflict resolution, `retrieve_for_context`.
- `scripts/lib/agent_mem0_provider.py` — Mem0 adapter, due diligence, flags.
- `docs/agent-intelligence/MEMORY_ADMISSION_POLICY.md` — admission statuses and
  provenance rules.
- `docs/agent-intelligence/ADR/004-mem0-over-letta-for-memory-adapter.md`
- `docs/agent-intelligence/ADR/006-memory-never-financial-truth.md`

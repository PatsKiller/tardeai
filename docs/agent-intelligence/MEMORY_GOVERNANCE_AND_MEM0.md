# Memory Governance & Mem0 Shadow Pilot

Status:      ACTIVE
as_of:       2026-08-17T23:11:04-04:00
Measured at: efcc51365 / not measured

Phase 4 of the Agent Intelligence Foundation. `READ_ONLY_ADVISORY`.

This document records the memory-provider abstraction, the Mem0 due diligence
and self-hosting preference, the shadow-mode posture, and the hard authority
boundary that memory is **context, never truth**.

## Status summary

| Item | Value |
|------|-------|
| Provider abstraction | `scripts/lib/agent_memory_provider.py` |
| Governance / admission | `scripts/lib/agent_memory_governance.py` + `scripts/lib/agent_memory_admission.py` |
| Durable provider | `scripts/lib/agent_durable_memory.py` — `DurableJsonlMemoryProvider` |
| Mem0 adapter | `scripts/lib/agent_mem0_provider.py` |
| Mem0 backend | **NOT_CONFIGURED** — package not installed, no backend wired |
| Active provider (Program 3) | `DurableJsonlMemoryProvider` when `MEMORY_PROVIDER=durable` |
| Default provider | `NullMemoryProvider` (`MEMORY_PROVIDER=null`) |
| `MEMORY_SHADOW` | `1` in Program 3 live shadow |
| `MEMORY_BEHAVIOR_INFLUENCE` | **`0` (must remain 0)** |
| `GOVERNED_MEMORY_ADVISORY_INFLUENCE` | `SHADOW` in Program 3 live shadow |

Memory is **durable and advisory**. It is **not financial truth**. It is **not
execution authority**.

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

Implementations:

1. **`NullMemoryProvider`** — always `NOT_CONFIGURED`. Safe default.
2. **`LocalTestMemoryProvider`** — deterministic in-memory store for tests.
3. **`DurableJsonlMemoryProvider`** — Program 3 production-shadow store.
   Shared `data/cio/aif_memory.jsonl` + flock + snapshot. Survives process
   restart, portfolio-server restart, CURRENT flip, and host reboot because
   `data/cio` is a CURRENT symlink to the shared runtime tree.
4. **`Mem0MemoryProvider`** — fail-soft adapter. `health()` returns
   `NOT_CONFIGURED`. Not installed. Not required.

## Backend selection (Program 3)

Preferred order was: (A) existing Postgres + pgvector, (B) self-hosted Mem0,
(C) existing local Trade AI persistence that satisfies `MemoryProvider`.

| Option | Finding |
|--------|---------|
| A. Postgres 17 + pgvector | Postgres 17 is local (`127.0.0.1:5432` / lab `:5433`) but **pgvector is not installed**. Do not introduce a new DB product. |
| B. Self-hosted Mem0 | `mem0` package is **not installed**. Do not force a brand-name dependency. |
| C. Shared JSONL on `data/cio` | **Selected.** Same root as reflection / lessons / promotions. Local, durable, CURRENT-flip safe. |

### Selected backend card

| Field | Value |
|-------|-------|
| Selection | Durable JSONL (`DurableJsonlMemoryProvider`) |
| Version | MemoryRecord@v1 / schema_version `1.0` |
| License | In-tree Trade AI (no new third-party memory product) |
| Storage | Shared `data/cio/aif_memory.jsonl` + `aif_memory.json` snapshot |
| Vector support | None (lexical + confidence + recency ranking) |
| Embedding provider | None (no external embedding egress) |
| Retention | Per-type TTL (see admission policy) |
| Backup | Shared runtime tree; JSONL is append-only audit |
| Failure behavior | Fail-soft search; fail-closed admission |
| Security model | Local-controlled disk; secret scan at admit + persist; no SaaS egress |
| Migration | Last-write-wins by `memory_id`; `ACTIVE` displayed as `ADMITTED` without rewriting stored statuses |

Do **not** send operator/financial memory to hosted SaaS.

## Shadow mode

- `MEMORY_SHADOW = 1` — retrieve and record; never let memory change production.
- `MEMORY_BEHAVIOR_INFLUENCE = 0` — hard gate. Program 3 does not flip this.
- `GOVERNED_MEMORY_ADVISORY_INFLUENCE = SHADOW` — memory shadow comparator only.
- Program 2 gates stay as deployed (`RATIFIED_LESSON_ADVISORY_INFLUENCE`,
  `FINANCIAL_SENSES_ADVISORY_INFLUENCE`) and are **not** reused for memory.

## Authority boundary: memory is context, not truth

Memory is always marked `NON_AUTHORITATIVE_CONTEXT`. It sits in a sibling
section to `office_truth` in the ContextEnvelope and can never be written back
into canonical truth.

- **Canonical truth always outranks memory.**
- A remembered statement is never a price, holding, cash, market value, risk
  limit, broker/order/stop/2FA fact, or live execution permission.
- Disputed memory stays visible as conflict metadata.
- Expired / retracted / superseded memory is excluded from primary retrieval
  but remains in the audit JSONL.

### The NEVER-admit list

`FORBIDDEN_AUTHORITATIVE_FIELDS` rejects memory whose subject/content names
canonical financial fact, including:

- current price / price / market value
- shares / quantity / position(s) / holding(s)
- cash / cash balance / tax balance
- risk limit / risk policy
- broker auth / broker state
- order state / order status
- stop state / stop status
- 2FA / two-factor
- freshness / policy config
- live execution permission
- credential

## Modules

- `scripts/lib/agent_memory_provider.py` — protocol + Null + LocalTest + factory
- `scripts/lib/agent_memory_governance.py` — MemoryRecord@v1, admission, conflict
- `scripts/lib/agent_memory_admission.py` — fail-closed candidate pipeline + receipt
- `scripts/lib/agent_durable_memory.py` — durable JSONL provider
- `scripts/lib/agent_memory_shadow.py` — SHADOW comparator (no production change)
- `scripts/lib/agent_mem0_provider.py` — Mem0 adapter (NOT_CONFIGURED)
- `docs/agent-intelligence/MEMORY_ADMISSION_POLICY.md`
- `docs/agent-intelligence/ADR/004-mem0-over-letta-for-memory-adapter.md`
- `docs/agent-intelligence/ADR/006-memory-never-financial-truth.md`
- `docs/agent-intelligence/ADR/007-durable-jsonl-memory-backend.md`
- `docs/maturity/MEMORY_OPERATOR_GUIDE.md`

## Rollback

Set `MEMORY_PROVIDER=null` (and optionally `GOVERNED_MEMORY_ADVISORY_INFLUENCE=OFF`).
Keep the JSONL as forensic evidence. Do not delete audit history.

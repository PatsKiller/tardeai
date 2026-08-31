# Agent Intelligence Foundation — Architecture

Status:      ACTIVE
as_of:       2026-08-16T23:27:37-04:00
Measured at: efcc51365 / not measured

The top-level map for the **Agent Intelligence Foundation** program: how Trade
AI's agents become context-aware, self-observing, memory-assisted, and
proactively advisory — **without** gaining trading authority.

> **Authority.** `READ_ONLY_ADVISORY`. Zero broker / order / stop / 2FA /
> risk-policy mutation. No network, no live side effects. Every phase is
> additive and shadow-first; nothing here changes what a live agent *does*
> until a human promotes it.

---

## 1. Controlling principles

These six rules are the constitution of the program. Every module is judged
against them.

| # | Principle | Meaning |
|---|-----------|---------|
| 1 | **DETERMINISTIC SYSTEMS ESTABLISH TRUTH** | Canonical financial truth comes from the deterministic decision/portfolio engines, never from an LLM or a memory. |
| 2 | **REFLECTIVE AGENTS CHALLENGE** | Agents may *question* the current decision — they may not *change* it. Challenge surfaces counter-evidence and opens a case; it never mutates policy. |
| 3 | **MEMORY PROVIDES CONTEXT NOT TRUTH** | A remembered statement is not a price, holding, cash balance, risk limit, or broker fact. Memory is `NON_AUTHORITATIVE_CONTEXT`, structurally separate from `office_truth`. |
| 4 | **LEARNING PROPOSES** | Reflection may *propose* a lesson/memory candidate. Proposals are advisory; they are never auto-promoted into rules. |
| 5 | **HUMANS PROMOTE** | Only a human (Iris / the operator) can ratify a proposal into an active rule, threshold, or policy. |
| 6 | **EXECUTION AUTHORITY SEPARATE** | The advisory office and the execution/broker layer are disjoint. Advisors have no path to place orders, move stops, or mutate broker auth. |

Two corollaries follow from #3–#6 and are enforced everywhere:

- **No new framework may become a second system of record.** LangGraph, Letta,
  Mem0, or any MCP backend are *measured* or *shadowed*, never made
  authoritative.
- **No agent may silently change production policy because it "learned"
  something.** Learning ends in a candidate awaiting human promotion.

---

## 2. The `NOTICE → … → LEARN` loop

One advisory wake is a pass around a fixed loop. Each arrow is a first-class,
auditable step; each step maps to a concrete module (phase in parentheses).

```
NOTICE ──► OBSERVE ──► ORIENT ──► PLAN ──► DELEGATE ──► CHALLENGE
   ▲                                                        │
   │                                                        ▼
 LEARN ◄── FOLLOW-UP ◄── COMMUNICATE ◄── SYNTHESIZE ◄───────┘
   │
   └── ABSTAIN (fail-closed: no confident recommendation, no write)
```

| Loop step | What happens | Module / phase |
|-----------|--------------|----------------|
| **NOTICE** | A canonical wake trigger fires (`POSITION_OPENED`, `CASH_BAND_CHANGED`, `FOLLOW_UP_DUE`, …). | `agent_wake_taxonomy.py` (P6) |
| **OBSERVE** | Load verified truth + decision/evidence through the single context chokepoint. | `agent_context_envelope.py` (P1) |
| **ORIENT** | Scope and budget the context; record honest retrieval status *before* reasoning. | `agent_context_integration.py` (P5) |
| **PLAN** | Bind the work to `wake_id` / `trace_id` / `decision_id` and open a trace. | `agent_run_trace.py` (P1) |
| **DELEGATE** | Hand each specialist only its scoped sub-envelope (guardian sees risk truth, steph sees research, …). | `agent_context_integration.py` (P5) |
| **CHALLENGE** | A reflective agent surfaces counter-evidence / counter-memory against the current recommendation. | `agent_notification_intelligence.py` (P2) |
| **SYNTHESIZE** | Alex composes the advisory view; memory stays labeled context, truth stays canonical. | `agent_context_envelope.py` (P1) |
| **COMMUNICATE** | Notification reasoning: suppress unchanged replays, re-open only on new evidence. | `agent_notification_intelligence.py` (P2) |
| **FOLLOW-UP** | Bind every non-action to a durable next review (`TIME`/`CONDITION`/`DATA_FRESHNESS`/`EVENT`). | `agent_followup.py` (P6) |
| **LEARN** | Wake → decision → case → feedback → outcome → reflection → **candidate** lesson/memory. | `agent_learning_linkage.py` (P7) |
| **ABSTAIN** | Fail-closed: unrecognized trigger/action or a missing provider degrades to an explicit `NOT_CONFIGURED`, never a guess. | all phases |

The loop is **shadow-first**: every phase is built and tested in isolation
(P1…P8), then shadow-compared against baseline behavior (P11), and only after
shadow acceptance does any output influence a live agent (P12).

---

## 3. System map

```
                        ┌──────────────────────────────────────────────┐
                        │        READ_ONLY_ADVISORY boundary           │
                        │                                              │
   deterministic        │   get_context_for_agent()  ◄── single        │
   truth / decision ────┼──►  ContextEnvelope@v1       chokepoint       │
   engines              │        │                                     │
                        │        ├─ office_truth   (canonical truth)   │
   memory provider ─────┼────────┼─ episodic_memory (NON_AUTHORITATIVE)│
   (Null/Local/Mem0)    │        ├─ research_memory                    │
                        │        ├─ external_read_context (read-only   │
   read-only MCP ───────┼────────┤    MCP gateway only)                │
   gateway              │        └─ governance + provenance            │
                        │                                              │
                        │   Phase 5: scope ─► budget ─► honest status   │
                        │   (SPECIALIST_SCOPES, CONTEXT_BUDGET_ORDER,   │
                        │    record_retrieval_before_reasoning)         │
                        │                                              │
                        │   AgentRunTrace@v1 + agent_tool_trace         │
                        │   (append-only, redacted JSONL)               │
                        │                                              │
                        │   notification + follow-up intelligence       │
                        │                                              │
                        │   learning linkage (propose, never promote)   │
                        └──────────────────────────────────────────────┘
                                   │  shadow_compare (P11/P12 gate)
                                   ▼
                          humans promote — or the change is discarded
```

---

## 4. The pieces, and how they fit

### 4.1 ContextEnvelope@v1 — `scripts/lib/agent_context_envelope.py` (P1)

The canonical context object shared by Alex and specialists. Key guarantees:

- **Single chokepoint** `get_context_for_agent(*, agent, wake, decision, symbols,
  plan_id, …)` is the one entrypoint all reasoning migrates toward.
- **Stable digest** `context_envelope_digest()` excludes timestamps, so
  materially-identical envelopes hash identically and any material change
  yields a new digest.
- **Truth/memory separation** — `office_truth` is canonical; memory lives only
  in `episodic_memory` and can never be written back.
- **Explicit absence** — missing providers are `NOT_CONFIGURED` / `UNAVAILABLE` /
  `ERROR`, never a silent empty list.
- **Governance** — `authority == READ_ONLY_ADVISORY`,
  `memory_authority == NON_AUTHORITATIVE_CONTEXT`; validation fails closed.

### 4.2 AgentRunTrace@v1 + `agent_tool_trace` — `scripts/lib/agent_run_trace.py`, `scripts/lib/agent_tool_trace.py` (P1/P2)

- `build_trace` / `append_trace` / `close_trace` / `query_traces` give every wake
  a redacted, append-only JSONL record, queryable by `wake_id` / `decision_id` /
  `case_id`.
- Chain-of-thought is stripped and secrets redacted before persist.
- `agent_tool_trace.build_tool_call` stores redacted request/response **digests**
  and a read/write capability class, never raw payloads.

### 4.3 Notification & follow-up intelligence — `scripts/lib/agent_notification_intelligence.py` (P2)

`evaluate_notification()` separates *identity* from *decision* + *evidence*:

- unchanged replay → suppressed;
- prior operator `REJECT` of the same unchanged recommendation → suppressed;
- same decision with **new evidence** → may reopen only with
  `WHAT CHANGED SINCE YOUR REJECT`.

`build_next_review()` degrades a missing schedule to an explicit
`NEXT_REVIEW_UNAVAILABLE` + reason — no bare "NEXT REVIEW".

### 4.4 Read-only MCP gateway — `scripts/lib/mcp_read_only_gateway.py` (P3)

A single internal chokepoint for every agent MCP call (`call_mcp_tool`):

- exact-tool allowlist + substring denylist, fail-closed;
- SSRF guard (private/metadata hosts always blocked) and path-traversal guard;
- response size bound + secret redaction; full receipt binding.

The denylist (`broker`, `order`, `stop`, `trade`, `create`, `update`, `delete`,
`write`, `risk_policy`, `auth`, `2fa`, …) is structural: read-only is enforced
by capability design, not by an annotation.

### 4.5 Memory abstraction + Mem0 shadow — `scripts/lib/agent_memory_provider.py`, `scripts/lib/agent_memory_governance.py`, `scripts/lib/agent_mem0_provider.py` (P4)

- A narrow duck-typed protocol (`search`/`health` + `add_candidate`/`get`/
  `dispute`/`expire`) with three implementations: `NullMemoryProvider`,
  `LocalTestMemoryProvider`, `Mem0MemoryProvider`.
- `agent_memory_governance` owns `MemoryRecord@v1` admission, conflict
  resolution, and a **NEVER-admit list** (`FORBIDDEN_AUTHORITATIVE_FIELDS`) that
  refuses to treat memory about price/holdings/cash/risk/broker/order as fact.
- Mem0 is **NOT_CONFIGURED** and shadow-only: `MEMORY_SHADOW=1`,
  `MEMORY_BEHAVIOR_INFLUENCE=0`. The adapter never constructs a client or opens a
  network path.

### 4.6 Wake taxonomy + autonomous office — `scripts/lib/agent_wake_taxonomy.py`, `scripts/lib/agent_followup.py` (P6)

- `canonicalize_wake_trigger()` maps every wake to one canonical trigger
  (or `None`); `is_followup_wake` / `is_material_wake` separate scheduling from
  state-change wakes.
- `allowed_autonomous_action()` classifies fail-closed: allowed actions are
  `LOAD_VERIFIED_TRUTH`, `SEARCH_INTERNAL_RESEARCH`, `RETRIEVE_MEMORY`,
  `USE_READ_ONLY_MCP`, `DELEGATE_SPECIALIST_QUESTION`,
  `CREATE_UPDATE_ADVISORY_CASE`, `SCHEDULE_REVISIT`, `PREPARE_NOTIFICATION`.
  `TRADE`, `MODIFY_RISK_POLICY`, `MUTATE_BROKER_AUTH`, `PROMOTE_LEARNED_RULES`,
  and friends are **always denied**.

### 4.7 Learning linkage — `scripts/lib/agent_learning_linkage.py` (P7)

- `build_lineage()` ties `wake_id → trace_id → decision_id → case_id →
  operator_feedback → follow_up → measured_outcome → darwin_score → reflection →
  lesson_candidate`.
- The feedback-vs-outcome invariant: `REJECT` / `ACK` / `DONE` / `RATE` / `DEFER` /
  `NOTE` are **FEEDBACK**, never investment outcomes; only a matured, measured
  `MEASURED_INVESTMENT_OUTCOME` counts as a result.
- `propose_memory_write()` is the *only* sanctioned path from reflection to
  memory, and it returns a **CANDIDATE** — a separate `admit_memory_candidate()`
  gate decides `ADMITTED` / `REJECTED`. The module never writes to any store.

### 4.8 LangGraph complexity gate — `scripts/lib/langgraph_complexity_gate.py` (P8)

`compute_complexity_metrics()` + `gate_decision()` measure durable-workflow
complexity from `AgentRunTrace`-shaped data. The default verdict is
**`NOT_REQUIRED`** — a *success* meaning we must not introduce a second
framework / second system of record. `PILOTED` is returned only on real
durable-workflow evidence, and even then grants no broker authority.
`letta_decision()` is **`DEFERRED`**.

---

## 5. Phase 5 — context-aware integration (this phase)

The adapters that make scoped, budgeted, honest context possible — without
wiring it into any live agent. `scripts/lib/agent_context_integration.py`.

### 5.1 Specialist scoping (`SPECIALIST_SCOPES`, `build_specialist_sub_envelope`)

No specialist receives every domain. Governance + provenance are *structural*
(authority + trace linkage) and always copied; content domains are scoped:

| Specialist | Content domains | Rationale |
|------------|-----------------|-----------|
| `guardian` | decision, office_truth, active_intent | risk scope: truth + constraints, no research/external/memory |
| `steph`    | decision, office_truth, active_intent, research_memory, external_read_context | research scope |
| `maria`    | decision, active_intent, episodic_memory, specialist_context | front-door scope: operator memory + other views |
| `ledger`   | decision, office_truth | canonical truth only |
| *(unknown)*| *(none)* | fail-closed: no content |

`build_specialist_sub_envelope(parent, specialist, question)` returns a
sub-envelope that binds `parent_wake_id` / `parent_trace_id`, carries the
`specialist_question`, and a `subcontext_digest` computed over a deterministic
projection (the question is folded into `trigger`, so distinct questions hash
differently).

### 5.2 Honest retrieval (`record_retrieval_before_reasoning`)

Retrieval status is recorded **before** synthesis, never assumed:

- no provider / down / error → `MEMORY_NOT_CONSULTED`;
- research not `OK` → `RESEARCH_UNAVAILABLE`;
- external read not `OK` → `MCP_NOT_AVAILABLE`.

A `retrieval_audit` block lists markers and `full_context_available`; the agent
is never allowed to pretend it had full context.

### 5.3 Deterministic budgeting (`CONTEXT_BUDGET_ORDER`, `apply_context_budget`)

`CONTEXT_BUDGET_ORDER` is the fixed priority, highest first:

```
canonical truth  >  decision/evidence  >  active thesis/constraints
>  operator explicit memory  >  relevant cases/research  >  external read
>  lower-confidence memory (last)
```

`apply_context_budget(envelope, budget_tokens)` truncates lowest-priority-first
and returns `(budgeted_envelope, truncation_metadata)`. **Canonical truth is
never dropped.** Lower-confidence memory is dropped *inside* `episodic_memory`
before the whole section, and every truncation is recorded in the metadata so a
trace shows exactly what was removed.

### 5.4 Shadow comparison (`shadow_compare`)

`shadow_compare(baseline, augmented)` reports `same` (action unchanged) plus
explicit `why` strings and per-source diffs (`memory_ids_used`,
`mcp_context_used`, `specialists_changed`, `notification_changed`,
`follow_up_changed`). It states *what* memory/MCP/specialist input changed, so a
shadow run can see *why* an action moved — not merely that it did.

---

## 6. Phase map

| Phase | Title | Key module(s) | Status |
|-------|-------|---------------|--------|
| 0 | Release truth, PR1 merge, exact-main deploy & topology | `cio_topology_audit.py` | merge done; promote/topology per operator |
| 1 | Schemas (ContextEnvelope, AgentRunTrace) | `agent_context_envelope.py`, `agent_run_trace.py` | implemented + tested |
| 2 | Observability instrumentation | `agent_tool_trace.py`, `agent_notification_intelligence.py` | primitives implemented + tested |
| 3 | Read-only MCP gateway | `mcp_read_only_gateway.py` | implemented + tested |
| 4 | Memory abstraction + Mem0 shadow | `agent_memory_provider.py`, `agent_memory_governance.py`, `agent_mem0_provider.py` | implemented, shadow-only |
| **5** | **Context-aware agent integration** | **`agent_context_integration.py`** | **implemented (shadow-compare only)** |
| 6 | Autonomous office initiative | `agent_wake_taxonomy.py`, `agent_followup.py` | implemented |
| 7 | Learning loop integration | `agent_learning_linkage.py` | implemented |
| 8 | LangGraph complexity gate | `langgraph_complexity_gate.py` | implemented |
| 9 | Security / threat model / red team | — | not started |
| 10 | Comprehensive test program | — | not started |
| 11 | Shadow acceptance before behavior influence | `shadow_compare` (P5) | not started |
| 12 | Controlled read-only activation | — | not started |

---

## 7. Non-goals (hard boundary)

- **No trading authority.** No phase may place an order, move a stop, or mutate
  broker/2FA state.
- **No policy self-modification.** Learning proposes; humans promote.
- **No second system of record.** The hash-chained event store, `office_truth`,
  and the decision engines remain authoritative.
- **No hidden fallback.** A missing provider is `NOT_CONFIGURED`, never silently
  replaced by stale memory.
- **No network / no secrets.** Every module is pure and deterministic; MCP and
  Mem0 backends are represented as `NOT_CONFIGURED` until a human wires a
  reviewed, self-hosted backend.

> The office *advises*. It never decides for the operator.

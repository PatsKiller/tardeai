# Orchestration & LangGraph Decision

Status: `READ_ONLY_ADVISORY` — this document records how Trade AI already
orchestrates agent work, how the LangGraph complexity gate is measured, and why
the default answer is **NOT_REQUIRED**.

---

## 1. What the existing orchestration already does

Trade AI is not a stateless chat loop. It already owns a durable, observable,
append-only orchestration surface that predates any workflow framework:

- **Wake lifecycle** (`scripts/lib/cio_wake_dispatcher.py`,
  `scripts/lib/cio_wake_jobs.py`): a sole durable wake claimant with an explicit
  `PENDING → CLAIMED (lease) → DISPATCHED → IN_FLIGHT → COMPLETED` state machine.
  Wakes carry two intents — `NEW_RUN` and `RESUME_RUN` — so *resume* and
  *continuation* are first-class, not an afterthought.
- **Hash-chained event store** (`CIOWakeJobStore`): the event log is
  authoritative; projections are derived and rebuildable by replay. Records are
  never mutated in place.
- **Traceability** (`scripts/lib/agent_run_trace.py`): every wake is bound to a
  `wake_id` + `trace_id` (plus `parent_trace_id`), persisted as redacted,
  append-only JSONL and queryable by `wake_id` / `decision_id` / `case_id`.
- **Canonical context** (`scripts/lib/agent_context_envelope.py`): a single
  `ContextEnvelope@v1` with a deterministic content digest and a
  `get_context_for_agent()` chokepoint; truth and memory are structurally
  separated, and missing providers degrade to explicit
  `NOT_CONFIGURED` / `UNAVAILABLE`.
- **Memory abstraction** (Phase 4): a narrow duck-typed provider protocol
  (`health()` + `search()`) with `NullMemoryProvider` / `Mem0MemoryProvider`
  implementations, `NON_AUTHORITATIVE_CONTEXT` authority.
- **Learning loop** (`scripts/lib/agent_learning_linkage.py`,
  `scripts/darwin_outcome_scorer.py`, `scripts/lib/advisory/kb_lessons.py`):
  lineage from wake → decision → case → feedback → outcome → reflection →
  lesson candidate; nightly reflection *proposes*, Iris *ratifies*. Lessons are
  advisory context, never rules.
- **Governance** (Phase 8 maturity): lifecycle state, authority state, sample
  gates, and human-only promotion.

In short: **durable state, resume, idempotency, lineage, memory, and governance
are already in-house.** The question Phase 8 answers is whether a framework such
as LangGraph adds anything beyond what this orchestration already provides.

---

## 2. The measured complexity gate

`scripts/lib/langgraph_complexity_gate.py` measures — it does **not** import or
install LangGraph. From `AgentRunTrace`-shaped data it computes:

| Metric | Meaning |
|--------|---------|
| `avg_steps_per_wake` | average steps summed per wake |
| `branch_count` | distinct branching points |
| `parallel_fan_out` | parallel fan-out |
| `retry_count` | retries |
| `durable_wait_count` | resumable wait states |
| `resume_count` | actual resumes |
| `operator_interrupts` | operator interrupts requiring state resume |
| `cross_process_continuation` | cross-process continuations |
| `partial_failure_recovery` | partial-failure recoveries |
| `manual_recovery_incidents` | manual recoveries |
| `state_loss_incidents` | state-loss / replay incidents |

`gate_decision(metrics)` maps these counts to one of two verdicts:

- **`NOT_REQUIRED`** — the default.
- **`PILOTED`** — only when a genuine durable-workflow problem is evidenced:
  1. multiple resumable wait states **and** complex branching + retries, or
  2. frequent partial-failure recovery (or manual recovery), or
  3. operator interrupts requiring exact state resume, or
  4. state-loss / replay complexity.

The gate's output is recorded back into the metrics
(`metrics["gate_decision"]`) so a decision is auditable at the point it was
measured.

---

## 3. The `NOT_REQUIRED` default — and why it is a SUCCESS

`NOT_REQUIRED` is **not** a failure. It is the expected, correct answer for a
system whose orchestration already covers durable workflow needs.

The controlling principles are explicit on this point:

- *"No new framework may become a second system of record."*
- *"No agent may silently change production policy because it 'learned' something."*

Introducing LangGraph as the orchestration substrate would (a) create a second
source of truth for what the event store already owns, (b) split the
`wake_id`/`trace_id`/`decision_id` lineage across two runtimes, and (c) add a
new failure surface to a `READ_ONLY_ADVISORY` system that is deliberately
fail-closed. The gate therefore defaults to `NOT_REQUIRED` and requires *real
evidence* before it ever flips.

---

## 4. LangGraph constraints if ever piloted

Even a `PILOTED` verdict grants **no** broker/order/stop/2FA authority. If a
pilot is ever justified, it is bounded by hard constraints:

1. **Never a system of record.** The hash-chained event store remains
   authoritative. LangGraph may only orchestrate *within* one bounded worker.
2. **Never a decision store.** Decision identity stays on `decision_id` +
   `decision_input_digest` / `decision_evidence_digest`.
3. **Never a memory store.** Memory stays behind the `NON_AUTHORITATIVE_CONTEXT`
   provider abstraction.
4. **Never a truth store.** `office_truth` is unchanged and remains canonical.
5. **Never a global runtime.** It cannot become the shared execution substrate
   for the fleet; it is scoped to the single worker that triggered the gate.
6. **External identity only.** All state is referenced via
   `decision_id` / `case_id` / `trace_id` / `context_digest` — never by
   LangGraph-internal node ids that would fork the lineage.
7. **Fail-closed.** A LangGraph pilot that cannot emit the same lineage/context
   digest as the incumbent orchestration is ineligible to influence synthesis.

---

## 5. Letta decision: `DEFERRED`

`letta_decision()` returns **`DEFERRED`**.

Trade AI already owns agent identity, plans, cases, decisions, the memory
abstraction, workflow, and governance. Letta (or any external memory/agent
platform) is not required today. It is reconsidered only if the existing memory
abstraction proves *structurally inadequate* — which the Phase 4 abstraction is
explicitly designed to avoid.

See [ADR-005](./ADR/005-langgraph-conditional-not-platform-rewrite.md) for the
recorded decision.

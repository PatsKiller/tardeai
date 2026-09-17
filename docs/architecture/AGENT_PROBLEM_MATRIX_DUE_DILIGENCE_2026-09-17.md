# Agent problem matrix — architectural due diligence

```
Schema:      AgentProblemMatrixDueDiligence/v1
Date:        2026-09-17
Authority:   READ_ONLY_ADVISORY — no broker, order, stop, or config mutation
Source:      operator-supplied chart, "10 AI Agent Problems and How to Fix Them"
             (Sivasankar Natarajan). 10 failure modes x 20 named tools.
Method:      measured against this tree at ede0698. Every verdict cites file:line.
```

> **REMEDIATED 2026-09-17.** Five rows were closed the same day; see
> `AGENT_PROBLEM_MATRIX_REMEDIATION_PLAN_2026-09-17.md` for the record and evidence.
> Three verdicts below are **corrected there** and should not be read as current:
> row 02 was over-called DARK (tool authority was already enforced by
> `agent_runtime.contracts.ToolPolicy`; the receipt trail was the real gap), the
> "conservative = 0" reading of the feature flags was wrong for
> `MEMORY_ADVERSARIAL_SCAN`, and `MCP_READ_ONLY_GATEWAY` stays 0 because it opens a
> capability path rather than guarding one. The rest of this document stands as
> measured.

## Question asked

For each of the ten failure modes: are we using one of the named tools, which one, and
if not, why not and what should we use instead?

## Headline

**We use none of the twenty named tools. Not one is in `requirements.txt` or
`package.json`.** The runtime dependency set is `anthropic`, `openai`, `pydantic` (plain),
`psycopg2`, `pandas`, `yfinance`, `finnhub-python`, `twilio` — no orchestration framework,
no memory SaaS, no guardrail library, no tracing vendor.

That is mostly the right answer, and in four cases it is a *recorded, tested* answer rather
than an accident. But "we built our own" is only a defence where the homegrown thing is
**wired**. The real finding is not the absent vendors. It is that this repository has built
a complete agent-safety stack and **left a large part of it switched off**.

Three verdict classes are used below:

| verdict | meaning |
|---|---|
| **LIVE** | homegrown equivalent exists AND a production path calls it |
| **DARK** | homegrown equivalent exists, is tested, and **nothing in production calls it** |
| **GAP** | no adequate equivalent, wired or otherwise |

Score: **4 LIVE · 4 DARK · 2 GAP.**

The DARK rows are the expensive ones. Per `AGENTS.md` §13.5, an unwired component is not an
absent one, and this system's most costly recurring habit is rebuilding what already exists.
Every DARK row below is a *wiring* task, not a build task, and none of them needs a vendor.

---

## Row-by-row

### 01 · Hallucinating answers — chart says LlamaIndex / Guardrails AI

**Verdict: LIVE. Homegrown. Do not adopt either tool.**

We run `scripts/lib/agent_number_grounding.py`, which is stricter than what Guardrails AI
would give us for this domain. Two halves: a prompt rule (`cio_agent_contract.GROUNDING_RULE`,
rule G0) and a deterministic post-parse check that looks up **every non-trivial number** in the
model's answer against the text the model was actually sent. Unsupported numbers past threshold
demote the answer to `RESEARCH_MORE` and cap confidence below the 40% gate.

Wired: `scripts/process_watchlist_agent_jobs.py:45` imports it; `:2971` calls it inside the real
agent job runner. Also `scripts/lib/cio_operator_desk_loop.py`, `scripts/lib/cio_agent_contract.py`.

Thresholds were tuned against a dry run over 300 stored results (2/0.25 flagged 119; 3/0.34
flagged 46; 3/0.5 flagged 10) — measured, not guessed.

Retrieval is also homegrown: `scripts/rag_indexer.py` + `scripts/rag_retrieval.py` over pgvector
with local `nomic-embed-text` via Ollama.

**Why not LlamaIndex:** it is a retrieval framework for documents. Our corpus is a governed
Postgres schema with an identity spine, per-class freshness TTLs and authority labels
(`config/data_source_authority.json`). LlamaIndex's abstractions would sit *above* that and
would have to be taught all of it. Net loss.

**Why not Guardrails AI:** it validates *shape and policy* (types, PII, toxicity). Our hallucination
problem is **numeric provenance in financial advice** — is `$412.50` a number we handed the model.
Guardrails has no validator for that. We would still write `agent_number_grounding.py`, plus a
dependency.

**Recommendation:** keep. No action.

---

### 02 · Choosing the wrong tool — chart says PydanticAI / MCP / LangGraph

**Verdict: DARK. The control exists and production does not call it.**

The equivalent is real and well designed: `scripts/agent_runtime/agents/definitions.py` gives every
agent an explicit `allowed_tools` / `denied_tools` allowlist (`:57-58`), a `BudgetPolicy`, and a
`DeploymentState`. Sentinel may call `kb.search`, `artifact.write`, `quarantine.stage`; it is
explicitly denied `kb.ratify`, `score.write`, `ticket.write`. That is exactly the "clear tool
selection logic" the chart asks for, and it is enforced by denial rather than by prompt.

Beneath it, `scripts/lib/mcp_read_only_gateway.py` is a single chokepoint for every agent tool
call: exact-tool allowlist plus substring denylist, fail-closed; server-side read-only so no write
tool passes regardless of metadata; SSRF guard; path-traversal guard; response size bound; secret
redaction; full receipt binding.

**The problem:** outside `scripts/lib/`, the only file that imports `mcp_read_only_gateway` is
`scripts/check_test_coverage.py` — a test registry. **No production path routes a tool call through
the gateway.** `MCP_READ_ONLY_GATEWAY` defaults to `0` (`agent_feature_flags.py:37`) and is set
nowhere in `.env.example` or any crontab.

Note the gateway is an *internal* gateway, not the upstream `mcp` SDK, and its external providers
(Calendar, Documents) are deliberately `NOT_CONFIGURED` rather than faked.

**Why not PydanticAI:** it would give typed tool signatures. We already have the typed layer
(`pydantic` 2.12.5 is a direct dependency) and, more importantly, PydanticAI validates *arguments*
— it has no concept of "this agent may never call this tool," which is the control that matters
when the denied tool is adjacent to a broker.

**Why not LangGraph:** answered formally — see row 05.

**Recommendation — highest-value item in this audit:** wire the gateway. Route
`process_watchlist_agent_jobs.py` and the `agent_runtime` dispatcher through
`mcp_read_only_gateway`, enable `MCP_READ_ONLY_GATEWAY=1` in shadow first, and confirm receipts
land in `data/cio/agent_tool_traces.jsonl`. Per §13.5 this is wiring, not building. No new
dependency.

---

### 03 · Using outdated information — chart says Tavily / Search APIs / MCP

**Verdict: LIVE for freshness. GAP for search redundancy — and Tavily is the specific gap.**

Freshness is handled better than the chart suggests, because we separated two things the chart
conflates. `scripts/lib/evidence_freshness_policy.py` distinguishes **retention age** (how long we
keep a row) from **decision freshness** (whether the row may still answer a question), with
per-class TTLs: intraday technicals 6h, breaking news 12h, analyst actions 14d, SEC filings 400d,
methodology canon 10y. One universal TTL would be wrong in both directions.

Live search runs through `scripts/lib/brave_router.py` with `scripts/lib/search_budget.py`
enforcing per-provider daily/monthly caps that **deny on error rather than fail open** — written
that way after a measured 2026-08-30 incident where four callers held their own Brave client, and
the alert path reported `monthly_pct: 17.6` while the provider was at 100% of its spend ceiling.

**The gap, self-documented:** `config/data_source_authority.json:243-264` declares Tavily with a
20/day budget and status `configured_unused`. Its own note is accurate and I confirmed it:

> "NO client exists in this tree and `scripts/lib/brave_router.SPILL_ADAPTERS` has no tavily entry.
> Spill receipts record it as `NO_ADAPTER`."

`SPILL_ADAPTERS` (`brave_router.py:296`) contains exactly one entry: `searxng`. So when Brave is
exhausted or down, spill has one destination, and a source we declared is recorded as unavailable.

**Recommendation:** this is the one row where the chart's named tool is the right answer.
Either wire a Tavily client (one shared module, per the config's own instruction) and add the
`SPILL_ADAPTERS` entry, **or** retire the registry row so the declaration stops asserting a
capability we do not have. Adding a data source is operator-only under §17/§7A — propose the
registry row, do not grant it. Leaving it half-declared is the worst of the three.

---

### 04 · Vulnerable to prompt injection — chart says Guardrails AI / Policy Validators

**Verdict: DARK, and honestly self-assessed as PARTIAL. Highest *risk* row.**

`scripts/lib/agent_untrusted_data.py` types all external content as `UNTRUSTED_DATA`, wraps it in
an `__untrusted_data__` envelope carrying content_type/source/ref, and runs a context partitioner
that refuses to let any untrusted marker survive inside a system or operator instruction section —
it is moved or stripped, never merged. Instruction sections are enumerated: `system`,
`system_prompt`, `operator_instructions`, `office_truth`, `active_intent`, `governance`, `decision`.

The module's own docstring is admirably blunt: this is **structural typing and delimiting, not a
model-level injection defence**; untrusted text still reaches model context, so acceptance gate
AIF-24 is **PARTIAL, not PASS**.

**The problem is the same as row 02:** outside `scripts/lib/`, only `check_test_coverage.py`
imports it. The agent job runner that ingests news, YouTube transcripts, social posts and external
research does **not** wrap that content. `MEMORY_ADVERSARIAL_SCAN` — the jailbreak /
instruction-override reject at memory admission — defaults to `0`.

This is the row where DARK carries real exposure. We ingest adversary-controllable text
(`news_articles` 13,578 rows; `social_post`; `youtube`) into an agent whose output shapes advice
on a real portfolio.

**Why not Guardrails AI:** its injection validators are heuristic classifiers over input text.
They would not replace the structural partition — which is the stronger control — and would add a
model call per ingest on a corpus this size. Wrong cost shape.

**Recommendation:**
1. Wire `agent_untrusted_data.untrusted_envelope()` at every external-content ingest point. Wiring, not building.
2. Turn on `MEMORY_ADVERSARIAL_SCAN=1` — `scripts/lib/agent_memory_governance.py` already implements the scan and `tests/test_memory_adversarial_scan_qualifiers.py` already tests it.
3. Then, and only then, evaluate whether a classifier adds anything. Do not buy first.

---

### 05 · Agents conflicting — chart says CrewAI / LangGraph

**Verdict: LIVE. Homegrown. LangGraph already formally evaluated and declined — keep declining.**

This is the row where we are furthest ahead of the chart, and we have the paperwork.

`scripts/lib/langgraph_complexity_gate.py` is a deterministic gate that **measures** whether
LangGraph is justified, from `AgentRunTrace`-shaped workflow metrics: durable waits, resumes,
branches, retries, partial-failure recoveries, operator interrupts, state-loss incidents. Default
verdict `NOT_REQUIRED`, and the module is explicit that NOT_REQUIRED **is a success** — it means
existing orchestration covers the need and a second framework would mean a second system of record.
Letta is `DEFERRED` by the same module. Both decisions are tested
(`tests/test_langgraph_complexity_gate.py`).

Conflict prevention in production is deterministic and at the right layer:

| control | file | prevents |
|---|---|---|
| `flock` non-overlap, exit 99 | `scripts/lib/agent_jobs_lock.py` | two runners on the same queue |
| holdings write lock | `scripts/lib/holdings_write_lock.py` | concurrent authoritative-store writes |
| file lease | `scripts/lib/agent_file_lease.py` | two agents on one artifact |
| LLM lane reservation | `scripts/lib/llm_lane_reservation.py` | two agents on one provider lane |
| lane registry (116 lanes) | `config/lane_registry.json` | a lane producing nothing going unnoticed |
| reviewer/scorer separation | `agent_runtime/agents/definitions.py` | an agent grading itself |

Role separation is structural rather than conversational: Sentinel has `reviewer_agent_id="iris"`
and `scorer_agent_id="darwin"`, and Darwin is denied `artifact.write`. The critic cannot edit what
it critiques.

`scripts/lib/model_policy.py` goes further — the critic **must use a different provider from the
author**. No multi-agent framework offers that; it is a domain judgment.

**Why not CrewAI:** CrewAI coordinates agents inside one process via conversational role-play.
Our agents are independent cron-scheduled processes coordinating through Postgres and file locks.
CrewAI has no answer for two OS processes racing a write — `flock` does. Adopting it would mean
rewriting the scheduler to fit the framework.

**Recommendation:** keep, and keep the gate. If someone proposes LangGraph again, the answer is to
run `langgraph_complexity_gate` against current traces and let the measurement decide. That is
better governance than either adopting or refusing on taste.

*Caveat:* the gate reads `AgentRunTrace` workflow metrics, and per row 09 those traces are barely
being emitted. **A `NOT_REQUIRED` verdict computed over near-empty traces is weakly evidenced.**
Fixing row 09 is a precondition for trusting this row's verdict on an ongoing basis. It does not
change today's answer — nothing suggests we need LangGraph — but the evidence is thinner than the
gate's confident output implies.

---

### 06 · Forgetting context — chart says Mem0 / Zep

**Verdict: DARK by deliberate choice, with the best-documented rejection in the tree.**

`scripts/lib/agent_mem0_provider.py` is a fail-soft adapter that reports `NOT_CONFIGURED` honestly
and carries a structured `MEM0_DUE_DILIGENCE` record: package not installed, self-hosted preferred
over hosted SaaS, **"no operator data egress"**, fail-soft behaviour specified. The docstring states
the package "is NOT installed and MUST NOT be installed in this tree."

The reason is a rail, not a preference. Under `AGENTS.md` §17, **what portfolio data may be sent to
an external model provider is an operator-only decision**. Mem0's and Zep's hosted offerings mean
shipping position-level context to a third party. An agent cannot make that call — which is why the
adapter exists as a *seam* rather than an integration.

Homegrown memory is substantial: ~30 modules including `agent_context_envelope.py`,
`agent_durable_memory.py`, `memory_consolidator.py`, `memory_decay.py`, `memory_taxonomy.py`,
`memory_namespace.py`, `semantic_operator_memory.py`.

The architecture is better than Mem0's on the axis that matters here — `ContextEnvelope@v1`
separates **memory from truth**, labelling memory `NON_AUTHORITATIVE_CONTEXT`, surfacing conflicts
instead of folding them into truth, representing missing providers explicitly
(`NOT_CONFIGURED`/`UNAVAILABLE`), and forbidding hidden fallback to stale memory. Mem0 returns
memories as facts. For financial advice, "the agent remembered" and "the portfolio says" must not
be the same tier of assertion.

Promotion is gated by `scripts/lib/agent_shadow_acceptance.py`, which is fail-closed: behaviour
influence stays off unless every hard gate is proven by *measured decision-level* evidence,
requiring ≥0.95 operator-rejection recall, and treating "not measured" as failure rather than pass.

**Current state:** `MEMORY_PROVIDER="null"`, `MEMORY_SHADOW=0`, `MEMORY_BEHAVIOR_INFLUENCE=0`
(`agent_feature_flags.py:35-44`). The only provider in use is the in-memory test double. A
`cio-memory-shadow-measure` lane is declared in `config/lane_registry.json`.

**Recommendation:** do not adopt Mem0 or Zep hosted — the egress rail forbids it and the operator
decides, not us. Self-hosted Mem0 OSS remains open but is not obviously better than what we have.
The actionable step is to run the shadow: `MEMORY_PROVIDER="local"`, `MEMORY_SHADOW=1`,
`MEMORY_BEHAVIOR_INFLUENCE=0`, let `agent_shadow_acceptance` accumulate measured evidence, and let
the 0.95 gate decide. Until that runs, "our memory is better" is a `[DOC-CLAIM]` about our own
architecture, not a measurement.

---

### 07 · Stuck in repetitive loops — chart says LangGraph / StateGraph

**Verdict: LIVE. Homegrown, and layered more carefully than the chart implies.**

Four independent brakes, each written after a specific failure:

1. **Per-invocation budget** — `BudgetPolicy(max_model_calls, max_tool_calls, max_cost_usd, deadline_seconds)` on every agent definition (`agent_runtime/agents/definitions.py:62,95,126,159,195`).
2. **Cumulative per-goal budget** — `scripts/lib/goal_budget.py`, written precisely because per-invocation budgets reset every lap: "a goal that laps two hundred times therefore passes two hundred budget checks and accumulates nothing." That is the actual repetitive-loop failure, and the chart's tools do not address it either.
3. **Circuit breaker** — `scripts/lib/research_circuit.py`, CLOSED/OPEN/HALF_OPEN, 3 failures, 600s cooldown; refuses new backend calls without dropping durable requests.
4. **Retry classification** — `scripts/lib/cio_provider_retry_v1.py` types dispositions as `RETRYABLE_TRANSIENT` / `NON_RETRYABLE_COST` / `NON_RETRYABLE_POLICY` / `NON_RETRYABLE_VALIDATION`, so a policy rejection is never retried as if it were a timeout. Journal records metadata and hashes only — never prompts, responses or credentials.

Plus `search_budget.py` (deny-on-error) and `telegram_send_idempotency.py` on the delivery side.

**Why not LangGraph/StateGraph:** they bound *graph* iteration — cycles in a single workflow run.
Three of our four brakes are cross-run and cross-provider: a cumulative goal budget, a provider
circuit, a retry taxonomy. A state graph would not have caught the two-hundred-lap goal, because
each lap is a legitimate separate run.

**Recommendation:** keep. No action.

---

### 08 · Overloaded with too much context — chart says LlamaIndex / Rerankers

**Verdict: LIVE, with a real but bounded weakness.**

Reranking exists: `scripts/rag_retrieval.py:27` defines `SOURCE_BOOSTS` applied at `:126` —
`trade_outcome` 1.35, `decision_outcome` 1.30, `research_finding` 1.25, `agent_synthesis` 1.20,
`cio_decision` 1.15, `fused_signal` 1.10, `agent_result` 1.05. Combined with the per-class decision
TTLs from row 03, stale evidence is excluded before ranking rather than ranked down.

Compression: `memory_consolidator.py`, `memory_decay.py`, `brief_semantic_dedupe.py`,
`prefetch_hybrid_rag_context.py`. Retrieval quality is measured, not assumed —
`scripts/hybrid_rag_retrieval_pilot.py` benchmarks nomic vs qwen3 embeddings over a fixed 40-query
set, read-only against production, with siblings `embedding_ab_baseline.py`,
`compare_phase2f_global_shadow_retrieval.py`, `phase2g_hybrid_canary_retrieval.py`.

**The weakness, stated plainly:** `SOURCE_BOOSTS` is a **static source-type prior**, not a
reranker. It cannot tell a highly relevant `news` item from an irrelevant one — it boosts by
category regardless of query. A cross-encoder reranker scores *query-document* relevance, which is
a genuinely different and better signal. Calling what we have "reranking" overstates it.

**Recommendation:** the strongest *candidate* case for a new dependency in this audit, and still
not urgent. A local cross-encoder (`bge-reranker` class, servable through the Ollama path we
already run) would cost no egress and no vendor. Gate it the way we gate everything else: run it
against the existing 40-query harness, and adopt only if it measurably beats `SOURCE_BOOSTS`. Do
not adopt LlamaIndex for this — we need a scoring model, not a framework.

---

### 09 · Difficult to debug and trace — chart says LangGraph / Langfuse

**Verdict: DARK. Widest gap between what is built and what runs.**

The tracing layer is genuinely good. `scripts/lib/agent_run_trace.py` defines `AgentRunTrace@v1`:
append-only crash-safe JSONL, `wake_id` + `trace_id` + `parent_trace_id`, queryable by
wake/decision/case, **chain-of-thought never persisted**, secrets redacted before persist, and
`workflow_metrics@v1` carrying the ten fields the LangGraph gate consumes.
`scripts/lib/agent_tool_trace.py` records every approved tool call with capability class,
read/write classification, request/response digests, timing, provider and source-as-of — never
OAuth tokens, API keys, session cookies, broker credentials or signing keys.

Around it: `cio_lineage.py`, `intelligence_lineage.py`, `lifecycle_trace.py`, `cio_wake_traces.py`,
`agent_trace_retention.py`, `curation_lineage.py`.

**And it is barely on.** `AGENT_RUN_TRACE` defaults to `0` (`agent_feature_flags.py:35`), set
nowhere in `.env.example` or any crontab. Outside `scripts/lib/`, `agent_run_trace` is imported by
`control_plane_api.py` (which *serves* traces) and `cio_gate_measurement_bridge.py` (which
*consumes* them) — but **not by the agent job runner that would produce them**.
`scripts/process_watchlist_agent_jobs.py` imports no trace module at all. `agent_tool_trace` has one
non-lib importer.

We built the reader and the consumer and left the writer switched off. This also undermines row 05,
where the LangGraph gate's `NOT_REQUIRED` verdict is computed from workflow metrics that are
largely not being written — consistent with `AGENTS.md` §0 rule 8: exit code 0, and by extension a
green gate, is not evidence of work.

**Why not Langfuse:** it is LLM-call observability — prompts, completions, latency, cost. Two
mismatches. First, hosted Langfuse means prompts containing portfolio positions leave the box:
§17 operator-only egress, same rail as row 06. Second, it traces *calls*; we need to trace
*decisions* — `decision_id`, `case_id`, `wake_id`, and the lineage from an event to an advisory to
an outcome. `AgentRunTrace@v1` already models that and Langfuse does not.

Self-hosted Langfuse would clear the egress rail and remains a reasonable *complement* later.
It is not a substitute, and adopting it while our own writer is off would be buying a second
tracing system to avoid turning on the first.

**Recommendation:** set `AGENT_RUN_TRACE=1` and `AGENT_DECISION_PAYLOAD=1`, and emit from
`process_watchlist_agent_jobs.py`. Verify by durable artifact per §0 rule 8 — non-empty
`data/cio/agent_run_traces.jsonl` with rows carrying real `wake_id`s — not by exit code. Retention
is already handled (`agent_trace_retention.py`).

---

### 10 · Taking risky actions on its own — chart says PydanticAI / HITL / Guardrails AI

**Verdict: LIVE, and materially stronger than anything in the chart's column.**

This is the row where the chart's framing is inadequate for our domain. It proposes "require human
approval for critical tasks" — an approval *workflow*. We implement something stronger: the risky
action is **structurally unreachable**, so there is no approval to bypass.

`MBI_BEHAVIOR = 0` is an unconditional raise in code, not a config flag. At
`scripts/lib/cio_instrument_record.py:390`, any attempt to write a behaviour field through the
cognition path raises `BehaviorWriteRefused`. `AGENTS.md` §17 names the control surface explicitly:
"there is no variable to raise, the control surface is the code." Weakening it requires an operator
approval token, and the whole broker subsystem is separate, operator-controlled and 2FA-gated.

Layered above that: `broker_confirmation_gate.py` (vendor-neutral fill confirmation with a
`QUARANTINED` state for anything that cannot be confirmed), `guard_request_approval.py`,
`approval_revalidator.py`, `phase6_approval_audit.py`, `claude_escalation_handler.py`, the §17
operator-only list, and per-agent `denied_tools` from row 02. Every agent definition carries
`DeploymentState.SHADOW`. `agent_feature_flags.activation_scope_check()` enforces that no flag
combination can ever grant broker, order, stop, 2FA or risk-policy authority — the flags are
structurally incapable of unlocking the dangerous thing.

**Why not PydanticAI or a HITL library:** both implement "ask a human before doing X," which
presumes the agent *can* do X and is choosing to ask. Our design is that the agent cannot do X at
all. An approval prompt is a policy; a raise is a rail. For an autonomous system touching a real
portfolio, the rail is the correct control and the approval layer is the fallback, not the primary.

**Recommendation:** keep. No action. This row should not be changed to match the chart.

---

## What to actually do

Ranked by risk reduced per unit of work. Nothing here requires a new dependency; items 1-4 are
wiring under §13.5.

**Status 2026-09-17: items 1-5 are done, item 6 remains a proposal.**

| # | action | row | why now |
|---|---|---|---|
| 1 | Wrap external content in `untrusted_envelope()` at ingest; enable `MEMORY_ADVERSARIAL_SCAN=1` | 04 | only row where DARK carries live adversarial exposure |
| 2 | Enable `AGENT_RUN_TRACE=1` + `AGENT_DECISION_PAYLOAD=1`; emit from the job runner | 09 | we cannot debug or measure what we do not record; also unblocks row 05's evidence |
| 3 | Route production tool calls through `mcp_read_only_gateway`; `MCP_READ_ONLY_GATEWAY=1` in shadow | 02 | fail-closed allowlist exists and guards nothing today |
| 4 | Run the memory shadow: `MEMORY_PROVIDER="local"`, `MEMORY_SHADOW=1`, influence stays `0` | 06 | converts a documented architectural claim into measured evidence |
| 5 | Resolve Tavily: wire a client + `SPILL_ADAPTERS` entry, or retire the registry row | 03 | **operator-only under §17/§7A — propose, do not grant.** Half-declared is the worst state |
| 6 | Benchmark a local cross-encoder reranker against the existing 40-query harness | 08 | only defensible new-dependency candidate; measure before adopting |

Items 1-4 are `AGENTS.md` §7 dry-run candidates: each writes durable state or touches a scheduled
job, so dry-run first and quote the output. Item 5 is operator-only. Item 6 is a measurement, and
adoption after it is a separate decision.

## Standing recommendation on the twenty tools

Adopt none of them on the strength of this chart. The chart's advice is sound for a greenfield
agent; this is not one. In eight of ten rows the homegrown control is better fitted, and in three
(04, 06, 09) the vendor option would additionally breach the §17 egress rail by shipping portfolio
context off-box.

The honest summary is not "we are ahead of this chart." It is that **we built ahead of it and then
did not turn four of the controls on.** The gap between our architecture and our runtime is wider
than the gap between our architecture and the chart.

## Method and limits

Measured at `ede0698` by dependency manifest inspection, import-graph analysis (production callers
vs. test-only callers vs. `check_test_coverage.py` registry entries), feature-flag defaults, and
`config/lane_registry.json`.

**Limits, stated so they are not read as more than they are:**

- Flag state was read from `.env.example` and committed crontabs. **The live `.env` on the runtime
  host is not in this tree and was not read.** If a flag is enabled there, the corresponding DARK
  verdict is wrong — and that would itself be a finding, since a production activation with no
  committed record is exactly the divergence §0 rule 5 is about. **This should be confirmed on
  ms01 before the DARK rows are acted on.**
- "LIVE" means a production module imports and calls the control. It does not mean the control was
  observed firing at runtime from the served release, which is the bar `AGENTS.md` §1 sets for
  finished work.
- Row 08's weakness is an architectural reading, not a measured retrieval-quality result. The
  40-query harness exists to settle it.

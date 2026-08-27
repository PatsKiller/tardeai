# Agent Intelligence Foundation

`READ_ONLY_ADVISORY` program to make Trade AI's agents context-aware,
self-observing, memory-assisted, and proactively advisory — without granting
autonomous trading authority.

## Controlling principles

1. Canonical financial truth always outranks memory.
2. A remembered statement is not a price, holding, cash balance, risk limit, or broker fact.
3. An MCP annotation is not a security boundary.
4. Read-only is enforced server-side by capability and credential design.
5. Every agent wake is traceable.
6. Every material recommendation binds to the exact decision/evidence generation.
7. Missing memory degrades gracefully.
8. Missing MCP providers degrade gracefully.
9. No new framework may become a second system of record.
10. No agent may silently change production policy because it "learned" something.
11. Repeated unchanged notifications are a quality defect.
12. A follow-up promise without a durable revisit is a quality defect.
13. A memory that cannot identify its provenance is not admissible.
14. A tool call that cannot identify its caller/wake is not admissible.
15. If a phase cannot prove its claims with tests and dry-run evidence, it is NOT COMPLETE.

## Phase status

| Phase | Title | Status |
|-------|-------|--------|
| 0 | Release truth, PR1 merge, exact-main deploy & topology convergence | complete (0 violations) |
| 1 | Schemas (ContextEnvelope@v1, AgentRunTrace@v1) | implemented + tested |
| 2 | Observability primitives + dry replay harness | implemented + tested |
| 3 | Read-only MCP gateway | implemented + tested (external NOT_CONFIGURED) |
| 4 | Memory abstraction + Mem0 shadow pilot | implemented + tested (Mem0 NOT_CONFIGURED) |
| 5 | Context-aware agent integration (shadow-only) | implemented + tested |
| 6 | Autonomous office initiative | implemented + tested |
| 7 | Learning loop integration | implemented + tested |
| 8 | LangGraph complexity gate | implemented (NOT_REQUIRED); Letta DEFERRED |
| 9 | Security / threat model / red team | implemented + tested |
| 10 | Comprehensive test program (failure injection + perf) | implemented + tested |
| 11 | Shadow acceptance before behavior influence | implemented (NOT_PROMOTED) |
| 12 | Controlled read-only activation (feature flags) | implemented + tested (defaults off) |

## Modules

- `scripts/lib/agent_context_envelope.py` — ContextEnvelope@v1 + `get_context_for_agent()` chokepoint
- `scripts/lib/agent_run_trace.py` — AgentRunTrace@v1 + append-only JSONL trace store
- `scripts/lib/agent_tool_trace.py` — governed tool-call tracing (capability class + redacted digests)
- `scripts/lib/agent_notification_intelligence.py` — notification reasoning + durable next-review
- `scripts/lib/mcp_read_only_gateway.py` — read-only MCP gateway (allowlist + SSRF/path/redaction + receipts)
- `scripts/lib/mcp_provider_adapters.py` — read-only provider adapters + local test doubles
- `scripts/lib/agent_memory_provider.py` — MemoryProvider protocol + Null/LocalTest providers
- `scripts/lib/agent_memory_governance.py` — MemoryRecord@v1 + admission/authority/conflict rules
- `scripts/lib/agent_mem0_provider.py` — Mem0 shadow adapter (NOT_CONFIGURED) + due diligence
- `scripts/lib/agent_context_integration.py` — specialist sub-envelopes + budget + shadow_compare
- `scripts/lib/agent_wake_taxonomy.py` — canonical wake-trigger taxonomy + autonomous action scope
- `scripts/lib/agent_followup.py` — durable next-review + reject re-open + advisory message composer
- `scripts/lib/agent_learning_linkage.py` — lineage + feedback-vs-outcome invariant + propose_memory_write
- `scripts/lib/langgraph_complexity_gate.py` — orchestration complexity gate (NOT_REQUIRED default)
- `scripts/lib/agent_replay_harness.py` — dry replay over the real 397-wake corpus
- `scripts/lib/agent_shadow_acceptance.py` — shadow comparison + promotion gate
- `scripts/lib/agent_perf_bench.py` — local CPU latency baseline
- `scripts/lib/agent_feature_flags.py` — canonical feature flags + rollback + activation-scope gate

## Specs, decisions & runbooks

- [CONTEXT_ENVELOPE_SPEC.md](./CONTEXT_ENVELOPE_SPEC.md)
- [AGENT_RUN_TRACE_SPEC.md](./AGENT_RUN_TRACE_SPEC.md)
- [MCP_READ_ONLY_GATEWAY.md](./MCP_READ_ONLY_GATEWAY.md)
- [MCP_SECURITY_MODEL.md](./MCP_SECURITY_MODEL.md)
- [MEMORY_GOVERNANCE_AND_MEM0.md](./MEMORY_GOVERNANCE_AND_MEM0.md)
- [MEMORY_ADMISSION_POLICY.md](./MEMORY_ADMISSION_POLICY.md)
- [AUTONOMOUS_OFFICE_INITIATIVE.md](./AUTONOMOUS_OFFICE_INITIATIVE.md)
- [ORCHESTRATION_AND_LANGGRAPH_DECISION.md](./ORCHESTRATION_AND_LANGGRAPH_DECISION.md)
- [EVALUATION_AND_SHADOW_TEST_PLAN.md](./EVALUATION_AND_SHADOW_TEST_PLAN.md)
- [THREAT_MODEL.md](./THREAT_MODEL.md)
- [PRIVACY_AND_REDACTION.md](./PRIVACY_AND_REDACTION.md)
- [DEPLOYMENT_RUNBOOK.md](./DEPLOYMENT_RUNBOOK.md)
- [ROLLBACK_RUNBOOK.md](./ROLLBACK_RUNBOOK.md)
- [PHASE_ACCEPTANCE.md](./PHASE_ACCEPTANCE.md)
- [AGENT_INTELLIGENCE_FOUNDATION_ARCHITECTURE.md](./AGENT_INTELLIGENCE_FOUNDATION_ARCHITECTURE.md)
- [IMPLEMENTATION_LOG.md](./IMPLEMENTATION_LOG.md)
- [ADR/](./ADR/) — 001 context envelope, 002 observability-first, 003 MCP gateway, 004 Mem0 over Letta, 005 LangGraph conditional, 006 memory never financial truth

## Authority

`READ_ONLY_ADVISORY`. Zero broker/order/stop/2FA/risk-policy mutations.
Memory is `NON_AUTHORITATIVE_CONTEXT`, never truth. Learning proposes; humans promote.

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

## Phase status

| Phase | Title | Status |
|-------|-------|--------|
| 0 | Release truth, PR1 merge, exact-main deploy & topology convergence | merge done; deploy/topology pending operator go-ahead |
| 1 | Agent Intelligence Foundation schemas (ContextEnvelope, AgentRunTrace) | implemented + tested |
| 2 | Lightweight observability instrumentation | not started |
| 3 | Read-only MCP gateway | not started |
| 4 | Memory abstraction + Mem0 shadow pilot | not started |
| 5 | Context-aware agent integration | not started |
| 6 | Autonomous office initiative | not started |
| 7 | Learning loop integration | not started |
| 8 | LangGraph complexity gate | not started |
| 9 | Security / threat model / red team | not started |
| 10 | Comprehensive test program | not started |
| 11 | Shadow acceptance before behavior influence | not started |
| 12 | Controlled read-only activation | not started |

## Modules

- `scripts/lib/agent_context_envelope.py` — ContextEnvelope@v1 + `get_context_for_agent()`
- `scripts/lib/agent_run_trace.py` — AgentRunTrace@v1 + append-only JSONL trace store

## Specs & decisions

- [CONTEXT_ENVELOPE_SPEC.md](./CONTEXT_ENVELOPE_SPEC.md)
- [AGENT_RUN_TRACE_SPEC.md](./AGENT_RUN_TRACE_SPEC.md)
- [ADR/001-context-envelope.md](./ADR/001-context-envelope.md)
- [ADR/002-observability-first.md](./ADR/002-observability-first.md)

## Authority

`READ_ONLY_ADVISORY`. Zero broker/order/stop/2FA/risk-policy mutations.

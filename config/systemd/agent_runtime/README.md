# Agent Runtime Scheduler — DEFAULT-DISABLED / PREPARE-ONLY

Deterministic, NON-agentic scheduling design for the Lane D reflective SHADOW
agents. **Nothing here is installed, enabled, or started by the change that adds
it.** These units are reviewed design artifacts. An agent can never schedule
itself, extend its own budget, or change its own permissions.

## Model: one bounded queue per agent

Each agent has exactly one queue and one templated unit instance:

| Instance | Agent | Wave | Enabled |
|----------|-------|------|---------|
| `tradeai-agent-runtime@sentinel`   | Sentinel (integrity)   | 1 | SHADOW |
| `tradeai-agent-runtime@darwin`     | Darwin (scoring)       | 1 | SHADOW |
| `tradeai-agent-runtime@iris`       | Iris (curation)        | 1 | SHADOW |
| `tradeai-agent-runtime@reflection` | Nightly Reflection     | 1 | SHADOW |
| `tradeai-agent-runtime@maria`      | Maria (research)       | 2 | DISABLED |
| `tradeai-agent-runtime@vega`       | Vega (technical)       | 2 | DISABLED |
| `tradeai-agent-runtime@risk_agent` | Guardian Risk          | 2 | DISABLED |
| `tradeai-agent-runtime@aegis`      | Aegis (incidents)      | 2 | DISABLED |

Second-wave instances remain refused by the runner even if a timer is created,
because the agent definition is `enabled=false` / `DESIGNED`.

## Deterministic controls (enforced in code, not by the model)

Implemented in `scripts/agent_runtime/agents/dispatcher.py`
(`BoundedDispatcher`, `CircuitBreaker`) and the agent definitions:

- **One queue per agent**, single-agent scoped (`REFUSED_WRONG_AGENT`).
- **Concurrency limit** — `max_concurrency` (default 1); overflow is left on the
  queue (`REFUSED_CAPACITY`).
- **Budgets** — per-agent model-call / tool-call / cost / deadline budgets live
  on the `AgentDefinition.budget` and are enforced by the governed runtime
  (`MvlRuntime`): SHADOW cost budget is `0.0`.
- **Circuit breaker** — opens after `circuit_breaker_trips_open_after`
  consecutive failures; further jobs return `CIRCUIT_OPEN`.
- **Dedup / idempotency** — jobs are de-duplicated by `dedup_value`
  (`input_hash`); the runtime's persistence layer is idempotent on stable ids.
- **Stale-input refusal** — inputs older than `stale_input_seconds` are refused
  (`REFUSED_STALE`).
- **Cancellation + deadline** — cooperative `should_cancel` between jobs; the
  runtime fails a run `DEADLINE_EXCEEDED` past its deadline.
- **Immutable evidence** — every run/artifact/review/score is written through the
  append-only `agentic_runtime` schema (see `migrations/agentic_runtime/`).
- **Shutdown + rollback** — `Type=oneshot --once` batches never stay resident;
  rollback = disable the timer and restore the prior agent definition version.
- **No raw secret access** — units set `NoNewPrivileges`, `ProtectSystem`,
  empty `CapabilityBoundingSet`; the runner imports no secret/credential tool.

## Enabling (requires explicit, separate operator authorization)

Enabling is intentionally multi-gated and OUT OF SCOPE for this change:

1. Apply the LAB/SHADOW migration + least-privilege roles (see
   `migrations/agentic_runtime/`), which themselves refuse without `--apply`.
2. Wire a governed queue + runtime backend and set
   `AGENT_RUNTIME_QUEUE_MODULE`; without it `run_once.py` fails closed.
3. Create the operator opt-in file `/etc/tradeai/agent_runtime_enabled`
   (the `ConditionPathExists` gate on every unit).
4. Set `AGENT_RUNTIME_OPERATOR_AUTH=1` in the service environment.
5. Confirm the agent's maturity gates are measured and accepted
   (`scripts/agent_runtime/agents/maturity_gates.py`); no agent is promotable
   with unmeasured gates.
6. Only then `systemctl enable --now tradeai-agent-runtime@<agent>.timer`.

Until all of the above, the runner prints the prepare-only banner and exits
non-zero.

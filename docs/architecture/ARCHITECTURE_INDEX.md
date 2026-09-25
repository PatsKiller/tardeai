# Architecture Index — where to look before you change a component

Status:      ACTIVE
Owner:       platform (coordinator-maintained; any agent may propose edits via PR)
as_of:       2026-09-25T09:20:00-04:00
Measured at: base 1c60ecb42 / served 1c60ecb42-main-exact-phase2-20260925-091436

This index is short on purpose. It does **not** own any roster. Each row names the
registry that does, so there is exactly one place to change each fact.

| Question | Authoritative source (edit here, nowhere else) | Checked by |
|---|---|---|
| Which scheduled jobs exist, their owner, schedule, state | `config/lane_registry.json` (136 lanes) | `scripts/check_lane_registry.py --fail-on-new` |
| Which units and flags must be ON | `config/expected_services.json` (58 units + flags) | `scripts/check_expected_services.py` |
| Declared systemd unit files | `config/systemd/**` (109 files) | not gated (see drift, detail map §4) |
| Persistent agent contracts (tools, authority, budget, lifecycle) | `config/agent_maturity_catalog.json` | `tests/test_agent_maturity_observability.py` |
| Market/portfolio agent routing and intents | `config/agents.yaml` | — |
| OpenClaw agents (Maria, Alex, Iris, …) | `~/.openclaw/openclaw.json` (host, not in repo) | — |
| Coding clients allowed to mutate | `config/agent_clients.yaml` | `tests/test_agent_clients_registry.py` (agent-governance CI) |
| Data domains, providers, writers, freshness | `config/data_source_authority.json` (26 domains, 22 providers) | `scripts/check_data_source_authority.py` |
| Stores that feed operator surfaces | `config/operator_surface_stores.json` | `scripts/report_store_cadence.py`, `tests/test_store_cadence.py` |
| LLM models / processes / lane floors | `config/llm_model_registry.json`, `config/llm_process_registry.json`, `config/llm_lane_floors.json` | — |
| Secret logical names (never values) | `config/secret_registry.yaml` | `scripts/check_no_secrets.py` |
| GUI routes (v3) | `apps/command-center-v3/src/App.tsx` (52 routes) | **no registry** — gap |
| HTTP API routes | `scripts/api_v2.py` `handle()` (:47145) + `scripts/portfolio_server.py` prefix routing | **no registry** — gap |
| Governance authority and agent rules | `AGENTS.md`, `AI_WORK_POLICY.md` | agent-governance CI |

Detail, verification status of every component, the decision-loop diagram and the
drift found between these registries and the running host:
[`AGENT_SERVICE_MAP_2026-09-25.md`](AGENT_SERVICE_MAP_2026-09-25.md).

Before editing: [`docs/governance/NEW_AGENT_STARTS_HERE.md`](../governance/NEW_AGENT_STARTS_HERE.md)
and [`docs/governance/ENGINEERING_STANDARD.md`](../governance/ENGINEERING_STANDARD.md).

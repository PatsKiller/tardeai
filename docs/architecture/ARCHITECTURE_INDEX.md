# Architecture Index — where to look before you change a component

Status:      PROPOSED (ships with the unratified AGENTS.md amendment)
Owner:       platform (coordinator-maintained; any agent may propose edits via PR)
as_of:       2026-09-25T09:20:00-04:00
Measured at: base 1c60ecb42 / served 1c60ecb42-main-exact-phase2-20260925-091436

This index is short on purpose. It does **not** own any roster. Each row names the
registry that does, so there is exactly one place to change each fact.

| Question | Authoritative source (edit here, nowhere else) | Checked by |
|---|---|---|
| Which scheduled jobs exist, their owner, schedule, state | `config/lane_registry.json` (136 lanes) | `scripts/check_lane_registry.py --fail-on-new` |
| Which units and flags must be ON | `config/expected_services.json` (58 units + 2 flags = 60) | `scripts/check_expected_services.py` |
| Declared systemd unit files | `config/systemd/**` (116 files, 101 unit files) | not gated (see drift, detail map §4) |
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
| Memory architecture: what memory is, who must read/write it, how it is enforced | `docs/architecture/cognitive_transformation_20260927/01_MEMORY_ENFORCEMENT_LAYER.md`, `02_GLOBAL_INTELLIGENCE_RECORD.md` (PROPOSED 2026-09-27; the 2026-08-24 memory designs stand, amended) | `MemoryCompliance@v1` audit (proposed) |
| Worker contract (lease, lock, heartbeat, status vocabulary) | `PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md` §5 → `docs/architecture/cognitive_transformation_20260927/06_SUPERVISORY_INTELLIGENCE_LAYER.md` (PROPOSED) | `supervisor.sla` / conformance audit (proposed) |
| Model routing (lane chooser, gating before generation) | `PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md` §9, `docs/architecture/cognitive_transformation_20260927/03_RESEARCH_RETRIEVAL_FIRST.md` (PROPOSED) | `config/llm_process_registry.json` gate |
| SLA, heartbeat, escalation ladder | `docs/architecture/cognitive_transformation_20260927/06_SUPERVISORY_INTELLIGENCE_LAYER.md` (PROPOSED) | breach detector (proposed) |
| Knowledge graph (nodes, edges, traversals that produce work) | `docs/architecture/cognitive_transformation_20260927/07_ENTERPRISE_COGNITIVE_GRAPH.md` (PROPOSED); `TICKER_KNOWLEDGE_GRAPH_GUID_LINEAGE.md` (amended) | projector idempotency (proposed) |
| Silo conformance and architecture drift | `docs/architecture/cognitive_transformation_20260927/05_PLATFORM_INTELLIGENCE_GOVERNANCE.md` (PROPOSED) | `platform-conformance-audit` (proposed) |
| Maturity roadmap to ≥ 4.7 | `docs/architecture/cognitive_transformation_20260927/09_MATURITY_GAP_AND_ROADMAP.md` (PROPOSED; supersedes 09-27 §12 waves 1–5 on approval) | independent re-measurement lane (Wave 5) |

## Who owns a fact when registries disagree

Precedence, highest first:
1. **DSA writer** (`config/data_source_authority.json`), for a **data value or store**.
2. **Lane owner** (`config/lane_registry.json`), for **when and whether a job runs**.
3. **Catalog agent** (`config/agent_maturity_catalog.json`), for an **agent's authority, tools and budget**.

If two of them name different owners for the same thing, don't pick one. Record the
disagreement as drift in the detail map §4 and ask the coordinator.

**A store in no registry** (not a DSA domain or projection, not in `operator_surface_stores.json`)
has **no declared owner or freshness**. Record it as drift. Treat its producer's author (git
blame of the writer) as the provisional contact. Don't hardcode a new freshness threshold for it;
propose a DSA or surface-store row instead. Known example: `dividend_calendar.json` (see map §4).

Detail, verification status of every component, the decision-loop diagram and the
drift found between these registries and the running host:
[`AGENT_SERVICE_MAP_2026-09-25.md`](AGENT_SERVICE_MAP_2026-09-25.md).

Before editing: [`docs/governance/NEW_AGENT_STARTS_HERE.md`](../governance/NEW_AGENT_STARTS_HERE.md)
and [`docs/governance/ENGINEERING_STANDARD.md`](../governance/ENGINEERING_STANDARD.md).

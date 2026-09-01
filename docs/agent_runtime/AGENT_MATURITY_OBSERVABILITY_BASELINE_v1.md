# Agent Maturity Observability Baseline v1

Status:      HISTORICAL
as_of:       2026-07-30T11:19:37-04:00
Measured at: efcc51365 / not measured

Timestamp: 2026-07-30T09:08:15-04:00

Hostname: ms01-openclaw

User: johnclaw

Resolved repository path: `/home/johnclaw/trade-ai-v12-rebuild/worktrees/agent-maturity-observability-v1`

Production-compatible source path verified: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`

Branch: `codex/agent-maturity-observability-v1`

Starting SHA: `306f817993707a99129633a8555352277bc6d05f`

Starting status: clean isolated worktree tracking `origin/main`.

Active AGENTS.md files: none found from repository root to touched directories.

Python: `Python 3.14.4` from the project virtualenv.

Node: `v22.23.1`.

Npm: `/usr/bin/npm --version` was not readable in this shell; frontend checks use direct Node entrypoints for TypeScript and Vite.

Migration framework: repository contains Agent Runtime persistence and migration contract tests; this tranche adds no database migration.

Current read-only runtime boundary: `scripts/agent_runtime_read_boot.py`, `scripts/agent_runtime/read_http.py`, `scripts/agent_runtime/read_api.py`, and `scripts/agent_runtime/read_postgres.py`.

Current maturity/API/UI surfaces: `scripts/agent_runtime/monitoring.py`, `tests/test_agent_runtime_monitoring.py`, `apps/command-center-v3/src/lib/agentRuntimeMonitoring.ts`, `apps/command-center-v3/src/lib/agentRuntimeReadAdapter.ts`, and `apps/command-center-v3/src/pages/AgentRuntimeHub.tsx`.

## Controlling Documents

Primary architecture: `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`.

Architecture-owner amendments or current implementation plans reviewed:

- `docs/architecture/AGENTIC_MVL_DILIGENCE_AND_TODAY_PLAN_2026-07-24.md`
- `docs/architecture/AGENT_MATURITY_COMMAND_CENTER_IMPLEMENTATION_PLAN_2026-07-25.md`
- `docs/architecture/OPENCLAW_HERMES_UPGRADE_ROLLBACK_PLAN_2026-07-23.md`

Controlling rule applied: humans retain financial authority; evidence may earn human review, but metrics and agents cannot grant production authority.

## Source Inventory

- `config/agent_maturity_catalog.json`: canonical catalog with zero financial authority and SHADOW/DESIGNED lifecycle evidence.
- `config/agent_runtime_mvl.json`: MVL runtime configuration; SHADOW/LAB environment evidence and denied authority classes.
- `config/hermes_maturity.yaml`: Hermes maturity-v2 weighted framework; not comparable to Agent Runtime MVL gates.
- `config/hermes_reactions.yaml`: Hermes Scope Governor reaction rules; `review_mode` is false in repository config and is not changed by this task.
- `config/hermes_thresholds.yaml`: adaptive threshold learning config; `review_mode` true for proposals-only learning.
- `scripts/hermes_maturity_gates.py`: DB-computed Hermes honest gate board; live DB facts are not read by this task.
- `scripts/lib/hermes_outcome_bus/maturity.py`: Hermes composite maturity scorer.
- `scripts/agent_runtime/`: contracts, definitions, persistence, read API, monitoring, and zero-authority runtime files.
- `scripts/proposal_agent_review.py`: Maria/Risk/Steph-style proposal review with deterministic fallback if local LLM is unavailable.
- `scripts/proposal_llm_reviewer.py`: local LLM proposal review with deterministic fallback and chunked review provenance.
- `scripts/broker_promote_oversight.py`: broker promotion oversight with local agent review, optional cached/cloud review, lane availability, and WARN/BLOCK logic. This task does not change WARN semantics or cloud requirement policy.
- `scripts/defense_adjudication.py`: deterministic defense adjudication and promotion criteria evaluation; this task does not call write paths.
- `apps/command-center-v3/src/pages/AgentRuntimeHub.tsx`: existing Command Center v3 Agents/Runtime surface.

## Baseline Limits

Production runtime state: UNVERIFIED.

Agent Runtime database rows: UNVERIFIED.

OpenClaw runtime metadata: OPERATOR_CHECK_REQUIRED.

Historical outcome completeness: OPERATOR_DATA_REQUIRED unless sanitized fixtures are supplied.

Secrets were not read. Raw `.env`, `/run/*/secrets`, raw OpenClaw config, broker credentials, TOTP material, and production database credentials were not read.

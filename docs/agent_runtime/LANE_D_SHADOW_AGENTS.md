# Lane D — Autonomous SHADOW Agents (default-disabled, prepare-only)

Status:      ACTIVE
as_of:       2026-07-26T11:32:24-04:00
Measured at: efcc51365 / not measured

This document describes the Lane D deliverable: production-ready, **default-disabled**
governed definitions for the reflective SHADOW agent fleet, plus their scheduler
design, maturity gates, least-privilege database roles, and Command Center
integration. Nothing here grants an agent any authority over trading, brokers,
accounts, positions, approvals, 2FA, production configuration, or its own
schedule / budget / permissions. Everything is SHADOW / LAB and prepare-only.

## What Lane D adds (all on the existing runtime, nothing rebuilt)

Code (`scripts/agent_runtime/agents/`):

| Module | Purpose |
|--------|---------|
| `base.py` | `ShadowAgentSpec` — binds an `AgentDefinition` to triggers, allowed advisory outputs, an independent reviewer and an independent scorer; hard authority + self-governance guards. |
| `definitions.py` | The 8 agent specs and the reviewer/scorer matrix; fails closed at import if any invariant breaks. |
| `governed_output.py` | The single sanctioned channel an agent may use to emit a review / scorecard / candidate lesson / hypothesis / remediation proposal / research task / draft-PR request. Rejects any forbidden verb, secret, or disallowed kind. |
| `maturity_gates.py` | 12 measurable promotion gates; reports `NOT_YET_MEASURED` and `promotable=False` until evidence is supplied and every gate passes. |
| `dispatcher.py` | Deterministic, NON-agentic bounded-queue runner: single-agent scope, concurrency cap, dedup/idempotency, stale-input refusal, circuit breaker, cancellation. Agents can never schedule themselves. |
| `read_projection.py` | Per-agent Command Center read model; marks agents without authoritative evidence `NOT_RUN` so nothing looks live that is not. |
| `run_once.py` | Fail-closed bounded runner entrypoint; refuses without operator auth and a wired queue backend. |

## The fleet

Wave 1 — **enabled in SHADOW** (advisory only):

| Agent | Role | Trigger(s) | Reviewer | Scorer |
|-------|------|-----------|----------|--------|
| Sentinel | Decision-integrity critic | Watch artifact changed / packet rebuild / contradiction-quality exception | Iris | Darwin |
| Darwin | Outcome-join + scorer (no model calls) | Outcome evidence available / scheduled sweep | Iris | Sentinel |
| Iris | Lesson-lifecycle + curation reviewer | Candidate lesson / contradiction / retrieval-quality exception / repeated finding | Sentinel | Darwin |
| Nightly Reflection | Candidate lessons + hypotheses | Nightly bounded batch | Iris | Darwin |

Wave 2 — **DISABLED** (`DESIGNED`, `enabled=false`; definitions only):

| Agent | Role | Reviewer | Scorer |
|-------|------|----------|--------|
| Maria | Evidence-bound fundamental/catalyst research critic | Iris | Darwin |
| Vega | Technical-structure review critic | Sentinel | Darwin |
| Guardian Risk (`risk_agent`) | Critique of deterministic risk evidence | Iris | Darwin |
| Aegis | Incident review + remediation proposals | Sentinel | Darwin |

Every producer's reviewer and scorer is a **different** agent (enforced in
`base.ShadowAgentSpec.validate` and tested).

## Governed autonomous-improvement boundary

Agents may ONLY: research, produce evidence, score, critique, create candidate
lessons/hypotheses, generate remediation proposals, and draft change/PR requests —
and only through `emit_governed_output`. That channel stamps `ADVISORY_ONLY` /
`DRAFT_ONLY` and rejects any payload naming a forbidden authority
(merge/deploy/activate/ratify/promote/order/approve/2FA/config-change/schedule-self/…).
Agents may NEVER merge, deploy, activate, change prod config, alter their own
permissions/budgets/schedule, ratify a lesson, promote a hypothesis, or touch
financial/broker/order/account/approval/2FA truth. These are hard guards in
`contracts.FORBIDDEN_TOOL_PREFIXES`, `base.SELF_GOVERNANCE_TOKENS`, and
`governed_output.FORBIDDEN_OUTPUT_TOKENS`, each with tests.

## Maturity gates

No agent may be marked OPERATIONAL before its gates are measured and accepted.
`evaluate_gates(spec)` with no measurements returns every gate as
`NOT_YET_MEASURED` and `promotable=False`. Gates: min artifact population,
retrieval-provenance completeness, independent-review coverage, independent-score
coverage, contradiction rate, unsupported-claim rate, stale-input refusal
accuracy, deadline/budget adherence, duplicate-run rate, operator usefulness,
rollback test, zero authority violations.

## Command Center integration (/v3/agents)

The read plane that serves real per-run evidence (last run, state, trigger,
checkpoint, artifact, reviewer, score, cost, retrieval count, tool calls,
deadline, failures, stale/schedule state) is **Lane A's deliverable** — the
`ReadOnlyAgentRuntimeAPI` (`read_api.py`), the Postgres reader
(`read_postgres.py`), `monitoring_events.py`, `identifiers.py`, and the
`AgentRuntimeReadAdapter` in the Command Center — currently on PR #163, not on
`main`. Lane D does **not** duplicate it.

Lane D provides `read_projection.fleet_promotion_readmodel()`, which the hub can
render for the "exact blockers to promotion" per agent using **real** spec + gate
data. When authoritative run evidence is absent it is reported `NOT_RUN` /
`evidence_source=NONE`; when Lane A's read plane supplies a run slice, the same
model marks it `LIVE`. No fixture is presented as live.

**Dependency on Lane A:** to show live per-agent run/artifact/review/score
evidence on `/v3/agents`, merge Lane A's read plane (PR #163) and pass its
per-agent slice into `fleet_promotion_readmodel(run_evidence=…)`.

## Database preparation (prepare-only)

- Schema: `migrations/agentic_runtime/0001_mvl.{up,down}.sql` (already present) —
  the isolated 8-table `agentic_runtime` schema, append-only evidence triggers.
- Roles: `migrations/agentic_runtime/0002_roles.{up,down}.sql` — least-privilege
  SHADOW/LAB writers + read-only Command Center reader, scoped to the schema only.
- Applier: `migrations/agentic_runtime/apply.sh` — refuses without `--apply`,
  prints prepare-only, refuses production/missing DSN. **Not applied.**

## Operator authorizations still required (nothing below is done here)

1. Apply `0001` + `0002` to an isolated LAB/SHADOW DB (`apply.sh --apply up`).
2. Set role passwords out-of-band from the secret store.
3. Merge Lane A's read plane (PR #163) for live `/v3/agents` evidence.
4. Wire a governed queue + runtime backend; set `AGENT_RUNTIME_QUEUE_MODULE`.
5. Create `/etc/tradeai/agent_runtime_enabled` and set
   `AGENT_RUNTIME_OPERATOR_AUTH=1`.
6. Measure + accept each agent's maturity gates.
7. Only then enable the per-agent systemd timers.

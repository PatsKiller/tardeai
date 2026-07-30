# Wave-1 SHADOW Agent-Runtime Activation Runbook

**Status:** OPERATOR-RUN, ROOT-REQUIRED. Nothing in this runbook is performed by
automation, and no step in it grants financial/production authority.

This is the exact, ordered procedure to take the four **wave-1 SHADOW** agents
(`sentinel`, `darwin`, `iris`, `reflection`) from *prepare-only / inert* to
*actually producing runtime evidence in the LAB* — the evidence the Agent
Maturity board's read-only bridge (`maturity_observability.collect_runtime_evidence`)
then surfaces as `RUNTIME_EVIDENCE`.

It is a **runbook, not a script**, on purpose: two of the steps (a governed
dispatch backend; root-owned system enablement) are deliberately human-authored
and human-run.

---

## Why the board is empty today (and why that is correct)

- The read plane is live (`/api/v3/agent-maturity` → 200), but there is **no
  runtime evidence** yet: no agent has produced runs/artifacts/reviews in the
  LAB `agentic_runtime` schema.
- `scripts/agent_runtime/agents/run_once.py` is **prepare-only**. It refuses to
  do work and exits non-zero *even when* `AGENT_RUNTIME_OPERATOR_AUTH=1` **and**
  `AGENT_RUNTIME_QUEUE_MODULE=<module>` are set, because dispatch is intentionally
  not wired in this build (`run_once.py`, "queue backend … is named but dispatch
  is not enabled in this build; no work performed.").
- The maturity bridge is fail-closed: until real runs/reviews exist, every agent
  reads `REPOSITORY_EVIDENCE / 0 eligible`. That is honest, not a regression.

So activation requires, in order: **(1)** a LAB DB with the schema/roles, **(2)**
a governed dispatch backend that `run_once.py` can actually run, **(3)** root-owned
enablement, **(4)** gate measurement. Wave-2, promotion, and production activation
stay OFF throughout.

---

## STEP 0 — Preconditions (verify before touching anything)

- Host is `ms01-openclaw`; the LAB Postgres instance is at
  `/home/johnclaw/tradeai-lab/pg17` (own socket + roles).
- Land **`fix/packet-d-lab-dsn-guard`** first (separate PR). Without it, a
  LAB-named DSN (`trade_ai_agentic_lab`) is falsely rejected by Packet-D shadow
  acceptance (`_shadow_dsn_guard`).
- Confirm the kill switch is available: `/etc/tradeai/` exists (root-owned). You
  will create `/etc/tradeai/agent_runtime_enabled` in Step 3 and can remove it to
  halt everything.

---

## STEP 1 — Apply LAB migrations + roles (ROOT / DB-admin)

The migration applier refuses without `--apply` and refuses a prod-looking DSN.

```bash
TRADE_AI_LAB_DSN='postgresql://<admin>@/trade_ai_agentic_lab?host=/home/johnclaw/tradeai-lab/sock' \
  migrations/agentic_runtime/apply.sh --apply up
```

This creates the `agentic_runtime` schema (8 tables: `agent_runs`,
`agent_artifacts`, `agent_tool_calls`, `agent_reviews`, `agent_scores`,
`kb_lessons`, `kb_cases`, `kb_chunks`) and the least-privilege LOGIN roles
`agentic_runtime_lab_rw`, `agentic_runtime_shadow_rw`, `agentic_runtime_reader`
(SELECT-only).

- Set the role passwords **out-of-band** from the secret store (the migration
  does not set them).
- The read plane's `AGENT_RUNTIME_READ_DSN` must use `agentic_runtime_reader`
  (the reader rejects superuser/createdb/replication roles).

**Verify:** `psql "$TRADE_AI_LAB_DSN" -c "\dt agentic_runtime.*"` shows the 8
tables; `agentic_runtime_reader` has SELECT only.

---

## STEP 2 — Configure a provider module for the governed dispatch backend

**The governed dispatch backend now SHIPS** (`scripts/agent_runtime_dispatch_boot.py`,
wired into `run_once.py`) — the bounded/circuit-broken/kill-switchable pipeline
described below is built and unit-tested. What remains is operator-supplied
configuration, NOT engineering of the mechanism:

The backend is **fail-closed and never fabricates work**. It refuses to run unless:
1. `AGENT_RUNTIME_DISPATCH_DSN` = the LAB `agentic_runtime_shadow_rw` writer DSN.
2. `AGENT_RUNTIME_PROVIDER_MODULE` = an operator-authored, reviewed module exposing:
   - `build_providers(agent_id)` → an object with real `.retrieval` / `.model`
     providers (e.g. the local LLM) and `.make_processor(persistence)` returning a
     `processor(JobRequest)` that drives the `MvlRuntime` advisory lifecycle
     (start → retrieve → reason → create_artifact → independent review → score);
   - `job_source(agent_id, limit)` → a bounded `Sequence[JobRequest]` drawn from
     real inputs (e.g. Watch artifacts to critique).

**Why the backend ships no default provider:** hollow/canned providers would
inflate the maturity board's `sample_size` with non-substantive artifacts. The
board must only ever show evidence produced by real model calls over real inputs,
so the provider module is deliberately operator-owned and reviewed.

The shipped backend already guarantees the safety contract (verified by
`tests/test_agent_runtime_dispatch_backend.py`):
- Bounded, single-agent, circuit-broken, dedup, stale-refusing, and
  **kill-switchable** — `should_cancel` observes `/etc/tradeai/agent_runtime_enabled`;
  remove it and every remaining job in the batch is CANCELLED.
- **Driver-isolated** — `psycopg2` is imported only inside
  `agent_runtime_dispatch_boot.py` (out-of-package); `scripts/agent_runtime/**`
  stays driver-free.
- **Advisory-only / zero-authority** — `MvlRuntime` + `governed_output` reject any
  broker/order/2FA/execution/service-control verb; no such import exists in the path.
- Independent reviewer ≠ producer and scorer ≠ producer (the processor records
  reviews/scores under a DIFFERENT agent id than the producer).
- Non-agentic — the backend cannot schedule itself, extend a budget (budgets come
  from the frozen `AgentDefinition`), or change any permission/config.

**Provider-module authoring is the remaining reviewed step** (its own PR): wire the
real model/retrieval providers and the real bounded job source, preserving the
contract above.

**Verify:** with the backend wired,
`python -m scripts.agent_runtime.agents.run_once --agent sentinel --once` performs
one bounded batch and writes rows into `agentic_runtime` (visible via the read
API), and refuses wave-2 agents (`maria/vega/risk_agent/aegis` are
`enabled=false` / `DESIGNED` → `EX_NOPERM`).

---

## STEP 3 — Enable the wave-1 timers (ROOT)

The unit templates live in `config/systemd/agent_runtime/` and are **system-scope**
(they use `WantedBy=timers.target`, `ProtectSystem=strict`, empty
`CapabilityBoundingSet`). Both the `@.service` and `@.timer` carry
`ConditionPathExists=/etc/tradeai/agent_runtime_enabled`.

```bash
# 1) the master opt-in / kill switch (ROOT)
sudo install -m 0644 /dev/null /etc/tradeai/agent_runtime_enabled

# 2) install the unit templates into the system unit dir (ROOT)
sudo cp config/systemd/agent_runtime/tradeai-agent-runtime@.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload

# 3) set AGENT_RUNTIME_OPERATOR_AUTH=1 + AGENT_RUNTIME_QUEUE_MODULE in the service
#    environment (drop-in), pointing QUEUE_MODULE at the Step-2 backend.
sudo systemctl edit tradeai-agent-runtime@.service   # add both Environment= lines

# 4) enable the FOUR wave-1 instances (ROOT)
for a in sentinel darwin iris reflection; do
  sudo systemctl enable --now "tradeai-agent-runtime@${a}.timer"
done
```

Timer cadence is `*:0/15` with `RandomizedDelaySec=120`, `Persistent=false`
(a paused host cannot stampede). Do **not** enable `maria/vega/risk_agent/aegis`.

**Verify:** `systemctl list-timers | grep agent-runtime` shows four timers;
`journalctl -u tradeai-agent-runtime@sentinel` shows bounded batches; the read API
`/api/v3/agent-runtime/runs` returns real rows.

---

## STEP 4 — Measure the 12 maturity gates (LAB, iterative)

Promotion eligibility requires **every** gate in
`scripts/agent_runtime/agents/maturity_gates.py` (`GATE_SPECS`, 12 gates)
measured **and** PASS — with `measurements=None` every gate is `NOT_YET_MEASURED`
and the agent is not promotable. Key gates: `min_artifact_population ≥ 100`,
`retrieval_provenance_completeness = 1.0`, `independent_review_coverage = 1.0`,
`independent_score_coverage = 1.0`, `contradiction_rate ≤ 0.02`,
`unsupported_claim_rate = 0.0`, `stale_input_refusal_accuracy = 1.0`,
`deadline_budget_adherence = 1.0`, `duplicate_run_rate = 0.0`,
`operator_usefulness ≥ 0.7`, `rollback_test_passed`, `authority_violations = 0`.

As gates are measured, feed the measured completion into the maturity board via
the bridge's `runtime_evidence` overlay (`framework_gates_complete=True` **only**
when `evaluate_gates` reports promotable). At ≥100 reviewed artifacts with HEALTHY
independent review and all gates PASS, the board moves the agent to
`ELIGIBLE_FOR_HUMAN_REVIEW` — a **human** then decides. Nothing auto-promotes
(`promotion_authority = HUMAN_ONLY`, `automatic_promotion_permitted = false`).

---

## Kill switch (immediate halt)

```bash
sudo rm /etc/tradeai/agent_runtime_enabled   # ConditionPathExists fails → all timers inert
```

No run starts while the file is absent. (Hermes has its own separate switch,
`data/runtime/HERMES_DISABLED`.)

---

## STILL GATED after this runbook

Wave-2 agents (`maria/vega/risk_agent/aegis`), `production_activation_authorized`,
automatic promotion, and all financial/broker/2FA/execution authority remain OFF.
This runbook only produces **LAB SHADOW advisory evidence** for human review.

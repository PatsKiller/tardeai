# Deployment Runbook — Controlled Read-Only Activation (Phase 12)

Status:      ACTIVE
as_of:       2026-08-17T23:11:04-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY`. This runbook governs how the Agent Intelligence
Foundation's capabilities are turned **on** in production. Activation is
*advisory-context only*: it may change how a recommendation is worded, what is
suppressed, which specialists are consulted, and what is scheduled for revisit —
it may **never** change holdings, cash, risk policy, place an order, write via
MCP, grant LangGraph broker authority, or auto-promote a learned strategy.

The single source of truth for flag values is
`scripts/lib/agent_feature_flags.py`. Everything below must stay in lock-step
with that module.

---

## 1. Prerequisites

Before any flag is enabled, **all** of the following must hold:

1. **Baseline is healthy.** The current production CIO decision path is green,
   the portfolio-server `/v3/cio` health endpoint returns 200, and there are no
   open P0/P1 defects.
2. **Shadow acceptance is complete** (Phase 11). The augmented (memory/MCP-
   assisted) path has been shadow-compared against the baseline path with the
   promotion gate satisfied: 0 canonical-truth overrides, 0 unauthorized
   actions, trace coverage >= 99%, 100% of write-classified MCP calls denied.
3. **Rollback runbook is available** and the operator has confirmed the rollback
   flag set is understood (`docs/agent-intelligence/ROLLBACK_RUNBOOK.md`).
4. **No secrets, no network.** Activation must not introduce any credential,
   network path, or live backend. `MEMORY_PROVIDER` stays `"null"` (or the
   reviewed, self-hosted `"local"` test double) until a human wires and reviews
   a backend.
5. **The activation scope is understood.** Every enabled flag must map to an
   effect that `activation_scope_check()` classifies as **allowed**. Any effect
   it denies is out of scope, permanently.

---

## 2. Feature-flag defaults

All flags are read from the environment and default to their most conservative
value. Absence of an environment variable = the default below.

| Flag | Default | Meaning |
|------|---------|---------|
| `AGENT_CONTEXT_ENVELOPE` | `0` | Enrich wakes with `ContextEnvelope@v1` |
| `AGENT_RUN_TRACE` | `0` | Append `AgentRunTrace@v1` lineage JSONL |
| `MCP_READ_ONLY_GATEWAY` | `0` | Route agent MCP calls through the read-only gateway |
| `MEMORY_PROVIDER` | `"null"` | `"null"` \| `"local"` \| `"mem0"` \| `"durable"` (invalid -> `"null"`) |
| `MEMORY_SHADOW` | `0` | Record memory; never let it influence synthesis |
| `MEMORY_BEHAVIOR_INFLUENCE` | `0` | Let memory shape advisory context (last resort) |
| `LANGGRAPH_WORKER_PILOT` | `0` | LangGraph durable-workflow pilot |

Integer/boolean flags accept `0`/`1`, `true`/`false`, `yes`/`no`, `on`/`off`
(case-insensitive). Any non-`1` value fails closed to `0`. Any `MEMORY_PROVIDER`
outside `{"mem0", "local", "null", "durable"}` fails closed to `"null"`.

### Program 3 — durable memory shadow (does not enable behavior influence)

```bash
export MEMORY_PROVIDER=durable
export MEMORY_SHADOW=1
export MEMORY_BEHAVIOR_INFLUENCE=0
export GOVERNED_MEMORY_ADVISORY_INFLUENCE=SHADOW
```

- **What turns on:** durable JSONL store on shared `data/cio`, Command Center
  Memory tab, retrieval/admission receipts, SHADOW comparator.
- **What stays off:** `MEMORY_BEHAVIOR_INFLUENCE`, broker/order/stop/risk/2FA.
- **Hold until:** canary memory survives restart + CURRENT flip, zero secret
  leaks, zero forbidden-truth admissions, Program 1/2 surfaces still healthy.

---

## 3. Staged activation order

Activation is **strictly ordered**. Never skip a stage, and hold at each stage
long enough to observe before proceeding.

### Stage 1 — Observability first

```bash
export AGENT_CONTEXT_ENVELOPE=1
export AGENT_RUN_TRACE=1
```

- **What turns on:** context-envelope enrichment and run-trace lineage.
- **Effect scope:** purely additive context and auditability. No decision
  changes.
- **Wiring:** the flag-gated hooks are implemented in
  `scripts/lib/agent_runtime_instrumentation.py` and invoked from
  `cio_material_scan._instrument_scan`. They **fail soft** — an observability
  failure never fabricates truth or mutates a decision — and flags OFF is exact
  pre-AIF parity.
- **Hold until:** trace coverage >= 99%, no context-build failures, no digest
  surprises. Compare before/after decision output — it must be identical.

### Stage 2 — Memory shadow

```bash
export MEMORY_SHADOW=1
export MEMORY_PROVIDER=local    # reviewed in-process test double, NOT a live backend
# MEMORY_BEHAVIOR_INFLUENCE stays 0
```

- **What turns on:** memory is *recorded* for shadow comparison, never applied.
- **Effect scope:** none on live output. The augmented path is computed and
  shadow-compared only.
- **Hold until:** shadow packets show the augmented path is understood, `why`
  strings are populated, and 0 unauthorized diffs are observed.

### Stage 3 — Read-only MCP gateway (optional, independent)

```bash
export MCP_READ_ONLY_GATEWAY=1
```

- **What turns on:** agent MCP calls flow through the exact-tool allowlist /
  substring-denylist / SSRF guard chokepoint.
- **Effect scope:** read-only data may inform analysis; write-classified calls
  are denied. Never required for memory influence.

### Stage 4 — Behavior influence (last)

```bash
export MEMORY_BEHAVIOR_INFLUENCE=1   # only after 2 and shadow acceptance
```

- **What turns on:** memory may shape wording/context, inform suppression of
  unchanged recommendations, and inform specialist questions.
- **Precondition (enforced in code):** `behavior_influence_active()` is `True`
  only when `MEMORY_BEHAVIOR_INFLUENCE == 1` **and**
  `MEMORY_PROVIDER != "null"`.
- **Hard boundary:** even with influence on, memory is `NON_AUTHORITATIVE_CONTEXT`.
  It can never outrank `office_truth`, and every forbidden effect in
  `ALLOWED_ACTIVATION_SCOPE["denied"]` remains structurally denied.

> `LANGGRAPH_WORKER_PILOT` is **not part of the default activation path**. It is
> gated by the LangGraph complexity gate (`langgraph_complexity_gate.py`) and
> grants no broker authority. Do not enable it as part of this phase without a
> separate, explicit decision record.

---

## 4. Flag meanings (reference)

- **`AGENT_CONTEXT_ENVELOPE`** — gates the single context chokepoint
  (`get_context_for_agent`) that assembles `office_truth`, decision, memory,
  research, and external read context with explicit retrieval statuses.
- **`AGENT_RUN_TRACE`** — gates append-only, redacted JSONL lineage
  (`wake_id -> trace_id -> decision_id`).
- **`MCP_READ_ONLY_GATEWAY`** — gates the read-only MCP chokepoint; structural
  deny of write/broker/order/stop/auth tools.
- **`MEMORY_PROVIDER`** — selects the memory backend (`null` no-op, `local`
  in-process test double, `mem0` fail-soft adapter).
- **`MEMORY_SHADOW`** — record-and-compare without influence.
- **`MEMORY_BEHAVIOR_INFLUENCE`** — the last, most sensitive flag; only this one
  lets memory shape advisory output.
- **`LANGGRAPH_WORKER_PILOT`** — LangGraph durable-workflow pilot; no authority.

---

## 5. Verification steps

After each stage, verify **all** of the following before advancing:

1. **Authority intact** — `authority == READ_ONLY_ADVISORY`,
   `memory_authority == NON_AUTHORITATIVE_CONTEXT` on every envelope.
2. **Zero mutation** — no broker/order/stop/2FA/risk-policy mutation in any
   trace (grep the trace store for forbidden tool classes).
3. **Truth override = 0** — memory/MCP never rewrites `office_truth`.
4. **Trace coverage >= 99%** — non-empty `trace_id` on wakes.
5. **MCP write denial = 100%** — every write-classified MCP call denied.
6. **Decision parity (Stage 1)** — output identical to baseline.
7. **Shadow acceptance (Stages 2-3)** — augmented vs baseline diffs explained,
   no unauthorized action.
8. **Scope check (Stage 4)** — every observed effect passes
   `activation_scope_check()` as allowed; any "denied" or "unknown" result is an
   immediate rollback trigger.

A reusable self-check:

```python
from scripts.lib.agent_feature_flags import load_feature_flags, behavior_influence_active, activation_scope_check
flags = load_feature_flags()
assert behavior_influence_active(flags) is (flags["MEMORY_BEHAVIOR_INFLUENCE"] == 1 and flags["MEMORY_PROVIDER"] != "null")
for effect in ["memory informs wording", "memory informs suppression"]:
    ok, _ = activation_scope_check(effect)
    assert ok
for effect in ["memory changes holdings", "MCP write", "LangGraph broker authority"]:
    ok, _ = activation_scope_check(effect)
    assert not ok
```

---

## 6. READ_ONLY_ADVISORY guardrails

1. **Memory is context, never truth.** `NON_AUTHORITATIVE_CONTEXT` is structural.
2. **No writes via MCP.** Read-only is enforced by capability/credential design,
   not annotation.
3. **No LangGraph broker authority.** The pilot measures, it never trades.
4. **No learning auto-promotion.** Learning proposes candidates; humans promote.
5. **Fail closed.** Missing provider -> `NOT_CONFIGURED`; unknown effect ->
   denied; unknown flag value -> `0`; invalid provider -> `"null"`.
6. **Any stage can be rolled back** by applying the rollback flag set. See
   `ROLLBACK_RUNBOOK.md`.

## 7. Trace retention (operator deployment step)

`scripts/lib/agent_trace_retention.py` provides bounded retention/rotation for
the two governed trace paths (`agent_run_traces.jsonl`, `agent_tool_traces.jsonl`).
It defaults to dry-run and refuses to touch any unlisted path. To enforce it
operationally, schedule a periodic dry-run + enforce pass (e.g. a user systemd
timer or cron) with an explicit max age / max bytes / max rows. **No automated
timer is installed by this branch** — the operator must add it before production
activation. Never run a purge against any path outside the governed set.

```bash
python3 - <<'PY'
from pathlib import Path
from scripts.lib.agent_trace_retention import enforce_trace_retention, GOVERNED_TRACE_PATHS
for p in GOVERNED_TRACE_PATHS:
    if Path(p).exists():
        print(enforce_trace_retention(p, max_age_days=90, max_bytes=50_000_000, dry_run=True))
PY
```

> The office advises. It never decides for the operator.

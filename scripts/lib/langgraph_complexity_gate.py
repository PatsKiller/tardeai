"""langgraph_complexity_gate.py — LangGraph complexity gate (Phase 8).

READ_ONLY_ADVISORY. Pure, deterministic, no side effects.

This module MEASURES whether introducing LangGraph as a workflow framework is
justified for Trade AI's agent orchestration. It does NOT install or import
LangGraph; it only quantifies the durable-workflow complexity already present in
AgentRunTrace-shaped data and maps that to a gate decision.

Critical semantics:

  * ``gate_decision`` defaults to ``NOT_REQUIRED``. NOT_REQUIRED is a SUCCESS —
    it means the existing orchestration already covers the workflow needs and we
    must NOT introduce a second framework / second system of record.
  * A non-NOT_REQUIRED verdict ("PILOTED") is returned only when a genuine,
    durable-workflow problem is evidenced in the measured traces.
  * Even a PILOTED verdict does NOT authorize broker authority, order mutation,
    or any change to the READ_ONLY_ADVISORY posture.

Letta decision:

  * ``letta_decision`` returns ``DEFERRED``: Trade AI already owns agent
    identity / plans / cases / decisions / memory abstraction / workflow /
    governance. Reconsider only if the existing memory abstraction proves
    structurally inadequate.

No broker / order / stop / 2FA / risk-policy mutation. No network. No secrets.
"""
from __future__ import annotations

from typing import Any

AUTHORITY_READ_ONLY_ADVISORY = "READ_ONLY_ADVISORY"

GATE_NOT_REQUIRED = "NOT_REQUIRED"
GATE_PILOTED = "PILOTED"
GATE_VALID = frozenset({GATE_NOT_REQUIRED, GATE_PILOTED})

# ── Default conservative thresholds ────────────────────────────────────────
GATE_THRESHOLDS: dict[str, int] = {
    "min_durable_waits": 2,             # multiple resumable wait states
    "min_resumes": 2,                   # ...and actual resumes
    "min_branches": 3,                  # complex branching
    "min_retries": 3,                   # ...and retries
    "min_partial_failure_recoveries": 2,  # frequent partial-failure recovery
    "min_manual_recovery_incidents": 2,
    "min_operator_interrupts": 2,       # operator interrupts requiring resume
    "min_state_loss_incidents": 1,      # state-loss / replay complexity
}

# Metric keys produced by compute_complexity_metrics (order stable for output).
_METRIC_KEYS = (
    "avg_steps_per_wake",
    "branch_count",
    "parallel_fan_out",
    "retry_count",
    "durable_wait_count",
    "resume_count",
    "operator_interrupts",
    "cross_process_continuation",
    "partial_failure_recovery",
    "manual_recovery_incidents",
    "state_loss_incidents",
)

# Aliases accepted in a trace for each countable metric (top-level or nested).
_ALIASES: dict[str, tuple[str, ...]] = {
    "branch_count": ("branches", "branch_count"),
    "parallel_fan_out": ("fan_out", "parallel_fanout", "parallel_fan_out"),
    "retry_count": ("retries", "retry_count"),
    "durable_wait_count": ("durable_waits", "waits", "durable_wait_count"),
    "resume_count": ("resumes", "resume_count"),
    "operator_interrupts": ("operator_interrupt_count", "interrupts", "operator_interrupts"),
    "cross_process_continuation": ("cross_process_continuations", "cross_process_continuation"),
    "partial_failure_recovery": ("partial_failure_recoveries", "partial_failure_recovery"),
    "manual_recovery_incidents": ("manual_recoveries", "manual_recovery_incidents"),
    "state_loss_incidents": ("state_losses", "state_loss_incidents"),
}

_NESTED_CONTAINERS = ("workflow", "complexity", "reasoning_runtime", "runtime", "metrics")


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, dict):
        n = value.get("count")
        if isinstance(n, (int, float)):
            return int(n)
        return len(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _trace_count(trace: dict[str, Any], key: str) -> int:
    names = (key, *_ALIASES.get(key, ()))
    for name in names:
        if name in trace:
            return _as_int(trace.get(name))
    for container in _NESTED_CONTAINERS:
        sub = trace.get(container)
        if not isinstance(sub, dict):
            continue
        for name in names:
            if name in sub:
                return _as_int(sub.get(name))
    return 0


def _steps_of(trace: dict[str, Any]) -> int:
    for key in ("step_count", "steps_count"):
        if key in trace:
            return _as_int(trace.get(key))
    steps = trace.get("steps")
    if isinstance(steps, list):
        return len(steps)
    rr = trace.get("reasoning_runtime")
    if isinstance(rr, dict):
        s = rr.get("steps")
        if isinstance(s, list):
            return len(s)
        if "step_count" in rr:
            return _as_int(rr.get("step_count"))
        n = 0
        for k in ("tool_calls", "specialist_calls"):
            if isinstance(rr.get(k), list):
                n += len(rr[k])
        return n
    return 0


def compute_complexity_metrics(traces: list[dict]) -> dict[str, Any]:
    """Measure durable-workflow complexity across AgentRunTrace-shaped traces.

    Deterministic: no timestamps, no randomness, no network. Returns a dict of
    summed counts plus a derived ``avg_steps_per_wake`` and the recorded gate
    decision (computed via ``gate_decision``).
    """
    rows = [t for t in (traces or []) if isinstance(t, dict)]

    # Steps are summed per wake so resumable/continued wakes count once.
    wake_steps: dict[str, int] = {}
    for t in rows:
        wid = str(t.get("wake_id") or t.get("trace_id") or "")
        wake_steps[wid] = wake_steps.get(wid, 0) + _steps_of(t)
    wake_totals = list(wake_steps.values())
    avg_steps = round(sum(wake_totals) / len(wake_totals), 2) if wake_totals else 0.0

    metrics: dict[str, Any] = {
        "traces": len(rows),
        "wakes": len(wake_totals),
        "avg_steps_per_wake": avg_steps,
    }
    for key in _METRIC_KEYS:
        if key == "avg_steps_per_wake":
            continue
        metrics[key] = sum(_trace_count(t, key) for t in rows)

    metrics["authority"] = AUTHORITY_READ_ONLY_ADVISORY
    metrics["gate_decision"] = gate_decision(metrics)
    return metrics


def gate_decision(metrics: dict[str, Any]) -> str:
    """Return the LangGraph gate decision for a measured metrics dict.

    NOT_REQUIRED is the default and is a SUCCESS — it means we must NOT
    introduce LangGraph. PILOTED is returned only when the metrics evidence a
    real durable-workflow problem:

      1. multiple resumable wait states AND complex branching + retries, OR
      2. frequent partial-failure recovery (or manual recovery), OR
      3. operator interrupts requiring exact state resume, OR
      4. state-loss / replay complexity.

    A PILOTED verdict grants NO broker/order/stop/2FA authority; it only records
    that a bounded LangGraph pilot (never a system of record) may be worth
    measuring. See ADR-005.
    """
    m = metrics if isinstance(metrics, dict) else {}
    t = dict(GATE_THRESHOLDS)
    t.update(m.get("thresholds") or {})

    durable_waits = _as_int(m.get("durable_wait_count"))
    resumes = _as_int(m.get("resume_count"))
    branches = _as_int(m.get("branch_count"))
    retries = _as_int(m.get("retry_count"))
    partial_recoveries = _as_int(m.get("partial_failure_recovery"))
    manual_recoveries = _as_int(m.get("manual_recovery_incidents"))
    operator_interrupts = _as_int(m.get("operator_interrupts"))
    state_loss = _as_int(m.get("state_loss_incidents"))

    multi_resumable_waits = (
        durable_waits >= int(t.get("min_durable_waits", 2))
        and resumes >= int(t.get("min_resumes", 2))
    )
    complex_branch_retry = (
        branches >= int(t.get("min_branches", 3))
        and retries >= int(t.get("min_retries", 3))
    )
    frequent_partial_recovery = (
        partial_recoveries >= int(t.get("min_partial_failure_recoveries", 2))
        or manual_recoveries >= int(t.get("min_manual_recovery_incidents", 2))
    )
    operator_interrupt_resume = (
        operator_interrupts >= int(t.get("min_operator_interrupts", 2))
        and resumes >= 1
    )
    state_loss_replay = state_loss >= int(t.get("min_state_loss_incidents", 1))

    if (
        (multi_resumable_waits and complex_branch_retry)
        or frequent_partial_recovery
        or operator_interrupt_resume
        or state_loss_replay
    ):
        return GATE_PILOTED
    return GATE_NOT_REQUIRED


def letta_decision() -> str:
    """Return the Letta decision — always DEFERRED for Trade AI.

    Trade AI already owns agent identity, plans, cases, decisions, memory
    abstraction, workflow, and governance. Reconsider only if the existing
    memory abstraction proves structurally inadequate.
    """
    return "DEFERRED"

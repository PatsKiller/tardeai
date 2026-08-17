"""agent_replay_harness.py — Phase 2.5 dry replay harness (READ_ONLY_ADVISORY).

A DRY-ONLY replay over the historical CIO wake-trace corpus. It READS the
wake traces and, for each wake, measures trace coverage / lineage / context
build, and — only when a ``decision_loader`` supplies decision payloads —
runs the notification-suppression and follow-up-binding simulations.

Hard invariants (enforced structurally, not by convention):

  * READS historical logs only. Never writes to production stores.
  * NEVER resends Telegram, never performs any network I/O, never touches a
    broker / order / stop / 2FA / risk-policy record.
  * The optional ``notify`` callback is accepted for interface parity but is
    NEVER invoked. ``notifications_sent`` is a pure computed simulation.

Honesty model — which metrics are measured on real data vs simulated:

  MEASURED ON REAL DATA (computed from the wake rows themselves):
    number_of_wakes, trace_coverage, trace_completeness,
    decision_lineage_breaks, context_build_failures.

  SIMULATED (populated only when ``decision_loader`` yields decision payloads;
  the real ``data/cio/cio_wake_traces.jsonl`` carries no decision payloads, so
  these are zero on the real corpus until a loader is supplied):
    notifications_considered, notifications_sent, suppressed,
    duplicate_unchanged, missing_next_review, operator_dispositions_recovered.

Metric definitions:

  * trace_coverage       = rows with non-empty ``trace_id`` / total rows.
  * trace_completeness   = rows with ``phase == "close"`` / total rows. This is
    an event-level ratio: the corpus stores BOTH an ``open`` and a ``close``
    row per lifecycle, so this is not the same as "fraction of lifecycles
    completed" (that would require wake_id pairing).
  * decision_lineage_breaks = rows where ``wake_id`` is present but
    ``trace_id`` is empty.
  * context_build_failures   = wakes where building the ContextEnvelope raised
    (including a ``decision_loader`` that raised), or where the built envelope
    failed ``validate_context_envelope``.
  * notifications_considered  = decisions evaluated via ``evaluate_notification``.
  * notifications_sent        = decisions where ``evaluate_notification`` would
    send (computed only; never actually sent).
  * suppressed                = decisions not sent (carried a suppressed_reason).
  * duplicate_unchanged       = subset of suppressed whose reason indicates an
    unchanged/duplicate replay.
  * missing_next_review       = material non-actions (e.g. WAIT) that end up
    with no durable binding (degrade to NEXT_REVIEW_UNAVAILABLE).
  * operator_dispositions_recovered = decisions/wakes with a recoverable
    operator disposition field.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.agent_context_envelope import (
    get_context_for_agent,
    validate_context_envelope,
)
from scripts.lib.agent_notification_intelligence import (
    NEXT_REVIEW_UNAVAILABLE,
    build_next_review,
    dedupe_identity,
    evaluate_notification,
    needs_next_review,
    validate_next_review,
)

# Suppression reasons that indicate an unchanged / duplicate replay.
_UNCHANGED_REASONS = frozenset({"unchanged_replay", "prior_operator_reject_unchanged"})

# Fields consulted (read-only) to recover an operator disposition.
_DISPOSITION_KEYS = ("operator_disposition", "disposition")


def load_wake_traces(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL wake-trace corpus. Skips blank lines and invalid rows.

    Only JSON objects (dicts) are returned; JSON arrays / scalars / unparseable
    lines are skipped. Missing files yield an empty list.
    """
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    try:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return rows
    return rows


def _recover_disposition(
    wake: dict[str, Any], decision: Optional[dict[str, Any]]
) -> Optional[str]:
    """Recover an operator disposition from the decision payload or the wake."""
    for source in (decision, wake):
        if not isinstance(source, dict):
            continue
        for key in _DISPOSITION_KEYS:
            value = source.get(key)
            if value:
                return str(value)
    return None


def _has_bound_next_review(decision: dict[str, Any]) -> bool:
    """True when a decision carries a durable, bound next review.

    A binding means a valid next review with a real kind (TIME / CONDITION /
    DATA_FRESHNESS / EVENT) — NOT ``NEXT_REVIEW_UNAVAILABLE``.
    """
    nr = decision.get("next_review")
    if not isinstance(nr, dict):
        return False
    ok, _ = validate_next_review(nr)
    kind = str(nr.get("kind") or "").upper()
    return ok and kind != NEXT_REVIEW_UNAVAILABLE


def replay_wakes(
    wake_path: str | Path,
    *,
    decision_loader: Optional[Callable[[dict[str, Any]], Optional[dict[str, Any]]]] = None,
    notify: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Dry-replay the wake corpus at ``wake_path`` and return a metrics dict.

    ``decision_loader`` (optional) maps a wake row to a decision payload used
    for the notification / follow-up simulation. When omitted, the harness only
    measures trace coverage / completeness / lineage / context build.

    ``notify`` is accepted for interface parity but is NEVER invoked — this
    harness is DRY-ONLY and performs no send / network side effects. The
    ``notifications_sent`` counter is a pure computed simulation.
    """
    # `notify` is accepted for interface parity only; it is never called.
    _ = notify

    wakes = load_wake_traces(wake_path)
    total = len(wakes)

    traced = 0
    closed = 0
    lineage_breaks = 0
    context_build_failures = 0
    notifications_considered = 0
    notifications_sent = 0
    suppressed = 0
    duplicate_unchanged = 0
    missing_next_review = 0
    operator_dispositions_recovered = 0

    # dedupe identity -> previous notification reasoning record.
    seen: dict[str, dict[str, Any]] = {}

    for wake in wakes:
        trace_id = wake.get("trace_id")
        if trace_id:
            traced += 1
        if str(wake.get("phase") or "").strip().lower() == "close":
            closed += 1
        if wake.get("wake_id") and not trace_id:
            lineage_breaks += 1

        # ── Context build (single chokepoint) ─────────────────────────────
        decision: Optional[dict[str, Any]] = None
        try:
            if decision_loader is not None:
                decision = decision_loader(wake)
            agent = str(wake.get("agent_id") or "alex")
            envelope = get_context_for_agent(agent=agent, wake=wake, decision=decision)
        except Exception:
            context_build_failures += 1
            continue

        ok, _errs = validate_context_envelope(envelope)
        if not ok:
            context_build_failures += 1
            continue

        if not isinstance(decision, dict):
            # No decision payload → nothing to simulate for this wake.
            continue

        # ── Notification suppression (computed only, never sent) ──────────
        notifications_considered += 1
        identity = dedupe_identity(decision)
        previous = seen.get(identity)
        disposition = _recover_disposition(wake, decision)
        if disposition:
            operator_dispositions_recovered += 1

        evaluation = evaluate_notification(
            decision=decision,
            previous=previous,
            operator_disposition=disposition,
        )
        seen[identity] = evaluation

        if evaluation.get("send"):
            notifications_sent += 1
            # NOTE: a real system would call notify() here. We NEVER do.
        else:
            suppressed += 1
            if evaluation.get("suppressed_reason") in _UNCHANGED_REASONS:
                duplicate_unchanged += 1

        # ── Follow-up binding (material non-action with no binding) ───────
        if needs_next_review(decision.get("current_action")):
            if not _has_bound_next_review(decision):
                built = build_next_review(
                    kind=decision.get("next_review_kind"),
                    due_at=decision.get("next_review_due_at"),
                    condition=decision.get("next_review_condition"),
                )
                if str(built.get("kind") or "").upper() == NEXT_REVIEW_UNAVAILABLE:
                    missing_next_review += 1

    return {
        "number_of_wakes": total,
        "notifications_considered": notifications_considered,
        "notifications_sent": notifications_sent,
        "duplicate_unchanged": duplicate_unchanged,
        "suppressed": suppressed,
        "missing_next_review": missing_next_review,
        "operator_dispositions_recovered": operator_dispositions_recovered,
        "decision_lineage_breaks": lineage_breaks,
        "context_build_failures": context_build_failures,
        "trace_coverage": (traced / total) if total else 0.0,
        "trace_completeness": (closed / total) if total else 0.0,
    }


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def render_replay_report(metrics: dict[str, Any]) -> str:
    """Render a human-readable summary of a replay metrics dict."""
    m = metrics or {}
    lines: list[str] = [
        "Agent Intelligence Foundation - Dry Replay Report (Phase 2.5)",
        "=" * 62,
        f"wakes replayed                     : {m.get('number_of_wakes', 0)}",
        f"trace coverage (traced/total)      : {_pct(m.get('trace_coverage'))}",
        f"trace completeness (closed/total)  : {_pct(m.get('trace_completeness'))}",
        f"decision lineage breaks            : {m.get('decision_lineage_breaks', 0)}",
        f"context build failures             : {m.get('context_build_failures', 0)}",
        "",
        "Notification simulation (computed only - never sent):",
        f"  considered                       : {m.get('notifications_considered', 0)}",
        f"  sent (simulated)                 : {m.get('notifications_sent', 0)}",
        f"  suppressed                       : {m.get('suppressed', 0)}",
        f"  duplicate/unchanged              : {m.get('duplicate_unchanged', 0)}",
        f"  missing next-review binding      : {m.get('missing_next_review', 0)}",
        f"  operator dispositions recovered  : {m.get('operator_dispositions_recovered', 0)}",
        "",
        "Measured on real data: number_of_wakes, trace_coverage, "
        "trace_completeness, decision_lineage_breaks, context_build_failures.",
        "Simulated (require a decision_loader): notification and follow-up "
        "metrics above.",
    ]
    return "\n".join(lines)

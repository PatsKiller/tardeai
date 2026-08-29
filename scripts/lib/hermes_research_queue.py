"""Idempotent Hermes research enqueue with fingerprint de-duplication.

Order of operations:
  1. Compute fingerprint
  2. In-flight match → return existing (optional priority bump)
  3. TTL reuse of fresh completed result (optional)
  4. Create new queued request

Store callbacks keep this module free of JSONL I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from lib.hermes_research_fingerprint import compute_fingerprint
    from lib.hermes_research_policy import try_reuse_completed_result
except ImportError:  # pragma: no cover
    from scripts.lib.hermes_research_fingerprint import compute_fingerprint  # type: ignore
    from scripts.lib.hermes_research_policy import try_reuse_completed_result  # type: ignore

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}
# "started" is legacy synonym for "running"
IN_FLIGHT = frozenset({"queued", "running", "started"})
TERMINAL = frozenset({"completed", "failed", "cancelled", "superseded"})


def _ledger_queue_skip(reason: str, request: dict[str, Any], fingerprint: str) -> None:
    """Optional skip-ledger hook. No-op unless RESEARCH_SKIP_GATE=1. Fail-soft."""
    try:
        from scripts.lib.research_skip_ledger import log_mapped_reason
    except Exception:
        try:
            from lib.research_skip_ledger import log_mapped_reason  # type: ignore
        except Exception:
            return
    try:
        subject = request.get("subject") if isinstance(request.get("subject"), dict) else {}
        symbol = str(request.get("symbol") or (subject or {}).get("symbol") or "")
        log_mapped_reason(
            reason,
            symbol=symbol,
            lane="hermes_queue",
            content_hash=fingerprint or "",
        )
    except Exception:
        return


@dataclass
class EnqueueResult:
    created: bool
    research_id: str
    fingerprint: str
    status: str
    reason: str  # created | duplicate_in_flight | priority_bumped | reused_fresh_result
                 # | blocked_non_retryable (Wave 2 slices 20/21)
    existing: Optional[dict[str, Any]] = None
    age_seconds: Optional[float] = None
    ttl_seconds: Optional[int] = None
    reuse_miss_reason: Optional[str] = None
    result_id: Optional[str] = None
    priority: Optional[str] = None
    log_event: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rank(p: str) -> int:
    return PRIORITY_RANK.get((p or "normal").lower(), 1)


def find_in_flight_by_fingerprint(fp: str, index: dict[str, dict]) -> Optional[dict]:
    """
    index: fingerprint -> latest request row (maintained by projection)
    """
    row = index.get(fp)
    if not row:
        return None
    if row.get("status") in IN_FLIGHT:
        return row
    return None


def supersede_open_jobs_for_plan(
    plan_id: str,
    *,
    new_research_id: str,
    list_open_by_plan: Callable[[str], list[dict]],
    update_request: Callable[[str, dict], None],
    now: Optional[datetime] = None,
) -> list[str]:
    """Mark other in-flight jobs for plan as superseded. Opt-in only (replace_open)."""
    now = now or _now()
    superseded_ids: list[str] = []
    for row in list_open_by_plan(plan_id):
        if row.get("research_id") == new_research_id:
            continue
        if row.get("status") not in IN_FLIGHT:
            continue
        update_request(
            row["research_id"],
            {
                "status": "superseded",
                "superseded_by": new_research_id,
                "updated_ts": now.isoformat(),
            },
        )
        superseded_ids.append(row["research_id"])
    return superseded_ids


def enqueue_research_request(
    request: dict[str, Any],
    *,
    find_in_flight_by_fingerprint: Callable[[str], Optional[dict[str, Any]]],
    save_request: Callable[[dict[str, Any]], None],
    update_request: Callable[[str, dict[str, Any]], None],
    new_research_id: Callable[[], str],
    find_fresh_completed: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    record_reuse_event: Optional[Callable[[dict[str, Any]], None]] = None,
    replace_open: bool = False,
    list_open_by_plan: Optional[Callable[[str], list[dict]]] = None,
    list_prior_failures: Optional[Callable[[str], list[dict]]] = None,
    now: Optional[datetime] = None,
) -> EnqueueResult:
    """
    Idempotent enqueue with fingerprint de-duplication.

    Mutates request in place to attach fingerprint / status / timestamps.

    Wave 2 slices 20 / 21 — when `list_prior_failures` is supplied, how this
    plan failed *before* can block the enqueue:

    * `execution_language` is never requeued. The output was correctly refused;
      running it again spends the cap to be refused again.
    * an all-`cost_cap` history waits for the cap window rather than retrying
      into a closed door. A cost cap is the process working, not a worker bug.
    * `truncated` is retryable but capped at one replay per plan per day.

    The callback is optional and the default behaviour is unchanged, so no
    existing caller is silently re-gated.
    """
    now = now or _now()
    now_iso = now.isoformat()

    fp = compute_fingerprint(request)
    request["fingerprint"] = fp
    request.setdefault("schema_version", "hermes_request@v1")

    plan_id = str(request.get("plan_id") or "")
    priority = (request.get("priority") or "normal").lower()

    def _log(**extra: Any) -> dict[str, Any]:
        base = {
            "event": "HERMES_RESEARCH_ENQUEUE",
            "fingerprint": fp,
            "plan_id": plan_id,
            "priority": priority,
            "ts": now_iso,
        }
        base.update(extra)
        return base

    # 0) Non-retryable prior failure? (Wave 2 slices 20/21) Cheapest check first:
    # it costs a ledger read and can save a paid call.
    if list_prior_failures is not None and plan_id:
        try:
            from scripts.lib.cio_research_fail_policy import replay_decision
        except ImportError:  # pragma: no cover
            from lib.cio_research_fail_policy import replay_decision  # type: ignore
        try:
            priors = list_prior_failures(plan_id) or []
        except Exception:
            priors = []
        gate = replay_decision(prior_failures=priors, plan_id=plan_id, now=now)
        if not gate["allow_enqueue"]:
            _ledger_queue_skip(gate["reason"], request, fp)
            return EnqueueResult(
                created=False,
                research_id="",
                fingerprint=fp,
                status="blocked",
                reason="blocked_non_retryable",
                existing=None,
                priority=priority,
                log_event=_log(
                    created=False,
                    reason="blocked_non_retryable",
                    block_reason=gate["reason"],
                    last_failure_class=gate["last_failure_class"],
                    is_worker_bug=False,
                    status="blocked",
                ),
            )

    # 1) In-flight duplicate?
    existing = find_in_flight_by_fingerprint(fp)
    if existing and existing.get("status") in IN_FLIGHT:
        existing_id = str(existing["research_id"])
        bumped = False
        new_p = request.get("priority") or "normal"
        old_p = existing.get("priority") or "normal"
        if _rank(str(new_p)) > _rank(str(old_p)):
            update_request(
                existing_id,
                {
                    "priority": new_p,
                    "updated_ts": now_iso,
                    "priority_bumped_from": old_p,
                },
            )
            bumped = True
            priority = str(new_p).lower()
        reason = "priority_bumped" if bumped else "duplicate_in_flight"
        if reason == "duplicate_in_flight":
            _ledger_queue_skip(reason, request, fp)
        log_event = _log(
            created=False,
            reason=reason,
            research_id=existing_id,
            status=existing.get("status") or "queued",
        )
        return EnqueueResult(
            created=False,
            research_id=existing_id,
            fingerprint=fp,
            status=str(existing.get("status") or "queued"),
            reason=reason,
            existing=existing,
            priority=priority,
            log_event=log_event,
        )

    # 2) Optional: reuse fresh completed result with same fingerprint
    reuse_miss: Optional[str] = None
    if find_fresh_completed is not None:
        decision = try_reuse_completed_result(
            request,
            fingerprint=fp,
            find_completed=find_fresh_completed,
            now=now,
        )
        reuse_miss = decision.reason if not decision.reuse else None
        if decision.reuse and decision.result is not None:
            rid = str(
                decision.result.get("research_id")
                or decision.result.get("result_id")
                or ""
            )
            result_id = decision.result.get("result_id")
            if record_reuse_event is not None:
                record_reuse_event(
                    {
                        "event": "HERMES_RESEARCH_RESULT_REUSED",
                        "fingerprint": fp,
                        "plan_id": plan_id,
                        "research_id": rid,
                        "result_id": result_id,
                        "age_seconds": decision.age_seconds,
                        "ttl_seconds": decision.ttl_seconds,
                        "thesis_version": request.get("thesis_version"),
                        "ts": now_iso,
                    }
                )
            log_event = _log(
                created=False,
                reason="reused_fresh_result",
                research_id=rid,
                status="completed",
                result_id=result_id,
                age_seconds=decision.age_seconds,
                ttl_seconds=decision.ttl_seconds,
                reuse_miss_reason=None,
            )
            _ledger_queue_skip("reused_fresh_result", request, fp)
            return EnqueueResult(
                created=False,
                research_id=rid,
                fingerprint=fp,
                status="completed",
                reason="reused_fresh_result",
                existing=decision.result,
                age_seconds=decision.age_seconds,
                ttl_seconds=decision.ttl_seconds,
                result_id=str(result_id) if result_id else None,
                priority=priority,
                log_event=log_event,
            )
        reuse_miss = decision.reason

    # 3) Create new request
    rid = new_research_id()
    request["research_id"] = rid
    request["status"] = "queued"
    request["created_ts"] = request.get("created_ts") or now_iso
    request["updated_ts"] = request["created_ts"]
    if reuse_miss:
        request["reuse_miss_reason"] = reuse_miss
    save_request(request)

    # Optional supersede of other open jobs on same plan (operator replace_open only)
    if replace_open and list_open_by_plan is not None:
        supersede_open_jobs_for_plan(
            plan_id,
            new_research_id=rid,
            list_open_by_plan=list_open_by_plan,
            update_request=update_request,
            now=now,
        )

    log_event = _log(
        created=True,
        reason="created",
        research_id=rid,
        status="queued",
        reuse_miss_reason=reuse_miss,
    )
    return EnqueueResult(
        created=True,
        research_id=rid,
        fingerprint=fp,
        status="queued",
        reason="created",
        existing=None,
        reuse_miss_reason=reuse_miss,
        priority=priority,
        log_event=log_event,
    )

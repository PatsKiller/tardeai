"""When the deep overnight LLM queue may drain, which lanes it may use, and which jobs are worth running.

Pure policy over config/llm_queue_drain.json. It schedules nothing and calls no model.

Operator 2026-10-31: weekends and market holidays drain all day; trading days drain 21:00-04:00 ET; budget
ceilings stay; DeepSeek only outside its billing peak (scripts/lib/deepseek_offpeak.py).
AUTHORITY: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "llm_queue_drain.json"
ET = ZoneInfo("America/New_York")


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _is_trading_day(now: datetime) -> bool:
    try:
        from scripts.market_session import is_trading_day
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from market_session import is_trading_day  # type: ignore
    return bool(is_trading_day(now))


def _is_deepseek_peak(now: datetime) -> bool:
    try:
        from scripts.lib.deepseek_offpeak import is_deepseek_peak_utc
    except ImportError:  # pragma: no cover
        from lib.deepseek_offpeak import is_deepseek_peak_utc  # type: ignore
    return bool(is_deepseek_peak_utc(now))


def window_state(
    now: Optional[datetime] = None,
    policy: Optional[dict] = None,
    *,
    is_trading_day: Optional[Callable[[datetime], bool]] = None,
) -> dict[str, Any]:
    """{"unrestricted": bool, "reason": str}. Unrestricted = continuous drain allowed now."""
    pol = policy or load_policy()
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(ET)
    win = pol["unrestricted_windows"]
    trading = (is_trading_day or _is_trading_day)(now)
    if not trading and win.get("non_trading_days_all_day"):
        return {"unrestricted": True, "reason": "non_trading_day"}
    night = win.get("trading_day_night_et") or {}
    start, end = int(night.get("start_hour", 24)), int(night.get("end_hour", 0))
    if et.hour >= start or et.hour < end:
        return {"unrestricted": True, "reason": f"night_{start:02d}-{end:02d}_et"}
    return {"unrestricted": False, "reason": "trading_day_hours"}


def provider_chain(
    now: Optional[datetime] = None,
    policy: Optional[dict] = None,
    *,
    is_deepseek_peak: Optional[Callable[[datetime], bool]] = None,
) -> list[str]:
    """Lanes in order; DeepSeek lanes dropped inside DeepSeek's billing peak."""
    pol = policy or load_policy()
    now = now or datetime.now(timezone.utc)
    peak = (is_deepseek_peak or _is_deepseek_peak)(now)
    ds = set(pol.get("deepseek_lanes") or [])
    return [lane for lane in pol["provider_order"] if not (peak and lane in ds)]


def _requeue_policy(policy: Optional[dict]) -> dict[str, Any]:
    return (policy or load_policy())["drain_requeue"]


def failure_rate(total: int, failed: int) -> float:
    """A lane's provider-job error rate; an empty window is 0.0, never a division by zero."""
    total = int(total or 0)
    if total <= 0:
        return 0.0
    return max(0, min(int(failed or 0), total)) / total


def rate_triggers_drain(rate: Optional[float], policy: Optional[dict] = None) -> bool:
    """True when a rate (0.0-1.0) reaches the configured drain threshold, inclusive."""
    threshold = float(_requeue_policy(policy)["failure_rate_threshold"])
    return float(rate or 0.0) >= threshold


def drain_triggered(total: int, failed: int, policy: Optional[dict] = None) -> bool:
    """True when (failed / total) reaches the configured drain threshold; a zero-job window never does."""
    return rate_triggers_drain(failure_rate(total, failed), policy)


def requeue_key(job_id: Any, attempt: int) -> str:
    """Idempotency key for one enqueue: the queue row id plus the 1-based attempt number.

    The queue row id is the stable job identity (deep_overnight_llm_queue.id) and attempt_count already
    counts attempts, so the pair names exactly one runnable copy. Enqueuing the same pair twice is a no-op;
    a later attempt has a different key and is allowed.
    """
    if job_id is None:
        raise ValueError("a requeue needs the queue row's stable job id")
    return f"{job_id}:{int(attempt)}"


def incident_key(job_id: Any, root_cause: Any = None) -> str:
    """One incident per failed job (root cause only when the caller has no job id); the attempt never enters it."""
    if job_id is not None:
        return f"job:{job_id}"
    return f"root:{str(root_cause or 'unknown').strip()}"


def retry_delay_s(attempt: int, policy: Optional[dict] = None) -> int:
    """Seconds before the retry after a failed attempt; the growing schedule lives in config."""
    delays = [int(x) for x in _requeue_policy(policy)["retry_delay_seconds"]]
    if not delays:
        raise ValueError("drain_requeue.retry_delay_seconds must not be empty")
    return delays[min(max(1, int(attempt)), len(delays)) - 1]


def _job_id(job: dict[str, Any]) -> Any:
    return job.get("job_id", job.get("id"))


def _job_attempt(job: dict[str, Any]) -> int:
    return max(0, int(job.get("attempt", job.get("attempt_count", 0)) or 0))


def requeue_plan(
    job: dict[str, Any],
    policy: Optional[dict] = None,
    *,
    after_fix: bool = False,
    now: Optional[datetime] = None,
    is_deepseek_peak: Optional[Callable[[datetime], bool]] = None,
) -> dict[str, Any]:
    """Plan for one failed job: requeue with the configured delay, or hold as a single incident.

    A job that fails its last allowed attempt gets action="hold" and one incident_key, but stays accounted for
    as failed; after_fix=True requeues it with a fresh attempt budget once the cause is fixed. Retries reuse
    provider_order through provider_chain(), so no separate retry lane list exists.
    """
    pol = policy or load_policy()
    cfg = pol["drain_requeue"]
    job_id = _job_id(job)
    if job_id is None:
        raise ValueError("a requeue plan needs the queue row's stable job id")
    attempt = _job_attempt(job)
    root_cause = job.get("root_cause") or job.get("last_error")
    plan: dict[str, Any] = {
        "job_id": job_id,
        "attempt": attempt,
        "providers": provider_chain(now, pol, is_deepseek_peak=is_deepseek_peak),
        "root_cause": root_cause,
    }
    if after_fix:
        return {
            **plan,
            "key": requeue_key(job_id, 1),
            "next_attempt": 1,
            "delay_s": retry_delay_s(1, pol),
            "action": "requeue",
            "reset_attempt": True,
            "incident_key": None,
        }
    if attempt >= int(cfg["max_attempts"]):
        return {
            **plan,
            "key": requeue_key(job_id, attempt),
            "next_attempt": None,
            "delay_s": None,
            "action": "hold",
            "reset_attempt": False,
            "incident_key": incident_key(job_id, root_cause),
        }
    return {
        **plan,
        "key": requeue_key(job_id, attempt),
        "next_attempt": attempt + 1,
        "delay_s": retry_delay_s(attempt, pol),
        "action": "requeue",
        "reset_attempt": False,
        "incident_key": None,
    }


def requeue_batch(
    jobs: list[dict[str, Any]],
    policy: Optional[dict] = None,
    *,
    already_queued: Any = (),
    after_fix: bool = False,
    now: Optional[datetime] = None,
    is_deepseek_peak: Optional[Callable[[datetime], bool]] = None,
) -> list[dict[str, Any]]:
    """Plans for every failed job, idempotent per requeue_key; held jobs stay in the batch as action="hold".

    `already_queued` is the set of requeue keys the caller has already enqueued, so calling twice with the
    same failed job creates one runnable copy, not two.
    """
    pol = policy or load_policy()
    seen = set(already_queued or ())
    plans = []
    for job in jobs:
        plan = requeue_plan(
            job, pol, after_fix=after_fix, now=now, is_deepseek_peak=is_deepseek_peak
        )
        if plan["key"] in seen:
            continue
        seen.add(plan["key"])
        plans.append(plan)
    return plans


def incidents(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The held plans deduplicated by incident_key: a job that exhausts its retries is ONE incident."""
    out: dict[str, dict[str, Any]] = {}
    for plan in plans:
        if plan.get("action") != "hold":
            continue
        key = plan["incident_key"]
        if key in out:
            continue
        out[key] = {
            "incident_key": key,
            "job_id": plan["job_id"],
            "attempt": plan["attempt"],
            "root_cause": plan.get("root_cause"),
            "providers": plan.get("providers") or [],
        }
    return list(out.values())


def drain_state(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts plus the queue label: queued / retrying / drained.

    Anything failed or held keeps the label at "retrying": the queue is drained only when no failed job is left.
    """
    counts: dict[str, Any] = {"queued": 0, "retrying": 0, "failed": 0, "done": 0}
    for job in jobs:
        status = str(job.get("status") or "").strip().lower()
        if job.get("held") or status in {"failed", "held_failed", "exhausted"}:
            counts["failed"] += 1
        elif status in {"retrying", "retry"}:
            counts["retrying"] += 1
        elif status in {"done", "succeeded", "cancelled", "canceled"}:
            counts["done"] += 1
        else:
            counts["queued"] += 1
    if counts["failed"] or counts["retrying"]:
        counts["status"] = "retrying"
    elif counts["queued"]:
        counts["status"] = "queued"
    else:
        counts["status"] = "drained"
    counts["drained"] = counts["status"] == "drained"
    return counts


def is_drained(jobs: list[dict[str, Any]]) -> bool:
    """The drain predicate: True only when no failed job is left."""
    return bool(drain_state(jobs)["drained"])


def triage_filter_sql(policy: Optional[dict] = None) -> tuple[str, list[Any]]:
    """SQL predicate (on alias-free deep_overnight_llm_queue columns) selecting jobs worth paying for."""
    pol = policy or load_policy()
    parts, params = [], []
    for job_type, rule in sorted((pol.get("triage") or {}).get("runnable_job_types", {}).items()):
        days = int(rule.get("symbol_snapshot_within_days") or 0)
        if days > 0:
            parts.append(
                "(job_type = %s AND EXISTS (SELECT 1 FROM ticker_snapshot_daily s "
                "WHERE s.symbol = deep_overnight_llm_queue.symbol AND s.snapshot_date >= current_date - %s))"
            )
            params += [job_type, days]
        else:
            parts.append("(job_type = %s)")
            params.append(job_type)
    if not parts:
        return "FALSE", []
    return "(" + " OR ".join(parts) + ")", params

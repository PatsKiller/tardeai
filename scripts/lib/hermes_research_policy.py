"""Hermes research reuse policy: TTL by priority/situation + quality gate.

TTL measures freshness of the *result* (as_of preferred, else completed_ts),
not the request created_ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional


DEFAULT_RESULT_TTL_SECONDS = {
    "critical": 2 * 3600,   # 2h
    "high": 6 * 3600,       # 6h
    "normal": 12 * 3600,    # 12h
    "low": 24 * 3600,       # 24h
}

# Optional overrides by situation type (wins over priority TTL)
SITUATION_TTL_SECONDS = {
    "S1_POSITION_LIFECYCLE": 6 * 3600,
    "S5_CASH_DEPLOYMENT": 12 * 3600,
    "S6_CONCENTRATION_OR_DISPOSITION": 6 * 3600,
}

MIN_ANSWER_RATIO_FOR_REUSE = 0.5   # at least half of questions answered
MIN_MEAN_CONFIDENCE_FOR_REUSE = 0.4


def resolve_ttl_seconds(request: dict[str, Any]) -> int:
    """Resolve result TTL from situation override, else priority default."""
    priority = (request.get("priority") or "normal").lower()
    subject = request.get("subject") or {}
    if not isinstance(subject, dict):
        subject = {}
    situation = str(
        subject.get("situation_type")
        or request.get("situation_type")
        or ""
    ).upper()
    if situation in SITUATION_TTL_SECONDS:
        return SITUATION_TTL_SECONDS[situation]
    return DEFAULT_RESULT_TTL_SECONDS.get(priority, DEFAULT_RESULT_TTL_SECONDS["normal"])


def parse_ts(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    v = str(value).replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(v)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def result_age_seconds(
    result: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    now = now or datetime.now(timezone.utc)
    ts = parse_ts(result.get("as_of")) or parse_ts(result.get("completed_ts"))
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds())


def is_result_reusable(result: dict[str, Any], request: dict[str, Any]) -> tuple[bool, str]:
    """
    Quality gate before TTL reuse.

    Returns (ok, reason).
    Failed / cancelled / superseded are never reusable.
    """
    status = str(result.get("status") or "completed").lower()
    # Completed results often omit status on the result row itself
    if status in ("failed", "cancelled", "superseded", "queued", "running", "started"):
        return False, "not_completed"
    if status not in ("completed", ""):
        # unknown non-completed
        if status != "completed" and result.get("result_id") is None and not result.get("answers") and not result.get("findings"):
            return False, "not_completed"

    answers = result.get("answers") or []
    findings = result.get("findings") or []
    if not answers and not findings:
        return False, "empty_result"

    # Question coverage (when request lists questions with ids and answers have status)
    req_q = request.get("questions") or []
    if req_q and answers:
        req_ids = set()
        for q in req_q:
            if isinstance(q, dict):
                qid = q.get("id") or q.get("question_id")
                if qid:
                    req_ids.add(qid)
        if req_ids:
            answered = {
                a.get("question_id") or a.get("id")
                for a in answers
                if isinstance(a, dict) and a.get("status") in ("answered", "partial")
            }
            answered.discard(None)
            # If answers lack status fields, treat presence as coverage (MVP results)
            if not any(isinstance(a, dict) and a.get("status") for a in answers):
                # fallback: any answers count as full coverage for MVP rows
                pass
            else:
                ratio = len(req_ids & answered) / max(1, len(req_ids))
                if ratio < MIN_ANSWER_RATIO_FOR_REUSE:
                    return False, "insufficient_answer_coverage"

    confs: list[float] = []
    for a in answers:
        if not isinstance(a, dict) or a.get("confidence") is None:
            continue
        try:
            confs.append(float(a["confidence"]))
        except (TypeError, ValueError):
            continue
    if confs:
        mean_c = sum(confs) / len(confs)
        if mean_c < MIN_MEAN_CONFIDENCE_FOR_REUSE:
            return False, "low_confidence"

    return True, "ok"


@dataclass
class ReuseDecision:
    reuse: bool
    reason: str
    result: Optional[dict[str, Any]] = None
    age_seconds: Optional[float] = None
    ttl_seconds: Optional[int] = None


def _catalyst_invalidates_reuse(
    request: dict[str, Any],
    result: dict[str, Any],
) -> Optional[str]:
    """
    If a medium+ catalyst was added/changed after the result as_of, block TTL reuse.

    Signals may be precomputed on the request (invalidation_signals) or derived
    from request.catalyst / subject.catalyst pack vs result as_of.
    """
    pre = request.get("invalidation_signals") or []
    if isinstance(pre, (list, tuple)):
        for s in pre:
            if str(s) in ("catalyst_added_or_changed", "catalyst_added", "catalyst_changed"):
                return "catalyst_invalidated"

    subject = request.get("subject") if isinstance(request.get("subject"), dict) else {}
    pack = request.get("catalyst") or request.get("catalyst_pack") or subject.get("catalyst")
    if not isinstance(pack, dict):
        return None
    try:
        try:
            from lib.catalyst_domain import catalyst_invalidation_signals
        except ImportError:  # pragma: no cover
            from scripts.lib.catalyst_domain import catalyst_invalidation_signals  # type: ignore
        known = request.get("known_catalyst_event_ids") or result.get("catalyst_event_ids") or []
        prior = result.get("as_of") or result.get("completed_ts")
        signals = catalyst_invalidation_signals(
            str(prior) if prior else None,
            pack,
            known_event_ids=list(known) if known else [],
        )
        if signals:
            return "catalyst_invalidated"
    except Exception:
        return None
    return None


def try_reuse_completed_result(
    request: dict[str, Any],
    *,
    fingerprint: str,
    find_completed: Callable[[str], Optional[dict[str, Any]]],
    now: Optional[datetime] = None,
) -> ReuseDecision:
    """Decide whether a completed result for fingerprint is fresh enough to reuse."""
    now = now or datetime.now(timezone.utc)
    ttl = resolve_ttl_seconds(request)

    # Operator force-refresh bypasses TTL reuse
    provenance = request.get("provenance") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    if (
        request.get("force_refresh")
        or request.get("operator_forced")
        or provenance.get("operator_forced")
    ):
        return ReuseDecision(False, "force_refresh", ttl_seconds=ttl)

    latest = find_completed(fingerprint)
    if not latest:
        return ReuseDecision(False, "no_completed_result", ttl_seconds=ttl)

    ok, why = is_result_reusable(latest, request)
    if not ok:
        return ReuseDecision(False, why, result=latest, ttl_seconds=ttl)

    # Catalyst calendar change after research as_of → do not reuse
    inv = _catalyst_invalidates_reuse(request, latest)
    if inv:
        age_inv = result_age_seconds(latest, now=now)
        return ReuseDecision(
            False,
            inv,
            result=latest,
            age_seconds=age_inv,
            ttl_seconds=ttl,
        )

    age = result_age_seconds(latest, now=now)
    if age is None:
        return ReuseDecision(False, "missing_as_of", result=latest, ttl_seconds=ttl)

    if age > ttl:
        return ReuseDecision(
            False,
            "ttl_expired",
            result=latest,
            age_seconds=age,
            ttl_seconds=ttl,
        )

    return ReuseDecision(
        True,
        "reused_fresh_result",
        result=latest,
        age_seconds=age,
        ttl_seconds=ttl,
    )

"""Portfolio validation projections: PR-004 gates and PR-005 changes over ``validation_gates`` / ``validation_events``.

Read-only by design. The handler hands in ``db_query`` (``api_v2._db_query``); these functions never open a
connection, never write, and never call a broker. Every value drawn is a served column; the two derived facts are
labelled as such (``window.days_remaining`` from ``proof_window_end``, and ``next_action`` — a sentence about the
served state, never a new verdict).

Rules that come from the operator's rails, not from taste:

* **No row means UNKNOWN, never PASS.** An empty portfolio scope proves only that nothing is declared; it is not
  evidence that the checks are healthy. ``counts`` stay readable (0 rows) and ``state`` stays ``UNKNOWN``.
* **``blocks_trading`` NULL is unknown, never "no".** The column is tri-state; a reader must not turn a missing
  declaration into a reassurance.
* **A gate that PASSED is closed and is not re-evaluated.** ``evaluate_open`` selects ``OPEN / OVERDUE / FAILED``
  only, so a closed gate's ``last_evaluated_at`` is the time it closed, not a live heartbeat. The projection says so
  in ``clock.state`` ("closed at its last evaluation") instead of implying a fresh green.
* **A store we cannot read is UNKNOWN with its reason**, never an empty list that reads as "nothing happened".

Payloads
--------
``PortfolioGates@v1``::

    {schema, served_at, state: OK|STALE|UNKNOWN, reason, text, scope: {categories, gates}, snapshot: {computed_at,
     age_s, threshold_s, basis: open_gates|closed_gates, rows_in_scope}, writer: {lane_id, last_ok_at, receipt},
     counts: {rows, failed, overdue, open, closed, blocks_trading, blocks_trading_unknown, never_evaluated} | None,
     items: [...]}

``PortfolioChanges@v1``::

    {schema, served_at, state: OK|UNKNOWN, reason, window: {basis, since, until}, count, latest_at,
     may_be_truncated, items: [{event_id, source_kind, source_id, category, transition, label, proof_window_end,
     occurred_at, detected_at, summary, owner, evidence}]}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

GATES_SCHEMA = "PortfolioGates@v1"
CHANGES_SCHEMA = "PortfolioChanges@v1"

#: The categories a portfolio gate may declare today. A set rather than a prefix so the scope is reviewable in one
#: place; a new category is a code change, not a data change, so a stray row can never silently widen the page.
SCOPE_CATEGORIES: tuple[str, ...] = ("Order protection",)

THRESHOLD_S = 900          # same window as HomeGates@v1: a snapshot older than this is STALE, not OK
FUTURE_SKEW_S = 360        # a clock more than this far ahead is a fault, never freshness
EVENT_LIMIT = 25           # change-list page size; the payload names when the window may be truncated
FALLBACK_WINDOW_H = 24     # when the visit cursor is not recorded, the window is the last 24 h (LQ-2467)
OPEN_SET = ("OPEN", "OVERDUE", "FAILED")
WRITER_LANE = "validation-gates-sync"
WRITER_RECEIPT = "data/runtime/validation-gates-sync_last.json"
LABEL_TEXT = {"FIXED": "FIXED", "FIXED_UNPROVEN": "FIXED · UNPROVEN OVER TIME", "MONITORING": "MONITORING"}

GATES_SQL = (
    "SELECT gate_id, title, category, source, status, blocks, blocks_trading, due_at, owner, fix_ref, label, "
    "proof_window_end, proven_at, last_eval_result, last_evaluated_at, last_eval_detail, evidence, decl_path "
    "FROM validation_gates WHERE category = ANY(%s) "
    "ORDER BY blocks_trading DESC NULLS FIRST, status, due_at NULLS LAST, gate_id"
)
FRESH_SQL = "SELECT MAX(last_evaluated_at) AS computed_at, COUNT(*) AS n FROM validation_gates WHERE category = ANY(%s)"
CHANGES_SQL = (
    "SELECT event_id, source_kind, source_id, category, transition, label, proof_window_end, occurred_at, "
    "detected_at, summary, owner, evidence FROM validation_events "
    "WHERE category = ANY(%s) AND occurred_at > %s AND occurred_at <= %s "
    "ORDER BY occurred_at DESC, event_id DESC LIMIT %s"
)


def _as_dt(v: Any) -> Optional[datetime]:
    """A served timestamp, or None. A naive value is refused (it is ambiguous), not assumed to be UTC."""
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc) if v.tzinfo else None
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _json(v: Any, default: Any) -> Any:
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return default if v is None else v


def _tri(v: Any) -> Optional[bool]:
    """Tri-state: True / False / None(=not declared). Never coerces None to False."""
    if v is None or v == "":
        return None
    if isinstance(v, str):
        low = v.strip().lower()
        return True if low in ("true", "yes", "1") else False if low in ("false", "no", "0") else None
    return bool(v)


def next_action(item: Mapping[str, Any], *, now: Optional[datetime] = None) -> str:
    """One sentence about what the served state asks of a person. Never a new verdict, never an invented date.

    Reads the item's own shape (``last_eval.result``, ``window.end``, ``window.proven_at``); the raw columns are
    accepted too so the function stays usable on a row. ``now`` is optional: without it an elapsed window cannot be
    told apart from an open one, so the caller that has a clock passes it.
    """
    status = str(item.get("status") or "")
    last_eval = item.get("last_eval") if isinstance(item.get("last_eval"), Mapping) else {}
    result = str(last_eval.get("result") or item.get("last_eval_result") or "")
    label = item.get("label")
    owner = item.get("owner") or "the owner"
    if result == "FAIL":
        return f"{owner}: the check failed at its last evaluation; fix the source or the check before it is trusted"
    if result in ("ERROR", "NOT_EVALUABLE"):
        return (f"{owner}: the check could not be evaluated at its last run, so it proves nothing; "
                "the declaration or the query needs review")
    if status in OPEN_SET and not result:
        return f"{owner}: the gate is open and has no recorded evaluation; the sync lane has not run it"
    if label == "FIXED":
        return "Closed as FIXED; the proof window ran without a regress — no action"
    if label == "FIXED_UNPROVEN":
        window = item.get("window") if isinstance(item.get("window"), Mapping) else {}
        end = _as_dt(window.get("end") or item.get("proof_window_end"))
        if end is None:
            return "No action unless it regresses; the proof window has no published end"
        proven = _as_dt(window.get("proven_at") or item.get("proven_at"))
        if now is not None and end <= now and proven is None:
            # The window the operator was told to wait out has LAPSED unproven. "No action" would be a false all-clear:
            # nothing will move this gate on its own (a PASSED gate is never re-evaluated), so the next move is theirs.
            return (f"{owner}: the proof window ended {end.date().isoformat()} with no proven verdict recorded "
                    f"(still {LABEL_TEXT.get('FIXED_UNPROVEN')}); review the evidence and record the outcome")
        return f"No action unless it regresses: proving over the window to {end.date().isoformat()}"
    if label == "MONITORING":
        return f"{owner}: a fix is recorded and monitored; re-open the gate if the source regresses"
    if status == "PASSED":
        return "Closed on a passing evaluation; a closed gate is not re-evaluated"
    return f"{owner}: review the gate; it is {status.lower() or 'in an unrecorded state'}"


def _age_text(age: float) -> str:
    return f"{age / 3600:.1f} h" if age >= 3600 else f"{age / 60:.0f} min" if age >= 60 else f"{age:.0f}s"


def _clock(state_now: datetime, at: Optional[datetime], threshold_s: int, *, status: str = "",
           raw: Any = None) -> dict:
    """The evaluation clock for ONE gate.

    A ``PASSED``/``WAIVED`` gate is closed and is never re-evaluated (``SELECT_OPEN_FOR_EVAL`` selects
    OPEN/OVERDUE/FAILED), so its timestamp is a closure time and CANNOT refresh. Calling that "stale" would be a
    false alarm on a healthy system; it is reported as ``closed`` with its age, and only an OPEN-class gate is
    judged for freshness.
    """
    if at is None:
        if raw is not None and raw != "":
            return {"state": "unreadable", "at": None, "age_s": None, "threshold_s": threshold_s,
                    "text": "the evaluation time is not a readable UTC timestamp"}
        return {"state": "never", "at": None, "age_s": None, "threshold_s": threshold_s,
                "text": "never evaluated"}
    age = (state_now - at).total_seconds()
    if age < -FUTURE_SKEW_S:
        return {"state": "future", "at": _iso(at), "age_s": round(age), "threshold_s": threshold_s,
                "text": "the evaluation time is in the future (clock fault)"}
    age = max(0.0, age)
    if status not in OPEN_SET:
        return {"state": "closed", "at": _iso(at), "age_s": round(age), "threshold_s": threshold_s,
                "text": f"closed at its last evaluation ({_age_text(age)} ago)"}
    return {"state": "stale" if age > threshold_s else "ok", "at": _iso(at), "age_s": round(age),
            "threshold_s": threshold_s,
            "text": f"evaluated {_age_text(age)} ago" + (f" (> {threshold_s}s)" if age > threshold_s else "")}


def _item(g: Mapping[str, Any], *, now: datetime) -> dict:
    detail = _json(g.get("last_eval_detail"), {}) or {}
    if not isinstance(detail, Mapping):
        detail = {}
    end = _as_dt(g.get("proof_window_end"))
    label = g.get("label")
    item = {
        "gate_id": g.get("gate_id"), "title": g.get("title"), "category": g.get("category"),
        "source": g.get("source") or "declaration", "status": g.get("status"), "blocks": g.get("blocks"),
        "blocks_trading": _tri(g.get("blocks_trading")), "due_at": _iso(_as_dt(g.get("due_at"))),
        "owner": g.get("owner"), "fix_ref": g.get("fix_ref"), "label": label, "label_text": LABEL_TEXT.get(label),
        "last_eval": {"result": g.get("last_eval_result"), "at": _iso(_as_dt(g.get("last_evaluated_at"))),
                      "detail": detail.get("detail") or detail.get("reason")},
        "clock": _clock(now, _as_dt(g.get("last_evaluated_at")), THRESHOLD_S, status=str(g.get("status") or ""),
                        raw=g.get("last_evaluated_at")),
        "window": {"end": _iso(end), "proven_at": _iso(_as_dt(g.get("proven_at"))), "label": label,
                   "label_text": LABEL_TEXT.get(label),
                   # derived from a served timestamp, and named as such: never a claim about the check itself
                   "days_remaining": (round((end - now).total_seconds() / 86400, 1) if end else None)},
        "evidence": _json(g.get("evidence"), []), "decl_path": g.get("decl_path"),
    }
    item["next_action"] = next_action(item, now=now)
    return item


def gates_model(rows: Optional[Iterable[Mapping]], fresh: Optional[Mapping], *, now: datetime,
                receipt_ok_at: Optional[datetime] = None,
                categories: tuple[str, ...] = SCOPE_CATEGORIES) -> dict:
    """PortfolioGates@v1. ``rows`` / ``fresh`` None = the read failed -> UNKNOWN, counts None. Never PASS on absence."""
    writer = {"lane_id": WRITER_LANE, "last_ok_at": _iso(receipt_ok_at), "receipt": WRITER_RECEIPT}
    scope = {"categories": list(categories), "gates": None}
    base = {"schema": GATES_SCHEMA, "served_at": _iso(now), "writer": writer, "scope": scope}
    unknown = {**base, "state": "UNKNOWN", "snapshot": None, "counts": None, "items": [], "reason": None}

    if rows is None or fresh is None:
        return {**unknown, "reason": "gate store unreadable", "text": "not available"}
    items_src = [dict(r) for r in rows]
    scope["gates"] = len(items_src)
    count_col = int(fresh.get("n") or 0)
    if not items_src:
        # A readable, empty scope: the counts are measured (0) and the state is still UNKNOWN, because "no gate is
        # declared" is not "the checks pass".
        return {**unknown, "counts": {"rows": 0, "failed": 0, "overdue": 0, "open": 0, "closed": 0,
                                      "blocks_trading": 0, "blocks_trading_unknown": 0, "never_evaluated": 0},
                "reason": f"no portfolio gate is declared for scope {list(categories)}",
                "text": "not declared"}
    items = [_item(g, now=now) for g in items_src]
    counts = {
        "rows": len(items),
        "failed": sum(1 for i in items if i["status"] == "FAILED" or i["last_eval"]["result"] == "FAIL"),
        "overdue": sum(1 for i in items if i["status"] == "OVERDUE"),
        "open": sum(1 for i in items if i["status"] in OPEN_SET),
        "closed": sum(1 for i in items if i["status"] not in OPEN_SET),
        "blocks_trading": sum(1 for i in items if i["blocks_trading"] is True),
        "blocks_trading_unknown": sum(1 for i in items if i["blocks_trading"] is None),
        "never_evaluated": sum(1 for i in items if i["clock"]["state"] == "never"),
        "clock_unreadable": sum(1 for i in items if i["clock"]["state"] == "unreadable"),
    }
    computed = _as_dt(fresh.get("computed_at"))
    if computed is None:
        # No usable snapshot clock. Two different faults, two different sentences: nothing was ever evaluated, or a
        # served timestamp could not be read as UTC (a naive or malformed value is ambiguous, so it is refused).
        if counts["clock_unreadable"]:
            return {**unknown, "counts": counts, "items": items,
                    "reason": "an evaluation timestamp could not be read as a UTC time", "text": "clock unreadable"}
        return {**unknown, "counts": counts, "items": items,
                "reason": "gates exist but none has ever been evaluated", "text": "not evaluated"}
    # Freshness is judged on the gates that the lane still evaluates. A scope of closed gates cannot refresh, and
    # reporting it STALE would raise an alarm on a system whose checks all passed and closed. When nothing is open,
    # the newest evaluation is labelled as a closure time and the state is OK-with-age, never a live green.
    open_clocks = [i["clock"] for i in items if i["status"] in OPEN_SET]
    age_any = max(0.0, (now - computed).total_seconds())
    if not open_clocks:
        snapshot = {"computed_at": _iso(computed), "age_s": round(age_any), "threshold_s": THRESHOLD_S,
                    "rows_in_scope": count_col, "basis": "closed_gates",
                    "text": f"every gate in scope is closed; newest closure {_age_text(age_any)} ago"}
        return {**base, "state": "OK", "reason": None, "snapshot": snapshot, "counts": counts, "items": items,
                "text": (f"{counts['rows']} portfolio gate{'' if counts['rows'] == 1 else 's'} in scope, "
                         f"all closed; newest closure {_age_text(age_any)} ago")}
    if any(c["state"] == "unreadable" for c in open_clocks):
        return {**unknown, "counts": counts, "items": items, "snapshot": {"computed_at": _iso(computed),
                "age_s": round(age_any), "threshold_s": THRESHOLD_S, "rows_in_scope": count_col,
                "basis": "open_gates"},
                "reason": "an open gate's evaluation time is not a readable UTC timestamp", "text": "clock unreadable"}
    if any(c["state"] == "never" for c in open_clocks):
        return {**unknown, "counts": counts, "items": items, "snapshot": {"computed_at": _iso(computed),
                "age_s": round(age_any), "threshold_s": THRESHOLD_S, "rows_in_scope": count_col,
                "basis": "open_gates"},
                "reason": f"{counts['never_evaluated']} open gate(s) have no recorded evaluation",
                "text": "not evaluated"}
    if any(c["state"] == "future" for c in open_clocks):
        return {**unknown, "counts": counts, "items": items, "snapshot": {"computed_at": _iso(computed),
                "age_s": round(age_any), "threshold_s": THRESHOLD_S, "rows_in_scope": count_col,
                "basis": "open_gates"},
                "reason": "an open gate's evaluation time is in the future (clock skew)", "text": "clock fault"}
    open_age = max(c["age_s"] for c in open_clocks)
    stale = open_age > THRESHOLD_S
    snapshot = {"computed_at": _iso(computed), "age_s": round(age_any), "threshold_s": THRESHOLD_S,
                "rows_in_scope": count_col, "basis": "open_gates", "oldest_open_age_s": open_age,
                "text": f"oldest open-gate evaluation {_age_text(open_age)} ago"}
    return {**base, "state": "STALE" if stale else "OK",
            "reason": f"oldest open-gate evaluation {open_age}s old > {THRESHOLD_S}s" if stale else None,
            "snapshot": snapshot, "counts": counts, "items": items,
            "text": (f"{counts['rows']} portfolio gate{'' if counts['rows'] == 1 else 's'} in scope · "
                     f"{counts['open']} open · oldest open evaluation {_age_text(open_age)} ago")}


def changes_model(rows: Optional[Iterable[Mapping]], *, now: datetime, since: Optional[datetime],
                  since_basis: str = "last_visit", limit: int = EVENT_LIMIT,
                  categories: tuple[str, ...] = SCOPE_CATEGORIES) -> dict:
    """PortfolioChanges@v1. ``rows`` None = the read failed -> UNKNOWN. Each event keeps its own timestamp."""
    limit = max(1, int(limit))
    if since is None:
        since = now - timedelta(hours=FALLBACK_WINDOW_H)
        since_basis = "fallback_24h"
    if since > now:
        # A cursor from the future cannot open a window; say so instead of returning a reassuring empty list.
        return {"schema": CHANGES_SCHEMA, "served_at": _iso(now), "state": "UNKNOWN",
                "reason": "the visit cursor is in the future (clock fault)",
                "window": {"basis": since_basis, "since": _iso(since), "until": _iso(now)},
                "count": None, "latest_at": None, "may_be_truncated": False, "items": []}
    window = {"basis": since_basis, "since": _iso(since), "until": _iso(now)}
    if rows is None:
        return {"schema": CHANGES_SCHEMA, "served_at": _iso(now), "state": "UNKNOWN",
                "reason": "change store unreadable", "window": window, "count": None, "latest_at": None,
                "may_be_truncated": False, "items": []}
    items = [{
        "event_id": r.get("event_id"), "source_kind": r.get("source_kind"), "source_id": r.get("source_id"),
        "category": r.get("category"), "transition": r.get("transition"), "label": r.get("label"),
        "label_text": LABEL_TEXT.get(r.get("label")),
        "proof_window_end": _iso(_as_dt(r.get("proof_window_end"))),
        "occurred_at": _iso(_as_dt(r.get("occurred_at"))), "detected_at": _iso(_as_dt(r.get("detected_at"))),
        "summary": r.get("summary"), "owner": r.get("owner"), "evidence": _json(r.get("evidence"), {}),
    } for r in rows]
    # The SQL windows the read, so an honest caller never breaks this. This is the second fence: a row outside the
    # window — or belonging to another page's scope — must not be published as "since your visit", and a wiring
    # mistake must be counted rather than hidden.
    scope = set(categories)
    ts = [_as_dt(i["occurred_at"]) for i in items]
    kept = [i for i, t in zip(items, ts) if t is not None and since < t <= now and i["category"] in scope]
    outside = {"before": sum(1 for t in ts if t is not None and t <= since),
               "after": sum(1 for t in ts if t is not None and t > now),
               "unreadable": sum(1 for t in ts if t is None),
               "out_of_scope": sum(1 for i in items if i["category"] not in scope)}
    latest = max((i["occurred_at"] for i in kept if i["occurred_at"]), default=None)
    return {"schema": CHANGES_SCHEMA, "served_at": _iso(now), "state": "OK", "reason": None, "window": window,
            "count": len(kept), "latest_at": latest, "may_be_truncated": len(items) >= limit,
            "outside_window": outside, "items": kept}


# ---- handler glue (the wiring cc-opus-3 routes to) ------------------------------------------------------------

def read_gates(db_query: Callable[..., Any], *, now: Optional[datetime] = None,
               receipt_ok_at: Optional[Callable[[str], Optional[datetime]]] = None) -> dict:
    """GET portfolio gates -> PortfolioGates@v1. ``db_query`` is api_v2._db_query; None on failure."""
    now = now or datetime.now(timezone.utc)
    rows = db_query(GATES_SQL, (list(SCOPE_CATEGORIES),))
    fresh = db_query(FRESH_SQL, (list(SCOPE_CATEGORIES),), fetch="one")
    ok_at = receipt_ok_at(WRITER_LANE) if receipt_ok_at else None
    return gates_model(rows, fresh, now=now, receipt_ok_at=ok_at)


def read_changes(db_query: Callable[..., Any], *, since: Optional[datetime], now: Optional[datetime] = None,
                 since_basis: str = "last_visit", cursor_raw: Optional[str] = None) -> dict:
    """GET portfolio changes -> PortfolioChanges@v1. ``since`` is the server-stamped visit cursor (portfolio.last_seen).

    ``cursor_raw`` is the value as the caller received it. A cursor that was PRESENT but unreadable is answered as
    UNKNOWN, never as the 24 h fallback: the two mean different things, and a silent fallback would widen the window
    the operator is told they are looking at.
    """
    now = now or datetime.now(timezone.utc)
    if since is None and cursor_raw:
        return {"schema": CHANGES_SCHEMA, "served_at": _iso(now), "state": "UNKNOWN",
                "reason": "the visit cursor is not a readable UTC timestamp",
                "window": {"basis": "unreadable_cursor", "since": None, "until": _iso(now)},
                "count": None, "latest_at": None, "may_be_truncated": False, "items": []}
    window_since = since if since is not None else now - timedelta(hours=FALLBACK_WINDOW_H)
    rows = db_query(CHANGES_SQL, (list(SCOPE_CATEGORIES), _iso(window_since), _iso(now), EVENT_LIMIT))
    return changes_model(rows, now=now, since=since, since_basis=since_basis)

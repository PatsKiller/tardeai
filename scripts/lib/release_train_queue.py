"""Release Train v2 queue store: the append-only event log and its rebuildable projection (Phase 1, 2026-10-21).

Tables (``migrations/2026_10_21_release_queue.sql``, NOT applied; needs operator):

* ``release_queue_events``: the one authoritative store. Append-only (a trigger refuses UPDATE, DELETE and
  TRUNCATE). Every row is a ``TrainEvent@v1``.
* ``release_queue``: one row per PR, a projection rebuilt from the events by :func:`rebuild_projection`. It is
  never an independent writer of truth.

**Read path** (``read_*``): takes the CC's ``db_query(sql, params=None, fetch="all")`` callable, which returns rows,
or ``None`` on any database error (``scripts/api_v2.py:_db_query``). Every read first probes ``to_regclass``, so it
can tell three things apart:

* ``NOT_MIGRATED``: the tables are absent; the operator has not applied the migration;
* ``DB_UNAVAILABLE``: the database did not answer;
* ``OK``: the store answered. Only here is an empty result a real zero.

A read never turns a failure into an empty list or a zero count. Every result carries ``store_state``, ``as_of``
and, when not OK, ``reason``.

**Write path** (:func:`append_event`, :func:`rebuild_projection`): takes a DB-API connection. It validates
TrainEvent@v1 before it touches the database and is idempotent on ``idempotency_key``. NO production caller in
Phase 1: the controller that appends events is Phase 3. Tests drive it with a fake connection.

AUTHORITY: READ_ONLY_ADVISORY for the read path. MBI_BEHAVIOR = 0: no broker, no order, no send.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

try:
    from lib import release_train_contracts as C
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_contracts as C  # type: ignore[no-redef]

NO_CONSUMER_REASON = (
    "write path (append_event / rebuild_projection) has no production caller until the Phase 3 controller; the read "
    "path is consumed by scripts/lib/release_train_view.py behind GET /api/v2/coordination/release-train*"
)

EVENTS_TABLE = "release_queue_events"
QUEUE_TABLE = "release_queue"
MIGRATION = "migrations/2026_10_21_release_queue.sql"

OK, NOT_MIGRATED, DB_UNAVAILABLE = "OK", "NOT_MIGRATED", "DB_UNAVAILABLE"
REASON = {NOT_MIGRATED: "not_migrated", DB_UNAVAILABLE: "db_unavailable"}

IN_TRAIN_STATES = ("selected", "integrating", "qualified", "waiting_window", "merged", "promoting")
STATE_ORDER = ("blocked", "needs_operator", "held", "ready") + IN_TRAIN_STATES + (
    "submitted", "classified", "released", "observing", "rolled_back", "rollback_failed", "superseded",
    "quarantined", "cancelled")

HISTORY_CLASS = {
    "NO_OP": "not_shipped", "FAILED_PRE_MERGE": "not_shipped", "CANCELLED": "not_shipped", "STOPPED": "not_shipped",
    "MERGED_NOT_LIVE": "merged_not_live", "RELEASED_VERIFIED": "verified", "RELEASED_OBSERVING": "observing",
    "ROLLED_BACK": "rolled_back", "ROLLBACK_FAILED": "rollback_failed",
}

EVENT_COLUMNS = ("seq", "event_id", "schema", "event_type", "subject_kind", "subject_id", "pr_number", "train_id",
                 "state_after", "actor", "policy_version", "epoch", "idempotency_key", "occurred_at", "recorded_at",
                 "payload", "evidence_refs")
QUEUE_COLUMNS = ("pr_number", "repo", "head_sha", "state", "risk_class", "risk_reasons", "agent", "depends_on",
                 "intended_window", "blocker", "next_action", "train_id", "submitted_at", "updated_at",
                 "last_event_seq")

DbQuery = Callable[..., Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    return v


def _jsonish(v: Any, default: Any) -> Any:
    if v is None:
        return default
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return v


def _row(r: Any, cols: Iterable[str]) -> dict[str, Any]:
    if isinstance(r, Mapping):
        return {c: r.get(c) for c in cols}
    return dict(zip(cols, r))


# ── read path ─────────────────────────────────────────────────────────────────────────────────────────────────


def probe(db_query: DbQuery) -> dict[str, Any]:
    """Which store state are we in? Never raises. ``{"state", "tables": {name: bool|None}, "as_of", "reason"}``."""
    as_of = _now().isoformat()
    try:
        row = db_query(
            "SELECT to_regclass('public.release_queue_events') IS NOT NULL AS events, "
            "to_regclass('public.release_queue') IS NOT NULL AS queue", None, fetch="one")
    except Exception as exc:  # noqa: BLE001 - a raising db_query is an unavailable store, never an empty one
        return {"state": DB_UNAVAILABLE, "tables": {EVENTS_TABLE: None, QUEUE_TABLE: None}, "as_of": as_of,
                "reason": f"db_unavailable:{type(exc).__name__}"}
    if not row:
        return {"state": DB_UNAVAILABLE, "tables": {EVENTS_TABLE: None, QUEUE_TABLE: None}, "as_of": as_of,
                "reason": "db_unavailable"}
    r = _row(row, ("events", "queue"))
    tables = {EVENTS_TABLE: bool(r["events"]), QUEUE_TABLE: bool(r["queue"])}
    if all(tables.values()):
        return {"state": OK, "tables": tables, "as_of": as_of, "reason": None}
    return {"state": NOT_MIGRATED, "tables": tables, "as_of": as_of, "reason": "not_migrated"}


def _unavailable(p: Mapping[str, Any], **empty: Any) -> dict[str, Any]:
    return {"store_state": p["state"], "as_of": p["as_of"], "reason": p["reason"] or REASON.get(p["state"]),
            "tables": p.get("tables"), **empty}


def _query(db_query: DbQuery, sql: str, params: Any, p: Mapping[str, Any]) -> Optional[list]:
    """Rows, or None when the database failed AFTER a good probe (then the caller reports DB_UNAVAILABLE)."""
    try:
        rows = db_query(sql, params, fetch="all")
    except Exception:  # noqa: BLE001
        return None
    return list(rows) if rows is not None else None


def _event_out(r: Any) -> dict[str, Any]:
    e = _row(r, EVENT_COLUMNS)
    e["payload"] = _jsonish(e.get("payload"), {})
    e["evidence_refs"] = _jsonish(e.get("evidence_refs"), [])
    e["occurred_at"] = _iso(e.get("occurred_at"))
    e["recorded_at"] = _iso(e.get("recorded_at"))
    e["schema"] = e.get("schema") or C.TRAIN_EVENT
    return e


def _queue_out(r: Any, now: datetime) -> dict[str, Any]:
    q = _row(r, QUEUE_COLUMNS)
    q["risk_reasons"] = _jsonish(q.get("risk_reasons"), [])
    q["depends_on"] = _jsonish(q.get("depends_on"), [])
    for k in ("submitted_at", "updated_at"):
        q[k] = _iso(q.get(k))
    q["as_of"] = q.pop("updated_at")
    ts = C.parse_ts(q["as_of"])
    q["age_seconds"] = int((now - ts).total_seconds()) if ts else None
    return q


def read_counts(db_query: DbQuery) -> dict[str, Any]:
    """Projection counts by state group. ``counts`` is None unless the store answered."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, counts=None)
    rows = _query(db_query, "SELECT state, count(*) AS n FROM release_queue GROUP BY state", None, p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, counts=None)
    by = {str(_row(r, ("state", "n"))["state"]): int(_row(r, ("state", "n"))["n"]) for r in rows}
    counts = {"ready": by.get("ready", 0), "held": by.get("held", 0), "needs_operator": by.get("needs_operator", 0),
              "blocked": by.get("blocked", 0), "in_train": sum(by.get(s, 0) for s in IN_TRAIN_STATES)}
    counts["other"] = sum(by.values()) - sum(counts.values())
    counts["total"] = sum(by.values())
    return {"store_state": OK, "as_of": p["as_of"], "reason": None, "tables": p["tables"], "counts": counts,
            "by_state": by}


def read_queue(db_query: DbQuery, *, state: Optional[str] = None, limit: int = 200,
               now: Optional[datetime] = None) -> dict[str, Any]:
    """The projection rows, most actionable first. ``rows`` is None unless the store answered."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, rows=None, total=None)
    if state is not None and state not in C.QUEUE_STATES:
        raise ValueError(f"bad state {state!r}")
    cols = ", ".join(QUEUE_COLUMNS)
    order = "CASE state " + " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(STATE_ORDER)) + " ELSE 99 END"
    where, params = ("WHERE state = %s", [state]) if state else ("", [])
    rows = _query(db_query, f"SELECT {cols} FROM release_queue {where} ORDER BY {order}, pr_number LIMIT %s",
                  [*params, int(limit)], p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, rows=None, total=None)
    now = now or _now()
    out = [_queue_out(r, now) for r in rows]
    return {"store_state": OK, "as_of": p["as_of"], "reason": None, "tables": p["tables"], "rows": out,
            "total": len(out)}


def read_events(db_query: DbQuery, *, after_seq: int = 0, limit: int = 100, train_id: Optional[str] = None,
                pr: Optional[int] = None) -> dict[str, Any]:
    """Events with ``seq > after_seq``, ascending. ``events`` is None unless the store answered."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, events=None, next_after_seq=None)
    conds, params = ["seq > %s"], [int(after_seq)]
    if train_id is not None:
        conds.append("train_id = %s")
        params.append(train_id)
    if pr is not None:
        conds.append("pr_number = %s")
        params.append(int(pr))
    sql = (f"SELECT {', '.join(EVENT_COLUMNS)} FROM release_queue_events WHERE {' AND '.join(conds)} "
           "ORDER BY seq ASC LIMIT %s")
    rows = _query(db_query, sql, [*params, int(limit)], p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, events=None,
                            next_after_seq=None)
    events = [_event_out(r) for r in rows]
    nxt = max((e["seq"] for e in events if e.get("seq") is not None), default=int(after_seq))
    return {"store_state": OK, "as_of": p["as_of"], "reason": None, "tables": p["tables"], "events": events,
            "next_after_seq": nxt}


def read_last_outcome(db_query: DbQuery) -> dict[str, Any]:
    """The newest ``outcome_recorded`` event's TrainOutcome. ``outcome`` None with store OK = none recorded yet."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, outcome=None)
    rows = _query(db_query, f"SELECT {', '.join(EVENT_COLUMNS)} FROM release_queue_events "
                  "WHERE event_type = 'outcome_recorded' ORDER BY seq DESC LIMIT 1", None, p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, outcome=None)
    if not rows:
        return {"store_state": OK, "as_of": p["as_of"], "reason": "no_outcome_recorded", "outcome": None}
    ev = _event_out(rows[0])
    oc = dict(ev["payload"])
    return {"store_state": OK, "as_of": p["as_of"], "reason": None, "seq": ev["seq"],
            "outcome": {k: oc.get(k) for k in ("train_id", "window_id", "outcome", "finished_at", "members",
                                                "candidate_sha", "main_sha", "served_sha")}}


def read_train(db_query: DbQuery, train_id: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Every event of one train, folded by :func:`train_detail`. ``found`` False with store OK = no such train."""
    if not C.TRAIN_ID_RE.match(train_id or ""):
        raise ValueError("bad train_id")
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, train=None, found=None)
    rows = _query(db_query, f"SELECT {', '.join(EVENT_COLUMNS)} FROM release_queue_events WHERE train_id = %s "
                  "ORDER BY seq ASC", [train_id], p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, train=None, found=None)
    events = [_event_out(r) for r in rows]
    if not events:
        return {"store_state": OK, "as_of": p["as_of"], "reason": None, "train": None, "found": False}
    return {"store_state": OK, "as_of": p["as_of"], "reason": None, "found": True,
            "train": train_detail(train_id, events, now=now)}


VERIFIED_OUTCOMES = ("RELEASED_VERIFIED", "RELEASED_OBSERVING")


def read_last_verified(db_query: DbQuery) -> dict[str, Any]:
    """The newest outcome whose immediate acceptance passed (RELEASED_VERIFIED or RELEASED_OBSERVING).
    ``verified`` None with store OK = no verified release recorded yet."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, verified=None)
    rows = _query(db_query, f"SELECT {', '.join(EVENT_COLUMNS)} FROM release_queue_events "
                  "WHERE event_type = 'outcome_recorded' AND payload->>'outcome' = ANY(%s) ORDER BY seq DESC LIMIT 1",
                  [list(VERIFIED_OUTCOMES)], p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, verified=None)
    if not rows:
        return {"store_state": OK, "as_of": p["as_of"], "reason": "no_verified_release", "verified": None}
    oc = _event_out(rows[0])["payload"]
    return {"store_state": OK, "as_of": p["as_of"], "reason": None,
            "verified": {"train_id": oc.get("train_id"), "served_sha": oc.get("served_sha"),
                         "verified_at": oc.get("finished_at"), "outcome": oc.get("outcome"),
                         "window_id": oc.get("window_id")}}


def _train_row(detail: Mapping[str, Any]) -> dict[str, Any]:
    oc = detail.get("outcome") or {}
    members = detail.get("members") or []
    return {"train_id": detail["train_id"], "window_id": detail.get("window_id"), "phase": detail.get("phase"),
            "member_count": len(members) if members else len(oc.get("members") or []),
            "outcome": oc.get("outcome"), "history_class": detail.get("history_class"),
            "started_at": detail.get("started_at"), "finished_at": detail.get("finished_at")}


def read_trains(db_query: DbQuery, *, limit: int = 20, before_seq: Optional[int] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """Trains, newest first (by first event seq), with window, member count, outcome and history class.
    Cursor pagination: pass ``next_before_seq`` back as ``before_seq``. ``trains`` None unless the store answered."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, trains=None, next_before_seq=None)
    conds, params = ["train_id IS NOT NULL"], []
    having = ""
    if before_seq is not None:
        having = "HAVING min(seq) < %s"
        params.append(int(before_seq))
    heads = _query(db_query, f"SELECT train_id, min(seq) AS first_seq FROM release_queue_events "
                   f"WHERE {' AND '.join(conds)} GROUP BY train_id {having} ORDER BY first_seq DESC LIMIT %s",
                   [*params, int(limit)], p)
    if heads is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, trains=None,
                            next_before_seq=None)
    heads = [_row(h, ("train_id", "first_seq")) for h in heads]
    if not heads:
        return {"store_state": OK, "as_of": p["as_of"], "reason": None, "trains": [], "next_before_seq": None}
    ids = [h["train_id"] for h in heads]
    rows = _query(db_query, f"SELECT {', '.join(EVENT_COLUMNS)} FROM release_queue_events "
                  "WHERE train_id = ANY(%s) ORDER BY seq ASC", [ids], p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, trains=None,
                            next_before_seq=None)
    by: dict[str, list] = {i: [] for i in ids}
    for r in rows:
        e = _event_out(r)
        by.setdefault(e["train_id"], []).append(e)
    trains = [_train_row(train_detail(i, by[i], now=now)) for i in ids]
    nxt = int(heads[-1]["first_seq"]) if len(heads) == int(limit) else None
    return {"store_state": OK, "as_of": p["as_of"], "reason": None, "trains": trains, "next_before_seq": nxt}


def read_current_train(db_query: DbQuery, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The newest train with no outcome recorded (in progress). ``train`` None with store OK = no live train."""
    p = probe(db_query)
    if p["state"] != OK:
        return _unavailable(p, train=None)
    rows = _query(db_query, "SELECT train_id FROM release_queue_events WHERE train_id IS NOT NULL GROUP BY train_id "
                  "HAVING bool_and(event_type <> 'outcome_recorded') ORDER BY max(seq) DESC LIMIT 1", None, p)
    if rows is None:
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, train=None)
    if not rows:
        return {"store_state": OK, "as_of": p["as_of"], "reason": "no_train_in_progress", "train": None}
    tid = _row(rows[0], ("train_id",))["train_id"]
    t = read_train(db_query, tid, now=now)
    if t["store_state"] != OK or not t.get("found"):
        return _unavailable({**p, "state": DB_UNAVAILABLE, "reason": "db_unavailable"}, train=None)
    row = _train_row(t["train"])
    return {"store_state": OK, "as_of": p["as_of"], "reason": None,
            "train": {k: row[k] for k in ("train_id", "phase", "member_count", "window_id", "started_at")}}


# ── pure folds ────────────────────────────────────────────────────────────────────────────────────────────────


def train_detail(train_id: str, events: list[Mapping[str, Any]], *, now: Optional[datetime] = None) -> dict:
    """Fold one train's events (ascending seq) into the /trains/{id} shape (docs/ops/RELEASE_TRAIN_API.md §6)."""
    now = now or _now()
    out: dict[str, Any] = {
        "train_id": train_id, "window_id": None, "phase": None, "history_class": "in_progress", "members": [],
        "base_sha": None, "candidate_sha": None, "main_sha": None, "served_sha": None, "artifact_digest": None,
        "policy_version": None, "classifier_version": None, "check_manifest": [], "frozen_at": None,
        "started_at": None, "finished_at": None, "elapsed_seconds": None, "rollback_target": None,
        "outcome": None, "evidence": [], "events": [dict(e) for e in events],
    }
    for e in events:
        pl = e.get("payload") or {}
        out["started_at"] = out["started_at"] or e.get("occurred_at")
        if e.get("state_after"):
            out["phase"] = e["state_after"]
        if e.get("event_type") == "frozen" and pl.get("schema") == C.TRAIN_CANDIDATE:
            for k in ("window_id", "base_sha", "candidate_sha", "policy_version", "classifier_version",
                      "check_manifest", "frozen_at"):
                out[k] = pl.get(k, out[k])
            out["members"] = sorted((dict(m) for m in pl.get("members") or []), key=lambda m: m.get("order", 0))
        elif e.get("event_type") == "evidence_recorded":
            out["evidence"].append(dict(pl))
        elif e.get("event_type") == "outcome_recorded":
            out["outcome"] = dict(pl)
            out["history_class"] = HISTORY_CLASS.get(pl.get("outcome"), "in_progress")
            out["finished_at"] = pl.get("finished_at")
            for k in ("window_id", "base_sha", "candidate_sha", "main_sha", "served_sha", "artifact_digest",
                      "rollback_target"):
                if pl.get(k) is not None:
                    out[k] = pl[k]
        for k in ("candidate_sha", "main_sha", "served_sha", "artifact_digest"):
            if pl.get(k) and e.get("event_type") in ("qualified", "merged", "promoting", "released", "observing"):
                out[k] = pl[k]
    s = C.parse_ts(out["started_at"])
    f = C.parse_ts(out["finished_at"]) or now
    out["elapsed_seconds"] = int((f - s).total_seconds()) if s else None
    return out


def _next_action(state: str, risk_class: Optional[str], reasons: list) -> tuple[Optional[str], Optional[str]]:
    blocker = reasons[0].get("rule") if reasons and state in ("held", "needs_operator", "blocked") else None
    text = {
        "ready": "Waits for the next enabled window.",
        "held": "Does not ride. The owner resolves the risk (see risk_reasons); broker code needs an "
                "execution-engineering grant and a manual release.",
        "needs_operator": "An operator ride approval bound to the full head SHA may admit it.",
        "blocked": "Cannot ride a train; release it through the manual process.",
        "submitted": "Waits for classification.",
        "superseded": "A newer head or dependency superseded this submission; resubmit.",
    }.get(state)
    return blocker, text


def project(events: Iterable[Mapping[str, Any]], *, repo: str = "PatsKiller/tardeai") -> dict[int, dict[str, Any]]:
    """Fold PR events (ascending seq) into ``release_queue`` rows keyed by PR number. Pure and deterministic:
    the same events always give the same projection, so the table can be rebuilt at any time."""
    rows: dict[int, dict[str, Any]] = {}
    for e in events:
        n = e.get("pr_number")
        if e.get("subject_kind") != "pr" or not n:
            continue
        pl = e.get("payload") or {}
        r = rows.setdefault(n, {"pr_number": n, "repo": repo, "head_sha": None, "state": "submitted",
                                "risk_class": None, "risk_reasons": [], "agent": None, "depends_on": [],
                                "intended_window": None, "blocker": None, "next_action": None, "train_id": None,
                                "submitted_at": None, "updated_at": None, "last_event_seq": None})
        et = e.get("event_type")
        if et == "submitted":
            r.update(repo=pl.get("repo") or r["repo"], head_sha=pl.get("head_sha"), agent=pl.get("agent"),
                     depends_on=list(pl.get("depends_on") or []), intended_window=pl.get("requested_window"),
                     submitted_at=e.get("occurred_at"), risk_class=None, risk_reasons=[], train_id=None)
        elif et == "classified":
            r.update(risk_class=pl.get("risk_class"), risk_reasons=list(pl.get("reasons") or []))
        if e.get("train_id"):
            r["train_id"] = e["train_id"]
        if e.get("state_after"):
            r["state"] = e["state_after"]
        r["updated_at"] = e.get("occurred_at")
        r["last_event_seq"] = e.get("seq")
        r["blocker"], r["next_action"] = _next_action(r["state"], r["risk_class"], r["risk_reasons"])
    return rows


# ── write path (no production caller in Phase 1) ──────────────────────────────────────────────────────────────


class InvalidEvent(ValueError):
    """The event failed TrainEvent@v1 validation; nothing was written."""


def append_event(conn: Any, event: Mapping[str, Any]) -> Optional[int]:
    """Append one TrainEvent@v1. Returns the new ``seq``, or None when ``idempotency_key`` already exists (the
    retry is a no-op). Validates first: an invalid event raises InvalidEvent and opens no cursor. The store assigns
    ``seq`` and ``recorded_at``, so a caller-supplied value is refused."""
    errs = C.validate_as(C.TRAIN_EVENT, event)
    if event.get("seq") is not None or event.get("recorded_at") is not None:
        errs.append("seq and recorded_at are assigned by the store")
    if errs:
        raise InvalidEvent("; ".join(errs))
    cols = [c for c in EVENT_COLUMNS if c not in ("seq", "recorded_at")]
    vals = [event.get(c) for c in cols]
    vals[cols.index("schema")] = C.TRAIN_EVENT
    vals[cols.index("payload")] = json.dumps(event.get("payload") or {}, sort_keys=True)
    vals[cols.index("evidence_refs")] = json.dumps(list(event.get("evidence_refs") or []))
    ph = ", ".join("%s::jsonb" if c in ("payload", "evidence_refs") else "%s" for c in cols)
    sql = (f"INSERT INTO release_queue_events ({', '.join(cols)}) VALUES ({ph}) "
           "ON CONFLICT DO NOTHING RETURNING seq")
    with conn.cursor() as cur:
        cur.execute(sql, vals)
        got = cur.fetchone()
    conn.commit()
    if not got:
        return None
    return int(got[0] if not isinstance(got, Mapping) else got["seq"])


def rebuild_projection(conn: Any, *, repo: str = "PatsKiller/tardeai") -> int:
    """Recompute ``release_queue`` from every PR event and upsert it in one transaction. Returns rows written.
    Rows are only inserted or updated: a projection rebuild deletes nothing (AGENTS.md section 0 rule 6)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(EVENT_COLUMNS)} FROM release_queue_events "
                    "WHERE subject_kind = 'pr' ORDER BY seq ASC")
        events = [_event_out(r) for r in cur.fetchall()]
        rows = project(events, repo=repo)
        cols = list(QUEUE_COLUMNS)
        ph = ", ".join("%s::jsonb" if c in ("risk_reasons", "depends_on") else "%s" for c in cols)
        upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "pr_number")
        sql = (f"INSERT INTO release_queue ({', '.join(cols)}) VALUES ({ph}) "
               f"ON CONFLICT (pr_number) DO UPDATE SET {upd}, projected_at = now()")
        for n in sorted(rows):
            r = rows[n]
            vals = [json.dumps(r[c]) if c in ("risk_reasons", "depends_on") else r[c] for c in cols]
            cur.execute(sql, vals)
    conn.commit()
    return len(rows)

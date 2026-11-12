"""Home "Trade-ready" verdict: the approved rule, its input contract, and the served read (LQ-20261107-2144).

Design: Home v010 (the v010 design REPORT.md sections 4-6), operator DECISION 2026-11-11 ~22:44 ET, and
the lead's build spec HOME-BACKEND-SPEC-20261111.md section 2 / LQ-2144 (W1-e):

* **NO** when any P0 is open, OR a validation gate that blocks trading is open, OR Portfolio != OK, OR
  Orders != OK, OR Data != OK. A P1 blocks only when that P1 declares ``blocks_trading = TRUE``.
* **UNKNOWN** when any REQUIRED input cannot be read. UNKNOWN always overrides YES.
* **YES** only when every required input was read AND none of the NO conditions holds.
* Schedulers WARN does not block trading; a non-blocking P1 and a gate that does not block trading are
  drawn as open but not blocking (``non_blocking``).

Precedence NO > UNKNOWN > YES (I1, operator-binding 2026-11-11 23:19 ET, LQ-2172): a NO condition proven by a
READ input is a known fact even when another input is unreadable, so the verdict is NO and the unreadable input
is still listed in ``unknown_inputs``. An unreadable Portfolio/Orders/Data is UNKNOWN, not "!= OK -> NO" (I2).
Operator I1/I2 defaults: unreadable -> UNKNOWN; no source -> UNKNOWN + NEEDS BACKEND (``needs_backend``);
timeout -> TIMED_OUT; failed read -> UNKNOWN; missing data -> UNKNOWN. Missing is never healthy, and YES needs
every required input successfully evaluated.

D1 (operator-binding): the Orders row is OK = protection exists and is active; WARN = protection existed but is no
longer active (an expired DAY stop as the only protection after the close; never OK); GAP = confirmed
unprotected; UNKNOWN = cannot be determined. WARN and GAP are both "!= OK", so both give NO.

Inputs are ``HomeField@v1``-shaped (spec 1.1): ``state`` OK | WARN | GAP | STALE | UNKNOWN | TIMED_OUT, ``value``,
``as_of``, ``age_s``, ``threshold_s``, ``threshold_basis``, ``source_id``, ``lane_id``, ``cause``, ``owner``,
``reason``. A value with no parseable ``as_of`` is UNKNOWN (a missing source is never OK and never 0); a value
older than its threshold is STALE; ``age_s`` is recomputed at serve time.

Architecture (operator 2026-11-11: writer lanes first, endpoints only read):

* :func:`compute_verdict` is pure: readings + clock -> ``HomeStatus@v1`` payload. Exhaustively tested.
* ``scripts/home_status_verdict.py`` (the n8n lane ``home-status-verdict``) gathers the readings, computes, and
  writes one ``home_snapshots`` row ``kind='status'`` (system of record) plus a JSON mirror (fallback copy only).
* :func:`served_status` is the body of ``GET /api/v2/home/status``: it only READS the latest snapshot (DB first,
  the mirror only when the DB is unreachable) and turns a stale or missing snapshot into UNKNOWN with the
  last-known verdict and its age. It never computes a verdict on the request. YES is never served stale.

Read-only advisory surface: MBI_BEHAVIOR = 0. Nothing here sizes, orders, stops or reaches a broker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

SCHEMA = "HomeStatus@v1"
FIELD_SCHEMA = "HomeField@v1"
RULE_VERSION = "home-v010-d2r3-20261112"   # LQ-2411: D2-a..d class map + R3 from config
LANE_ID = "home-status-verdict"
SNAPSHOT_KIND = "status"
TABLE = "home_snapshots"
MIRROR_REL = "data/runtime/home_status_latest.json"
RECEIPT_REL = f"data/runtime/{LANE_ID}_last.json"
ET = ZoneInfo("America/New_York")

YES, NO, UNKNOWN = "YES", "NO", "UNKNOWN"
VERDICTS = (YES, NO, UNKNOWN)

# HomeField@v1 states (spec 1.1).
OK, WARN, GAP, STALE, TIMED_OUT = "OK", "WARN", "GAP", "STALE", "TIMED_OUT"
STATES = (OK, WARN, GAP, STALE, UNKNOWN, TIMED_OUT)   # GAP: Orders D1, confirmed unprotected
NEEDS_BACKEND = "NEEDS BACKEND"
UNREADABLE_STATES = (UNKNOWN, TIMED_OUT)

# Input names (spec 2144 table). Required inputs decide UNKNOWN; schedulers/alerts are informational only.
P0 = "p0"
P1_BLOCKING = "p1_blocking"
GATES = "gates"
PORTFOLIO = "portfolio"
ORDERS = "orders"
DATA = "data"
SCHEDULERS = "schedulers"
ALERTS = "alerts"
INCIDENT_CLASSES = "incident_classes"            # D2-b: every open incident classified by the approved map
REQUIRED_INPUTS = (P0, P1_BLOCKING, GATES, PORTFOLIO, ORDERS, DATA, INCIDENT_CLASSES)
COUNT_INPUTS = (P0, P1_BLOCKING, GATES)          # NO when a read list holds a blocking item
ROW_INPUTS = (PORTFOLIO, ORDERS, DATA)           # NO when read and state != OK
GUARD_INPUTS = (INCIDENT_CLASSES,)              # never NO by themselves: OK, or UNKNOWN when not proven
INFO_INPUTS = (SCHEDULERS, ALERTS)               # never change the verdict
ALL_INPUTS = REQUIRED_INPUTS + INFO_INPUTS
ROWS = (PORTFOLIO, ORDERS, DATA, ALERTS, SCHEDULERS)  # the System Status rows the page draws

# Fallback categories (design v010: categories, never incident names). An item may carry its own category from the
# LQ-2149 class map (e.g. "Unprotected Position"); otherwise these apply.
CATEGORY = {
    P0: "Open P0",
    P1_BLOCKING: "P1 Blocks Trading",
    GATES: "Open Validation Gate",
    PORTFOLIO: "Portfolio",
    ORDERS: "Orders",
    DATA: "Data Staleness",
    INCIDENT_CLASSES: "Unclassified Incident",
}
KIND = {P0: "p0", P1_BLOCKING: "p1", GATES: "gate", PORTFOLIO: "row", ORDERS: "row", DATA: "row",
        INCIDENT_CLASSES: "guard"}
GOTO = {
    P0: "#card-action",
    P1_BLOCKING: "#card-action",
    GATES: "#card-gates",
    PORTFOLIO: "#row-portfolio",
    ORDERS: "#row-orders",
    DATA: "#row-data",
    ALERTS: "#row-alerts",
    SCHEDULERS: "#row-schedulers",
    INCIDENT_CLASSES: "#card-action",
}

# R3 (operator 2026-11-12 08:40 ET; v6 addendum section 3): read from config/home_status_registry.json
# ``protection_verdict``, never hard-coded. A missing or invalid value is never YES and never a silent NO: the verdict
# is UNKNOWN with cause "config invalid" and a data-quality row.
POLICY_INPUT = "protection_verdict"
R3_KEY = "confirmed_no_overrides_unknown"


def r3_setting(policy: Any) -> Optional[bool]:
    """The R3 value from the ``protection_verdict`` block, or None when the block or value is missing/invalid."""
    if not isinstance(policy, Mapping):
        return None
    value = policy.get(R3_KEY)
    return value if isinstance(value, bool) else None

# Cadence windows; the lane's dispatch cron list mirrors them (a test pins the two together): every minute
# 09:00-15:59 ET on weekdays, every 5 minutes otherwise.
SESSION_CADENCE_S = 60
OFF_SESSION_CADENCE_S = 300
# Serve-time limit on the snapshot's age. In session 300 s (spec); off-hours 900 s = 3 cadences of 5 min (the spec's
# 1800 s assumed a 15-minute off-hours cadence; this lane runs every 5 minutes per the LQ, so the bound is tighter).
SESSION_SNAPSHOT_MAX_AGE_S = 300
OFF_SESSION_SNAPSHOT_MAX_AGE_S = 900
FUTURE_SKEW_S = 300


# ── clock helpers ───────────────────────────────────────────────────────────────────────────────


def to_utc(value: Any) -> Optional[datetime]:
    """An aware UTC datetime, or None. A naive datetime or an unparseable string is None (its zone is unknown)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def in_session_window(now: datetime) -> bool:
    et = now.astimezone(ET)
    return et.weekday() < 5 and 9 <= et.hour <= 15


def cadence_s(now: datetime) -> int:
    return SESSION_CADENCE_S if in_session_window(now) else OFF_SESSION_CADENCE_S


def snapshot_max_age_s(now: datetime) -> int:
    return SESSION_SNAPSHOT_MAX_AGE_S if in_session_window(now) else OFF_SESSION_SNAPSHOT_MAX_AGE_S


# ── the input contract ──────────────────────────────────────────────────────────────────────────


@dataclass
class Item:
    """One open thing behind a count input: an incident or a gate. Synthetic in tests."""

    id: str
    title: str
    blocks_trading: bool = False
    category: Optional[str] = None
    priority: Optional[str] = None
    source_id: Optional[str] = None
    owner: Optional[str] = None
    cause: Optional[str] = None
    first_seen_at: Optional[str] = None
    stale_condition: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "blocks_trading": bool(self.blocks_trading),
            "category": self.category,
            "priority": self.priority,
            "source_id": self.source_id,
            "owner": self.owner,
            "cause": self.cause,
            "first_seen_at": self.first_seen_at,
            "stale_condition": bool(self.stale_condition),
        }


@dataclass
class Reading:
    """One input as the lane read it (HomeField@v1 before grading).

    ``state`` is what the provider measured: OK, WARN (read, fresh, not OK), STALE, UNKNOWN or TIMED_OUT.
    :func:`field_of` re-applies the freshness rule from ``as_of``/``threshold_s`` so a provider cannot hand in an
    unproven OK. ``threshold_basis == "since_last_close"`` marks a session-aware OK (market closed, stamp at or after
    the last close: the latest data that can exist), which is not re-aged against ``threshold_s``.
    """

    name: str
    state: str
    value: Any = None
    as_of: Any = None
    threshold_s: Optional[float] = None
    threshold_basis: str = "fixed"
    source_id: Optional[str] = None
    lane_id: Optional[str] = None
    owner: Optional[str] = None
    cause: Optional[str] = None
    reason: Optional[str] = None
    items: list[Item] = field(default_factory=list)
    needs_backend: bool = False   # I2: the source this input needs does not exist yet (always with UNKNOWN)
    data_quality: list[dict[str, Any]] = field(default_factory=list)   # e.g. D2-c "override ignored"; never hidden


def unknown(name: str, reason: str, *, source_id: Optional[str] = None, lane_id: Optional[str] = None,
            owner: Optional[str] = None, cause: Optional[str] = None) -> Reading:
    return Reading(name=name, state=UNKNOWN, reason=reason, source_id=source_id, lane_id=lane_id, owner=owner,
                   cause=cause)


def no_source(name: str, reason: str, *, source_id: Optional[str] = None, lane_id: Optional[str] = None,
              owner: Optional[str] = None) -> Reading:
    """I2 "no source -> UNKNOWN + NEEDS BACKEND": the table, receipt or registry this input reads does not exist."""
    r = unknown(name, f"{NEEDS_BACKEND}: {reason}", source_id=source_id, lane_id=lane_id, owner=owner,
                cause=NEEDS_BACKEND)
    r.needs_backend = True
    return r


def field_of(reading: Reading, now: datetime) -> dict[str, Any]:
    """The HomeField@v1 for one reading at ``now``.

    * UNKNOWN / TIMED_OUT stay as they are.
    * A read value with no parseable ``as_of``, or no ``threshold_s``, cannot prove it is fresh -> UNKNOWN.
    * An ``as_of`` more than 5 min in the future is not trusted -> UNKNOWN.
    * A read value older than ``threshold_s`` -> STALE (unless the basis is ``since_last_close``).
    * Every non-OK field keeps ``cause``/``source_id``/``owner``; a missing owner is ``UNREGISTERED`` (visible).
    """
    state = reading.state if reading.state in STATES else UNKNOWN
    reason = reading.reason
    if reading.state not in STATES:
        reason = f"unknown reading state {reading.state!r}"
    at = to_utc(reading.as_of)
    age_s: Optional[float] = round((now - at).total_seconds(), 1) if at else None
    if state not in UNREADABLE_STATES:
        if at is None:
            state, reason = UNKNOWN, reason or "no as_of: freshness cannot be proven"
        elif reading.threshold_s is None:
            state, reason = UNKNOWN, reason or "no threshold: freshness cannot be judged"
        elif age_s is not None and age_s < -FUTURE_SKEW_S:
            state, reason = UNKNOWN, reason or "as_of is in the future"
        elif (reading.threshold_basis != "since_last_close" and age_s is not None
              and age_s > float(reading.threshold_s)):
            state = STALE
            reason = reason or f"age {age_s} s > threshold {reading.threshold_s} s"
    owner = reading.owner
    if state != OK and not owner:
        owner = "UNREGISTERED"
    return {
        "schema": FIELD_SCHEMA,
        "name": reading.name,
        "required": reading.name in REQUIRED_INPUTS,
        "state": state,
        "value": reading.value,
        "as_of": iso(at),
        "age_s": age_s,
        "threshold_s": reading.threshold_s,
        "threshold_basis": reading.threshold_basis,
        "source_id": reading.source_id,
        "lane_id": reading.lane_id,
        "cause": reading.cause,
        "owner": owner,
        "reason": reason,
        "needs_backend": bool(reading.needs_backend) and state in UNREADABLE_STATES,
        "goto": GOTO.get(reading.name),
        "items": [i.as_dict() for i in reading.items],
    }


# ── the rule ────────────────────────────────────────────────────────────────────────────────────


def _group_items(name: str, fld: Mapping[str, Any], items: list[Item]) -> list[dict[str, Any]]:
    """One blocker per category (the why sheet lists categories), each carrying its items and the oldest first_seen."""
    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.category or CATEGORY[name], []).append(item)
    out = []
    for category, its in groups.items():
        seen = sorted(i.first_seen_at for i in its if i.first_seen_at)
        owners = sorted({i.owner for i in its if i.owner})
        sources = sorted({i.source_id for i in its if i.source_id})
        out.append({
            "category": category,
            "kind": KIND[name],
            "input": name,
            "count": len(its),
            "cause": its[0].cause or its[0].title if len(its) == 1 else f"{len(its)} open",
            "source_id": ", ".join(sources) or fld.get("source_id"),
            "owner": ", ".join(owners) or fld.get("owner") or "UNREGISTERED",
            "goto": fld.get("goto"),
            "first_seen_at": seen[0] if seen else None,
            "items": [i.as_dict() for i in its],
        })
    return out


def _unknown_entry(name: str, fld: Mapping[str, Any]) -> dict[str, Any]:
    entry = {"input": name, "state": fld["state"], "reason": fld.get("reason") or fld["state"]}
    if fld.get("needs_backend"):
        entry["needs_backend"] = True
    return entry


def compute_verdict(readings: Iterable[Reading], now: datetime, *, run_id: Optional[str] = None,
                    policy: Any = None) -> dict[str, Any]:
    """Apply the approved rule. Pure: no I/O. ``now`` must be timezone-aware.

    A required input missing from ``readings`` counts as UNKNOWN (never as OK). ``policy`` is the registry's
    ``protection_verdict`` block: R3 true -> a NO from a good read overrides UNKNOWN (operator I1/R3); false ->
    UNKNOWN beats NO; missing or invalid -> UNKNOWN "config invalid" (never YES, never a silent NO).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    by_name: dict[str, Reading] = {}
    for r in readings:
        by_name[r.name] = r
    for name in REQUIRED_INPUTS:
        by_name.setdefault(name, unknown(name, "input not provided to the verdict lane"))
    fields = {name: field_of(r, now) for name, r in by_name.items()}

    blockers: list[dict[str, Any]] = []
    non_blocking: list[dict[str, Any]] = []
    unknown_inputs: list[dict[str, Any]] = []
    data_quality: list[dict[str, Any]] = []
    for name, r in by_name.items():
        for dq in r.data_quality:
            data_quality.append({"input": name, **dq})

    for name in REQUIRED_INPUTS:
        fld = fields[name]
        readable = fld["state"] in (OK, WARN)
        if name in GUARD_INPUTS:
            # D2-b: an input that can only prove "nothing unclassified"; anything but OK is UNKNOWN, never NO.
            if fld["state"] != OK:
                unknown_inputs.append(_unknown_entry(name, fld))
        elif name in COUNT_INPUTS:
            # A count list is only trusted when read AND fresh: a stale list cannot prove that nothing is open.
            if not readable:
                unknown_inputs.append(_unknown_entry(name, fld))
                continue
            items = by_name[name].items
            blocking = [i for i in items if name == P0 or i.blocks_trading]
            rest = [i for i in items if not (name == P0 or i.blocks_trading)]
            blockers.extend(_group_items(name, fld, blocking))
            for g in _group_items(name, fld, rest):
                g["category"] = ("P1 Data Integrity Alert" if name == P1_BLOCKING
                                 else "Open Validation Gate (does not block trading)") if g["category"] == CATEGORY[name] else g["category"]
                non_blocking.append(g)
            if fld["state"] == WARN and not blocking:
                # The provider reported a blocking condition without detail: never lose it.
                blockers.append({"category": CATEGORY[name], "kind": KIND[name], "input": name, "count": None,
                                 "cause": fld.get("reason") or "reported without detail", "source_id": fld.get("source_id"),
                                 "owner": fld.get("owner"), "goto": fld.get("goto"), "first_seen_at": None, "items": []})
        else:  # ROW_INPUTS
            if fld["state"] in UNREADABLE_STATES:
                unknown_inputs.append(_unknown_entry(name, fld))
            elif fld["state"] != OK:
                blockers.append({"category": CATEGORY[name], "kind": "row", "input": name, "row": name, "count": None,
                                 "cause": fld.get("cause") or fld.get("reason") or fld["state"].lower(),
                                 "reason": fld.get("reason"), "state": fld["state"],
                                 "source_id": fld.get("source_id"), "owner": fld.get("owner"), "goto": fld.get("goto"),
                                 "first_seen_at": None, "items": []})

    for name in INFO_INPUTS:
        if name in fields and fields[name]["state"] != OK:
            fld = fields[name]
            non_blocking.append({"category": name.capitalize(), "kind": "info", "input": name, "state": fld["state"],
                                 "count": fld.get("value") if isinstance(fld.get("value"), int) else None,
                                 "cause": fld.get("cause") or fld.get("reason") or fld["state"].lower(),
                                 "source_id": fld.get("source_id"), "owner": fld.get("owner"), "goto": fld.get("goto")})

    r3 = r3_setting(policy)
    if r3 is None:
        why = f"config invalid: {POLICY_INPUT}.{R3_KEY} missing or not a boolean (R3)"
        unknown_inputs.append({"input": POLICY_INPUT, "state": UNKNOWN, "reason": why})
        data_quality.append({"input": POLICY_INPUT, "cause": why, "source_id": "config/home_status_registry.json",
                             "owner": "operator"})
        verdict = UNKNOWN
    elif blockers and (r3 or not unknown_inputs):
        verdict = NO
    elif unknown_inputs:
        verdict = UNKNOWN
    else:
        verdict = YES
    # 2172: YES only when every required input was successfully evaluated. Restated as a guard so a future edit to
    # the branches above cannot serve YES over an input that was not read OK.
    if verdict == YES and (r3 is None or not all(fields[n]["state"] == OK
                                                 or (n in COUNT_INPUTS and fields[n]["state"] == WARN)
                                                 for n in REQUIRED_INPUTS)):
        verdict = UNKNOWN

    return {
        "schema": SCHEMA,
        "rule_version": RULE_VERSION,
        "verdict": verdict,
        "computed_at": iso(now),
        "run_id": run_id,
        "cadence_s": cadence_s(now),
        "snapshot_max_age_s": snapshot_max_age_s(now),
        "blockers": [{"n": i + 1, **b} for i, b in enumerate(blockers)],
        "unknown_inputs": unknown_inputs,
        "needs_backend": [n for n in ALL_INPUTS if n in fields and fields[n]["needs_backend"]],
        "non_blocking": non_blocking,
        "data_quality": data_quality,
        "protection_verdict": {R3_KEY: r3},
        "inputs": {n: fields[n] for n in REQUIRED_INPUTS},
        "rows": {n: fields[n] for n in ROWS if n in fields},
    }


# ── the served read (GET /api/v2/home/status) ──────────────────────────────────────────────────

SNAPSHOT_SQL = (
    "SELECT payload, computed_at, run_id FROM home_snapshots "
    "WHERE kind = 'status' ORDER BY computed_at DESC LIMIT 1"
)


def _load_mirror(path: Path) -> Optional[dict[str, Any]]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def latest_from_db(query: Callable[..., Any]) -> tuple[Optional[dict[str, Any]], bool]:
    """(latest status payload or None, db_readable). ``query`` follows api_v2 ``_db_query``: list, or None on failure."""
    rows = query(SNAPSHOT_SQL)
    if rows is None:
        return None, False
    if not rows:
        return None, True
    first = rows[0]
    doc = first.get("payload") if isinstance(first, Mapping) else first[0]
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except ValueError:
            return None, True
    return (doc if isinstance(doc, dict) else None), True


def _reage(fields: Any, now: datetime) -> Any:
    """Recompute every field's age_s at serve time (a snapshot never carries a frozen age)."""
    if not isinstance(fields, dict):
        return fields
    out = {}
    for k, f in fields.items():
        if isinstance(f, dict):
            at = to_utc(f.get("as_of"))
            f = {**f, "age_s": round((now - at).total_seconds(), 1) if at else None}
        out[k] = f
    return out


def served_status(*, query: Optional[Callable[..., Any]], mirror: Path, now: Optional[datetime] = None,
                  writer_last_ok_at: Optional[str] = None) -> dict[str, Any]:
    """The body of GET /api/v2/home/status. Reads only; never computes a verdict on the request.

    * DB first (system of record). The JSON mirror is read ONLY when the DB is unreachable, and ``read_from`` says so.
    * No snapshot -> UNKNOWN (``reason: no snapshot written``), empty lists, counts null — never YES.
    * A snapshot older than its own ``snapshot_max_age_s`` -> UNKNOWN with ``unknown_inputs`` naming
      ``verdict_snapshot`` and the last computed verdict and blockers under ``last_known``.
    * A payload with the wrong schema, rule version or verdict word -> UNKNOWN (``verdict_unreadable``).
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    doc: Optional[dict[str, Any]] = None
    db_readable = False
    if query is not None:
        doc, db_readable = latest_from_db(query)
    read_from = "db" if db_readable else None
    if not db_readable:
        doc = _load_mirror(mirror)
        read_from = "mirror" if doc else None

    base = {
        "schema": SCHEMA,
        "served_at": iso(now),
        "read_from": read_from,
        "db_readable": db_readable,
        "writer": {"lane_id": LANE_ID, "last_ok_at": writer_last_ok_at, "receipt": RECEIPT_REL},
    }
    empty = {"blockers": [], "unknown_inputs": [], "non_blocking": [], "inputs": {}, "rows": {}, "blocker_count": None}
    if not doc:
        reason = "no snapshot written" if db_readable else "verdict store unreachable and no mirror copy"
        return {**base, **empty, "state": UNKNOWN, "verdict": UNKNOWN, "reason": reason, "snapshot": None,
                "unknown_inputs": [{"input": "verdict_snapshot", "state": UNKNOWN, "reason": reason}], "last_known": None}
    computed_at = to_utc(doc.get("computed_at"))
    if (doc.get("schema") != SCHEMA or doc.get("verdict") not in VERDICTS or computed_at is None
            or doc.get("rule_version") != RULE_VERSION):
        reason = "verdict_unreadable: stored snapshot failed validation"
        return {**base, **empty, "state": UNKNOWN, "verdict": UNKNOWN, "reason": reason, "snapshot": None,
                "unknown_inputs": [{"input": "verdict_snapshot", "state": UNKNOWN, "reason": reason}], "last_known": None}
    age_s = round((now - computed_at).total_seconds(), 1)
    try:
        limit = float(doc.get("snapshot_max_age_s"))
    except (TypeError, ValueError):
        limit = float(SESSION_SNAPSHOT_MAX_AGE_S)
    # The serve-time limit is the stricter of the snapshot's own and the one for the current window.
    limit = min(limit, float(snapshot_max_age_s(now)))
    snapshot = {"computed_at": doc.get("computed_at"), "age_s": age_s, "threshold_s": limit, "run_id": doc.get("run_id")}
    inputs = _reage(doc.get("inputs"), now)
    rows = _reage(doc.get("rows"), now)
    if age_s > limit or age_s < -FUTURE_SKEW_S:
        reason = f"age {age_s} s > {limit:g} s" if age_s > limit else "snapshot computed_at is in the future"
        return {
            **base, **empty,
            "state": STALE, "verdict": UNKNOWN, "reason": f"verdict snapshot stale: {reason}", "snapshot": snapshot,
            "unknown_inputs": [{"input": "verdict_snapshot", "state": STALE, "reason": reason}],
            "last_known": {"verdict": doc.get("verdict"), "computed_at": doc.get("computed_at"), "age_s": age_s,
                           "blockers": doc.get("blockers") or [], "unknown_inputs": doc.get("unknown_inputs") or [],
                           "non_blocking": doc.get("non_blocking") or []},
            "inputs": inputs, "rows": rows,
        }
    return {
        **base,
        "state": OK,
        "verdict": doc["verdict"],
        "rule_version": doc.get("rule_version"),
        "reason": None,
        "snapshot": snapshot,
        "blockers": doc.get("blockers") or [],
        "blocker_count": len(doc.get("blockers") or []),
        "unknown_inputs": doc.get("unknown_inputs") or [],
        "non_blocking": doc.get("non_blocking") or [],
        "inputs": inputs,
        "rows": rows,
        "last_known": None,
    }


def mirror_path(state_root: Path) -> Path:
    return Path(state_root) / MIRROR_REL


def api_handler(query: Optional[Callable[..., Any]], *, state_root: Optional[Path] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """GET /api/v2/home/status in one call (the api_v2 route delegates here; see docs/patches/home_status_route_20261112.md).

    Resolves the mirror and the writer receipt through the same ``lane_last_receipt.runtime_dir`` the lane writes with,
    so the reader and the writer cannot point at different directories.
    """
    try:
        from scripts.lib.lane_last_receipt import runtime_dir
    except ImportError:  # api_v2 puts scripts/ itself on sys.path
        from lib.lane_last_receipt import runtime_dir  # type: ignore[no-redef] -- same function, alternate import root under api_v2
    rt = Path(runtime_dir(state_root))
    last_ok = None
    try:
        rec = json.loads((rt / Path(RECEIPT_REL).name).read_text(encoding="utf-8"))
        last_ok = rec.get("ok_at") if isinstance(rec, dict) else None
    except (OSError, ValueError):
        last_ok = None
    return served_status(query=query, mirror=rt / Path(MIRROR_REL).name, now=now, writer_last_ok_at=last_ok)

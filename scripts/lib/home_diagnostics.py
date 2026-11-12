"""Home Diagnostics: the Cause/Source/Owner + threshold registry, its loader, and the pure status computation
(LQ-20261107-2149 / 2150, design/pages/home/v010).

Three layers, kept apart on purpose:

* ``load_registry`` -- ``config/home_diagnostics_registry.json`` validated; a malformed registry raises, it is never
  half-loaded (a registry that silently lost a widget would print a shorter, greener drawer).
* ``evaluate`` -- PURE: (widget, probe fact, now) -> a row. No clock, no I/O. Status is computed, never declared:
  OK | STALE | UNKNOWN | TIMED OUT | OFF_SESSION. UNKNOWN is never OK; a missing source is UNKNOWN, not 0.
* ``build_snapshot`` / ``serve`` -- the collector (n8n lane) writes the snapshot; the endpoint only READS it. A snapshot
  older than ``max_snapshot_age_s`` grades every row UNKNOWN ("collector stale") and keeps the last good values.

Probes are read-only: ``db_max`` (newest timestamp in a table), ``db_live`` (the table answers; optional newest event
time as detail), ``none`` (no production source). Table/column names come from the registry file, which is validated
against an identifier pattern before any SQL is built.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_CONFIG = Path(__file__).resolve().parents[2] / "config"
REGISTRY_PATH = _CONFIG / "home_status_registry.json"
THRESHOLDS_PATH = _CONFIG / "home_thresholds.json"
LANE_REGISTRY_PATH = _CONFIG / "lane_registry.json"
SNAPSHOT_NAME = "home_diagnostics_latest.json"
SCHEMA = "HomeDiagnostics@v1"
STATES = ("OK", "WARN", "STALE", "UNKNOWN", "TIMED_OUT")  # HomeField@v1 vocabulary (spec §1.1)
SESSIONS = ("rth", "extended", "closed")
PROBE_KINDS = ("db_max", "db_live", "none")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_WHERE = re.compile(r"^[a-z_][a-z0-9_]* = '[A-Za-z0-9_.$ -]+'$")


class RegistryError(ValueError):
    pass


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise RegistryError(msg)


PRIORITIES = ("P0", "P1", "INFO")


def validate_incident_registry(doc: Mapping[str, Any]) -> None:
    """The incident-class map that 2147 (alerts read), 2144 (trade-ready) and 2145 (coverage) consume."""
    owners = doc.get("owners") or {}
    classes = doc.get("incident_classes")
    _need(isinstance(classes, Mapping) and bool(classes), "incident_classes is required")
    _need(isinstance(doc.get("incident_classes_approved"), bool), "incident_classes_approved must be a boolean (D2 is an operator decision)")
    for key, c in classes.items():
        _need(bool(c.get("category")), f"incident class {key}: category is required")
        _need(c.get("priority") in PRIORITIES, f"incident class {key}: priority {c.get('priority')!r} not in {PRIORITIES}")
        _need(isinstance(c.get("blocks_trading_default"), bool), f"incident class {key}: blocks_trading_default must be a boolean")
        _need(c.get("owner") in owners, f"incident class {key}: owner {c.get('owner')!r} not in owners")
        _need(isinstance(c.get("home_visible"), bool), f"incident class {key}: home_visible must be a boolean")
        for k in ("ttl_h", "proof_window_h"):
            _need(c.get(k) is None or (isinstance(c[k], (int, float)) and c[k] > 0), f"incident class {key}: {k} must be null or positive")
        _need(not (c["blocks_trading_default"] and c["priority"] == "INFO"), f"incident class {key}: an INFO class cannot block trading")
    rs = doc.get("requires_stop") or {}
    _need(isinstance(rs.get("asset_types"), list) and bool(rs["asset_types"]), "requires_stop.asset_types is required")
    _need(isinstance(doc.get("stop_exempt_accounts"), list), "stop_exempt_accounts must be a list")


def validate_registry(doc: Mapping[str, Any]) -> dict[str, Any]:
    _need(doc.get("schema") == "HomeStatusRegistry@v1", "schema must be HomeStatusRegistry@v1")
    causes, owners = doc.get("causes") or {}, doc.get("owners") or {}
    _need(bool(causes) and bool(owners), "causes and owners are required")
    validate_incident_registry(doc)
    sources: dict[str, Any] = {}
    for s in doc.get("sources") or []:
        sid = s.get("source_id")
        _need(bool(sid) and sid not in sources, f"duplicate or empty source_id {sid!r}")
        _need(s.get("owner") in owners, f"source {sid}: owner {s.get('owner')!r} not in owners")
        _need(s.get("cause_category") in causes, f"source {sid}: cause_category {s.get('cause_category')!r} not in causes")
        probe = s.get("probe") or {}
        _need(probe.get("kind") in PROBE_KINDS, f"source {sid}: probe.kind {probe.get('kind')!r} not in {PROBE_KINDS}")
        if probe["kind"] in ("db_max", "db_live"):
            _need(bool(_IDENT.match(str(probe.get("table", "")))), f"source {sid}: bad probe.table")
            col = probe.get("column") or probe.get("last_event_column")
            _need(bool(_IDENT.match(str(col or ""))), f"source {sid}: bad probe column")
            if probe.get("where"):
                _need(bool(_WHERE.match(probe["where"])), f"source {sid}: probe.where must be `col = 'literal'`")
        else:
            _need(bool(probe.get("reason")), f"source {sid}: a none probe must say why (reason)")
        sources[sid] = s
    widgets, seen = [], set()
    for w in doc.get("widgets") or []:
        wid = w.get("widget_id")
        _need(bool(wid) and wid not in seen, f"duplicate or empty widget_id {wid!r}")
        seen.add(wid)
        _need(w.get("source_id") in sources, f"widget {wid}: unknown source_id {w.get('source_id')!r}")
        for key in ("widget", "refresh_rate", "failure_mode"):
            _need(bool(w.get(key)), f"widget {wid}: {key} is required")
        _need(isinstance(w.get("needs_backend"), bool), f"widget {wid}: needs_backend must be a boolean")
        covered: set[str] = set()
        for r in w.get("rules") or []:
            for sess in r.get("sessions") or []:
                _need(sess in SESSIONS, f"widget {wid}: unknown session {sess!r}")
                _need(sess not in covered, f"widget {wid}: session {sess} has two rules")
                covered.add(sess)
            if r.get("expected") is False:
                _need(bool(r.get("note")), f"widget {wid}: an expected:false rule must say why (note)")
                _need(r.get("off_session_state", "OK") in ("OK", "WARN"), f"widget {wid}: off_session_state must be OK or WARN")
            else:
                t = r.get("threshold_s")
                _need(t is None or (isinstance(t, int) and t > 0), f"widget {wid}: threshold_s must be null or a positive int")
        _need(covered == set(SESSIONS), f"widget {wid}: rules must cover every session {SESSIONS}, have {sorted(covered)}")
        if sources[w["source_id"]]["probe"]["kind"] == "none":
            _need(w["needs_backend"], f"widget {wid}: a widget on a none-probe source must carry needs_backend")
        widgets.append(w)
    _need(len(widgets) == 13, f"the Home v010 drawer lists 13 widgets, registry has {len(widgets)}")
    _need(int(doc.get("max_snapshot_age_s", 0)) > 0 and int(doc.get("probe_timeout_s", 0)) > 0, "limits required")
    return {**doc, "_sources": sources, "widgets": widgets}


def _lane_owners(path: Path) -> dict[str, str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get("lanes") or doc.get("rows") or []
    return {r["lane_id"]: r.get("owner") for r in rows if isinstance(r, dict) and r.get("lane_id")}


def load_registry(path: Path | str | None = None, thresholds_path: Path | str | None = None,
                  lane_registry_path: Path | str | None = None) -> dict[str, Any]:
    """Merge config/home_status_registry.json (source -> owner -> cause) with config/home_thresholds.json (widgets).

    Owners of lane-backed sources come from config/lane_registry.json (an explicit owner must agree); thresholds that name an
    authority_domain come from config/data_source_authority.json through lib.session_freshness.authority_thresholds. A lane or
    a domain that does not exist is a RegistryError, so a typo cannot silently become a missing threshold."""
    status = json.loads(Path(path or REGISTRY_PATH).read_text(encoding="utf-8"))
    thr = json.loads(Path(thresholds_path or THRESHOLDS_PATH).read_text(encoding="utf-8"))
    _need(thr.get("schema") == "HomeThresholds@v1", "thresholds schema must be HomeThresholds@v1")
    lanes = _lane_owners(Path(lane_registry_path or LANE_REGISTRY_PATH))
    sources = []
    for src in status.get("sources") or []:
        src = dict(src)
        lane = src.get("owner_lane")
        if lane:
            _need(lane in lanes, f"source {src.get('source_id')}: owner_lane {lane!r} is not a lane in lane_registry.json")
            if src.get("owner") is not None:
                _need(src["owner"] == lanes[lane], f"source {src.get('source_id')}: owner {src['owner']!r} disagrees with lane_registry owner {lanes[lane]!r}")
            src["owner"] = lanes[lane]
        sources.append(src)
    from lib import session_freshness as sf  # noqa: PLC0415

    widgets = []
    for w in thr.get("widgets") or []:
        w = dict(w)
        rules = []
        for r in w.get("rules") or []:
            r = dict(r)
            dom = r.pop("authority_domain", None)
            if dom:
                got = sf.authority_thresholds(dom)
                _need(got is not None, f"widget {w.get('widget_id')}: authority domain {dom!r} not in data_source_authority.json")
                basis = r.pop("basis", "open")
                _need(basis in ("open", "closed"), f"widget {w.get('widget_id')}: basis must be open or closed")
                hours = got.get("closed_h" if basis == "closed" else "open_h")
                _need(hours is not None, f"widget {w.get('widget_id')}: domain {dom!r} has no {basis} threshold")
                r["threshold_s"] = int(round(hours * 3600))
                r["threshold_basis"] = f"data_source_authority:{dom}.{basis}"
            rules.append(r)
        w["rules"] = rules
        widgets.append(w)
    merged = {**status, "sources": sources, "widgets": widgets,
              "max_snapshot_age_s": thr.get("max_snapshot_age_s"), "probe_timeout_s": thr.get("probe_timeout_s")}
    return validate_registry(merged)


def session_of(now: datetime) -> str:
    """rth | extended | closed, for an instant. NYSE calendar (holidays, early closes) via cio_market_session."""
    from lib import cio_market_session as ms  # noqa: PLC0415 -- scripts/ is on sys.path in every caller

    et = now.astimezone(ET)
    if not ms.is_trading_day(et):
        return "closed"
    if ms.is_rth(et):
        return "rth"
    t = et.time()
    if time(4, 0) <= t < time(9, 30) or time(16, 0) <= t < time(20, 0):
        return "extended"
    return "closed"


def _rule(widget: Mapping[str, Any], session: str) -> Mapping[str, Any]:
    for r in widget["rules"]:
        if session in r["sessions"]:
            return r
    raise RegistryError(f"widget {widget['widget_id']}: no rule for session {session}")


def _fmt_age(s: Optional[float]) -> Optional[str]:
    if s is None:
        return None
    s = int(max(0, s))
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{round(s / 60)} m"
    h, m = divmod(round(s / 60), 60)
    return f"{h} h {m} m" if m else f"{h} h"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def evaluate(widget: Mapping[str, Any], source: Mapping[str, Any], fact: Mapping[str, Any], now: datetime,
             owners: Mapping[str, str], causes: Mapping[str, str]) -> dict[str, Any]:
    """One diagnostics row from one probe fact. PURE.

    ``fact`` = {"read": ok|none|error|timeout, "as_of": iso|None, "last_event_at": iso|None, "error": str|None,
    "last_good_at": iso|None}. Age is measured from ``as_of`` to ``now``; an as_of in the future is UNKNOWN (a clock
    that disagrees is not a fresh value).
    """
    session = session_of(now)
    rule = _rule(widget, session)
    read = fact.get("read")
    as_of = _parse(fact.get("as_of"))
    age_s = None if as_of is None else (now - as_of).total_seconds()
    threshold = None if rule.get("expected") is False else rule.get("threshold_s")
    status, cause, why = "UNKNOWN", source["cause_category"], None
    off_session, session_note = False, None

    if read == "none":
        cause, why = "NO_SOURCE", fact.get("error") or source["probe"].get("reason")
    elif read == "timeout":
        status, cause, why = "TIMED_OUT", "READ_TIMEOUT", fact.get("error") or "no answer within the probe timeout"
    elif read == "error":
        cause, why = "READ_FAILURE", fact.get("error") or "the read failed"
    elif read == "ok":
        if as_of is None and source["probe"]["kind"] == "db_max":
            cause, why = "NO_SOURCE", "the source answered but holds no value"
        elif age_s is not None and age_s < -60:
            cause, why = "READ_FAILURE", "the source timestamp is in the future (clock disagreement)"
        elif rule.get("expected") is False:
            # One vocabulary: a source that is not expected to print outside its session is OK, with the basis named.
            # D1 (operator 11-11): where the rule says off_session_state WARN (Orders: an expired DAY stop is no longer
            # active protection) the row is WARN with a cause, never OK.
            status, off_session, session_note = rule.get("off_session_state", "OK"), True, rule["note"]
            if status == "WARN":
                cause, why = "SESSION_CLOSED", rule["note"]
        elif threshold is None:
            status, why = "OK", "event-driven source: status is whether the read worked"
        elif age_s is not None and age_s > threshold:
            status, why = "STALE", f"age {_fmt_age(age_s)} exceeds {_fmt_age(threshold)}"
        else:
            status = "OK"
    else:
        why = f"unrecognised probe result {read!r}"
    ok = status == "OK"
    # An off-session row has no limit today; the drawer still shows the limit that applies in session.
    in_session = None
    if rule.get("expected") is False:
        in_session = next((r.get("threshold_s") for r in widget["rules"] if r.get("expected") is not False and r.get("threshold_s")), None)
    # An event-driven source has no age limit; the drawer shows how long since its newest event instead of "0 s".
    shown_age = age_s
    ev = _parse(fact.get("last_event_at"))
    if ev is not None and threshold is None and read == "ok":
        shown_age = (now - ev).total_seconds()
    return {
        "widget_id": widget["widget_id"],
        "widget": widget["widget"],
        "source": source["label"],
        "source_id": source["source_id"],
        "owner": owners.get(source["owner"], source["owner"]),
        "owner_key": source["owner"],
        "owner_lane": source.get("owner_lane"),
        "refresh_rate": widget["refresh_rate"],
        "age_s": None if shown_age is None else int(max(0, shown_age)),
        "age": _fmt_age(shown_age),
        "as_of": _iso(as_of),
        "threshold_s": threshold,
        "threshold": _fmt_age(threshold) if threshold else None,
        "threshold_basis": "session_closed" if off_session else (rule.get("threshold_basis") or ("fixed" if threshold else None)),
        "off_session": off_session,
        "session_note": session_note,
        "read": read,
        "in_session_threshold": _fmt_age(in_session) if in_session else None,
        "session": session,
        "state": status,
        "cause": None if ok else causes.get(cause, cause),
        "cause_category": None if ok else cause,
        "why": None if ok else why,
        "failure_mode": widget["failure_mode"],
        "needs_backend": bool(widget["needs_backend"]),
        "needs_backend_note": widget.get("needs_backend_note"),
        "last_event_at": fact.get("last_event_at"),
        "last_good_at": fact.get("last_good_at") or (_iso(as_of) if ok else None),
    }


# ---- collector side (reads the database, read-only) -------------------------------------------------

def probe_source(source: Mapping[str, Any], query: Callable[[str], Any], timeout_s: float = 30.0) -> dict[str, Any]:
    """Run one source's probe. ``query(sql)`` returns a list of rows or raises; TimeoutError means timed out.
    Never raises: a failure is a fact the row grades, not an exception that hides the other twelve."""
    probe = source["probe"]
    if probe["kind"] == "none":
        return {"read": "none", "error": probe.get("reason")}
    table, where = probe["table"], probe.get("where")
    clause = f" WHERE {where}" if where else ""
    try:
        if probe["kind"] == "db_max":
            rows = query(f"SELECT max({probe['column']}) FROM {table}{clause}")
            ts = rows[0][0] if rows else None
            return {"read": "ok", "as_of": _iso(ts) if isinstance(ts, datetime) else None}
        col = probe.get("last_event_column")
        rows = query(f"SELECT max({col}) FROM {table}{clause}")
        ts = rows[0][0] if rows else None
        return {"read": "ok", "as_of": None, "last_event_at": _iso(ts) if isinstance(ts, datetime) else None}
    except TimeoutError as exc:
        return {"read": "timeout", "error": f"{type(exc).__name__}: {exc}"[:200]}
    except Exception as exc:  # noqa: BLE001 -- named in the row, never swallowed
        msg = str(exc).strip().splitlines()[0][:160] if str(exc).strip() else ""
        return {"read": "error", "error": f"{type(exc).__name__}: {msg}"}


def build_snapshot(registry: Mapping[str, Any], query: Callable[[str], Any], now: datetime,
                   previous: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Probe every distinct source once, then grade every widget. ``previous`` supplies last_good_at on failure."""
    facts: dict[str, dict[str, Any]] = {}
    for sid, src in registry["_sources"].items():
        facts[sid] = probe_source(src, query, float(registry["probe_timeout_s"]))
    prev_rows = {r.get("widget_id"): r for r in ((previous or {}).get("rows") or [])}
    rows = []
    for w in registry["widgets"]:
        fact = dict(facts[w["source_id"]])
        if fact.get("read") != "ok":
            fact["last_good_at"] = (prev_rows.get(w["widget_id"]) or {}).get("last_good_at")
        # db_live sources are "fresh as of this read"
        if fact.get("read") == "ok" and registry["_sources"][w["source_id"]]["probe"]["kind"] == "db_live":
            fact["as_of"] = _iso(now)
        rows.append(evaluate(w, registry["_sources"][w["source_id"]], fact, now, registry["owners"], registry["causes"]))
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    return {"schema": SCHEMA, "generated_at": _iso(now), "registry_version": registry.get("version"),
            "session": session_of(now), "counts": counts, "rows": rows}


# ---- read side (the endpoint) -----------------------------------------------------------------------

def regrade(rows: list, registry: Mapping[str, Any], now: datetime) -> list:
    """Re-grade a snapshot's rows at serve time. A row's age and OK/STALE come from its ``as_of`` and the limit that
    applies at ``now`` (session included), never from collect time: a source read 800 s old at collection is 1650 s
    old 850 s later and must not still read OK. Rows the collector could not read (no source, read failure, timed
    out) stay as written, because nothing new has been read.
    """
    widgets = {w["widget_id"]: w for w in registry["widgets"]}
    out = []
    for r in rows:
        w = widgets.get(r.get("widget_id"))
        if w is None or r.get("read") != "ok":
            out.append(dict(r))
            continue
        fact = {"read": "ok", "as_of": r.get("as_of"), "last_event_at": r.get("last_event_at"),
                "last_good_at": r.get("last_good_at")}
        row = evaluate(w, registry["_sources"][w["source_id"]], fact, now, registry["owners"], registry["causes"])
        row["regraded_at"] = _iso(now)
        out.append(row)
    return out


def serve(snapshot: Optional[Mapping[str, Any]], registry: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """What GET /api/v2/home/diagnostics returns. Reads a snapshot; never probes, never writes.

    No snapshot, an unreadable one, or one older than max_snapshot_age_s => all 13 rows UNKNOWN ("collector stale" /
    "no snapshot"), last good values kept. The endpoint can never print OK on evidence nobody gathered recently."""
    limit = int(registry["max_snapshot_age_s"])
    gen = _parse((snapshot or {}).get("generated_at")) if isinstance(snapshot, Mapping) else None
    good = isinstance(snapshot, Mapping) and snapshot.get("schema") == SCHEMA and gen is not None \
        and isinstance(snapshot.get("rows"), list)
    age = None if gen is None else (now - gen).total_seconds()
    if good and age is not None and -60 <= age <= limit:
        rows = regrade(snapshot["rows"], registry, now)
        return {**snapshot, "state": "OK", "reason": None, "rows": rows, "served_at": _iso(now),
                "counts": {s: sum(1 for r in rows if r["state"] == s) for s in STATES},
                "snapshot_age_s": int(max(0, age)), "max_snapshot_age_s": limit, "as_of_now": _iso(now)}
    prev = {r.get("widget_id"): r for r in ((snapshot or {}).get("rows") or [])} if good else {}
    reason = "no snapshot has been written" if not isinstance(snapshot, Mapping) or not snapshot else (
        "the snapshot is unreadable or has the wrong schema" if not good else
        f"the snapshot is {_fmt_age(age)} old (limit {_fmt_age(limit)})")
    rows = []
    for w in registry["widgets"]:
        src = registry["_sources"][w["source_id"]]
        row = evaluate(w, src, {"read": "error", "error": f"collector stale: {reason}",
                                "last_good_at": (prev.get(w["widget_id"]) or {}).get("last_good_at")}, now,
                       registry["owners"], registry["causes"])
        row["cause_category"], row["cause"] = "COLLECTOR_STALE", registry["causes"]["COLLECTOR_STALE"]
        row["age"] = row["age_s"] = None
        rows.append(row)
    return {"schema": SCHEMA, "state": "STALE" if good else "UNKNOWN",
            "detail": "collector_stale" if good else "no_snapshot", "reason": reason, "served_at": _iso(now),
            "generated_at": (snapshot or {}).get("generated_at") if good else None, "snapshot_age_s": None if age is None else int(age),
            "max_snapshot_age_s": limit, "registry_version": registry.get("version"), "session": session_of(now),
            "counts": {s: sum(1 for r in rows if r["state"] == s) for s in STATES}, "rows": rows,
            "as_of_now": _iso(now)}

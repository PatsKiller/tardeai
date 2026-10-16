"""n8n lane self-healing: the deterministic tier, failure signatures and the live-heal gate (pure; no I/O).

Operator 2026-10-16 ("yes make self healing now"). Measured that day: 612 diagnosis events, 12 diagnosed, 0
remediation runs, 695 open escalations. The diagnoser (scripts/n8n_failure_diagnosis.py) spent its model budget
on the same failure over and over (the 3-per-lane-per-day cap counted retries of ONE failure), sent known
deterministic patterns to the model, and had no action that could heal a live lane. This module holds the rules;
the CLI applies them before the model path:

1. ``signature`` — lane + event_type + normalized error tail (numbers, timestamps, ids and hex collapsed). One
   diagnosis per signature per day; every other incident with that signature is ATTACHED to it, and its escalation
   is collapsed into the signature's one escalation.
2. ``deterministic_verdict`` — no model call:
   * RUN_SKIPPED_LOCK / flock_held while another run of the lane finished RUN_DONE in the same slot -> auto-close
     ``covered``;
   * RUN_TIMEOUT executor_lost (or an overdue RUNNING orphan) -> the existing ``reap_orphan_run`` handler;
   * a failure followed by a later successful run of the same lane (same mode when the failure names one; for a
     NO_OUTPUT finding a LIVE run, or one whose output signal advanced) -> auto-close ``self_recovered``.
3. ``classify_failure`` — transient (timeout, connection reset/closed by the server, dependency_unavailable,
   HTTP 5xx) vs code error (a Python exception class that is a bug, including psycopg2 InterfaceError: using a
   closed connection object is a code path, not a network blip) vs unknown.
4. ``live_heal_gate`` — ``rerun_live_once`` is allowed only when ALL hold: effect owner n8n, stage canary or
   cutover, not a sender / P1 / F09-broker-order-stop-options lane, a transient failure, and the lane has a
   semantic effect key (config/n8n_effect_keys.json) so the executor's effect-claim gate stands between the rerun
   and a duplicate effect (fail closed). At most one per lane per day; through ``host_run_request`` only.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0: nothing here sizes, orders, stops, sends or touches a broker.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "N8nSelfHeal@v1"
LIVE_HEAL_ACTION = "rerun_live_once"
LIVE_HEAL_MAX_PER_LANE_DAY = 1
LIVE_HEAL_STAGES = frozenset({"canary", "cutover"})
#: Families and words that never get an automatic live rerun (AGENTS.md §0/§22: broker, order, stop, options
#: execution; F09 is the broker/execution family). Matched on the lane id and the registry dispatch class.
NEVER_LIVE_FAMILIES = frozenset({"F09"})
NEVER_LIVE_WORDS = ("broker", "order", "stop", "options-exec", "options_exec", "option-exec", "execution", "scalp-live",
                    "schwab", "alpaca", "moomoo", "fidelity", "snaptrade", "trade-exec", "fill", "scalp")
SENDER_WORDS = ("send", "telegram", "notify", "notifier", "email", "digest-send", "alert-send", "sms")
SENDER_CLASSES = frozenset({"sender", "send", "notify", "alert"})
#: Registry dispatch priority at or below this is a P1 lane when no lane_cutover_policy.json says otherwise.
P1_DISPATCH_PRIORITY_MAX = 1
SLOT_WINDOW_S = 600              # "the same slot": two runs of a lane requested within 10 minutes
AUTO_CLOSE_OUTCOMES = ("covered", "self_recovered")

TRANSIENT = "transient"
CODE_ERROR = "code_error"
UNKNOWN = "unknown"

_TRANSIENT_RES = tuple(re.compile(p, re.I) for p in (
    r"\btimed?[ _-]?out\b", r"\btimeout\b", r"\bRUN_TIMEOUT\b", r"\bdeadline exceeded\b",
    r"\bconnection (?:reset|refused|aborted)\b", r"\bECONNRESET\b", r"\bECONNREFUSED\b", r"\bbroken pipe\b",
    r"\bserver closed the connection\b", r"\bconnection (?:was )?closed by (?:the )?(?:server|peer|remote)\b",
    r"\bremote end closed connection\b", r"\bterminating connection due to idle", r"\bcould not connect to server\b",
    r"\bdependency_unavailable\b", r"\btemporar(?:il)?y unavailable\b", r"\bservice unavailable\b",
    r"\b(?:HTTP|status|status_code|code)[ :=/]*5\d\d\b", r"\b50[234] (?:Bad Gateway|Service Unavailable|Gateway Time-?out)\b",
    r"\bOperationalError\b.*\b(?:connection|timeout|server)\b", r"\bReadTimeout\b", r"\bConnectTimeout\b",
    r"\bRemoteDisconnected\b", r"\btoo many connections\b",
))
#: A Python exception that is a bug in the lane, not the environment. psycopg2 InterfaceError ("connection already
#: closed") is the lane using a connection object it should have re-opened: a code fix (daily-incubator-refresh,
#: 2026-10-16), so it is a code error even though the text says "connection".
_CODE_ERROR_RES = tuple(re.compile(p) for p in (
    r"\b(?:TypeError|AttributeError|NameError|KeyError|IndexError|SyntaxError|IndentationError|ImportError|"
    r"ModuleNotFoundError|ZeroDivisionError|AssertionError|UnboundLocalError|NotImplementedError|"
    r"RecursionError|JSONDecodeError|UnicodeDecodeError|UnicodeEncodeError)\b",
    r"\bInterfaceError\b", r"\b(?:ProgrammingError|UndefinedColumn|UndefinedTable|DataError|IntegrityError)\b",
    r"\bValueError\b", r"\busage: ", r"\bunrecognized arguments\b", r"\bNo such file or directory\b.*\.py\b",
))

_NORMALIZERS = (
    (re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:[+-]\d\d:?\d\d|Z)?"), "<ts>"),
    (re.compile(r"\b\d{8}T\d{4}\b"), "<slot>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{10,}\b", re.I), "<hex>"),
    (re.compile(r"\b(?:siem|run|rem|d|e|g|p)[:-][A-Za-z0-9._:-]{6,}"), "<id>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
)
SIGNATURE_TAIL_CHARS = 240


def normalize_error(text: Any) -> str:
    out = str(text or "")
    for rx, rep in _NORMALIZERS:
        out = rx.sub(rep, out)
    return out.strip().lower()[-SIGNATURE_TAIL_CHARS:]


def signature(lane: str, event_type: Any, error_text: Any) -> str:
    """Stable id of one failure KIND on one lane. The lane prefix the SIEM bridge puts on its error is dropped."""
    err = str(error_text or "")
    if err.startswith(f"{lane}:"):
        err = err[len(lane) + 1:]
    raw = f"{lane}|{str(event_type or '').upper()}|{normalize_error(err)}"
    return "sig-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def classify_failure(text: Any, *, event_type: Any = None, run_reason: Any = None) -> str:
    """transient | code_error | unknown. A code error wins over a transient word in the same text."""
    blob = " ".join(str(x or "") for x in (event_type, run_reason, text))
    if any(rx.search(blob) for rx in _CODE_ERROR_RES):
        return CODE_ERROR
    if str(event_type or "").upper() == "RUN_TIMEOUT" or any(rx.search(blob) for rx in _TRANSIENT_RES):
        return TRANSIENT
    return UNKNOWN


# ---------------------------------------------------------------- deterministic tier


def _ts(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def _receipt(run: Mapping[str, Any]) -> dict[str, Any]:
    try:
        rec = json.loads(run.get("receipt_json") or "") or {}
    except (TypeError, ValueError):
        rec = {}
    return rec if isinstance(rec, dict) else {}


_MODE_RE = re.compile(r"\bmode=(dry_run|live)\b")
_KEY_MODE_RE = re.compile(r"^[deg]:[^:]+:(dry_run|live):")


def failure_mode(fields: Mapping[str, Any], error_text: Any) -> Optional[str]:
    m = _MODE_RE.search(str(error_text or ""))
    if m:
        return m.group(1)
    m = _KEY_MODE_RE.match(str(fields.get("run") or ""))
    return m.group(1) if m else None


def _ok_done(run: Mapping[str, Any]) -> bool:
    if run.get("state") != "RUN_DONE":
        return False
    ec = run.get("exit_code")
    return ec in (None, 0, "0")


def _signal_advanced(run: Mapping[str, Any]) -> bool:
    rec = _receipt(run)
    a, b = rec.get("output_signal_mtime_after"), rec.get("output_signal_mtime_before")
    try:
        return a is not None and (b is None or float(a) > float(b))
    except (TypeError, ValueError):
        return False


def _is_lock_skip(event_type: str, error_text: str, run_reason: Any) -> bool:
    blob = f"{error_text} {run_reason or ''}".lower()
    return event_type == "RUN_SKIPPED_LOCK" or "flock_held" in blob or "lock_skipped" in blob


def deterministic_verdict(row: Mapping[str, Any], *, fields: Mapping[str, Any], runs: Iterable[Mapping[str, Any]],
                          now: float) -> Optional[dict[str, Any]]:
    """{kind: auto_close|reap, outcome, evidence, cause} or None (the model path decides).

    ``row`` is the SIEM row, ``fields`` its parsed message (lane, run, error, at), ``runs`` the lane's recent
    ledger rows (newest first)."""
    runs = list(runs)
    et = str(row.get("event_type") or "").upper()
    err = str(fields.get("error") or row.get("message") or "")
    failed_run_id = fields.get("run")
    failed = next((r for r in runs if r.get("run_id") == failed_run_id), None) if failed_run_id else None
    reason = (_receipt(failed).get("reason") if failed else None) or ""
    t_fail = (_ts((failed or {}).get("finished_at")) or _ts((failed or {}).get("requested_at"))
              or _ts(fields.get("at")) or _ts(row.get("created_at")))
    # 1. lock skip covered by another holder in the same slot
    if _is_lock_skip(et, err, reason) or (failed and failed.get("state") == "RUN_SKIPPED_LOCK"):
        t_req = _ts((failed or {}).get("requested_at")) or t_fail
        for r in runs:
            if r.get("run_id") == failed_run_id or not _ok_done(r):
                continue
            t = _ts(r.get("requested_at")) or _ts(r.get("started_at"))
            if t is not None and t_req is not None and abs(t - t_req) <= SLOT_WINDOW_S:
                return {"kind": "auto_close", "outcome": "covered", "evidence": [f"run:{r.get('run_id')}"],
                        "cause": "lock held by another run of the lane in the same slot; that run finished RUN_DONE"}
    # 2. executor_lost -> the existing reaper
    if (et == "RUN_TIMEOUT" and "executor_lost" in f"{err} {reason}".lower()) or any(
            r.get("state") in ("RUNNING", "RUN_RUNNING") and _orphan(r, now) for r in runs):
        return {"kind": "reap", "outcome": "reap_orphan_run", "action_id": "reap_orphan_run",
                "evidence": [f"run:{r.get('run_id')}" for r in runs if r.get("state") in ("RUNNING", "RUN_RUNNING")][:3],
                "cause": "RUN_TIMEOUT executor_lost: the run lost its executor; reap the orphan row"}
    # 3. a later successful run of the same lane
    if t_fail is not None:
        mode = failure_mode(fields, err) or (failed or {}).get("mode")
        for r in runs:
            if r.get("run_id") == failed_run_id or not _ok_done(r):
                continue
            t_done = _ts(r.get("finished_at"))
            if t_done is None or t_done <= t_fail:
                continue
            if et == "NO_OUTPUT":
                ok = r.get("mode") == "live" or _signal_advanced(r)
            else:
                ok = mode is None or r.get("mode") == mode
            if ok:
                return {"kind": "auto_close", "outcome": "self_recovered", "evidence": [f"run:{r.get('run_id')}"],
                        "cause": f"a later {r.get('mode')} run of the lane finished RUN_DONE at {r.get('finished_at')}"}
    return None


def _orphan(run: Mapping[str, Any], now: float, timeout_s: float = 0.0) -> bool:
    """Only a RUNNING row whose receipt-less heartbeat is older than 2 h counts here; the handler re-checks the real
    precondition (2x timeout, stale heartbeat, dead pid) before it finishes anything."""
    hb = _ts(run.get("heartbeat_at")) or _ts(run.get("started_at")) or _ts(run.get("requested_at"))
    return hb is not None and now - hb > max(7200.0, 2 * timeout_s)


_SLOT_KEY_RE = re.compile(r"^[de]:([a-z0-9][a-z0-9._-]{1,63}):live:[0-9]{8}T[0-9]{4}(?::a[2-9])?$")


def slot_parent(lane: str, fields: Mapping[str, Any], runs: Iterable[Mapping[str, Any]]) -> Optional[str]:
    """The FAILED live d:/e: run a live heal retries (its effect slot is the one re-claimed): the incident's own run
    when it is one, else the lane's newest RUN_FAILED live slot run. None = nothing to bind to (no live heal)."""
    runs = list(runs)
    rid = str(fields.get("run") or "")
    m = _SLOT_KEY_RE.match(rid)
    if m and m.group(1) == lane:
        row = next((r for r in runs if r.get("run_id") == rid), None)
        if row is None or row.get("state") == "RUN_FAILED":
            return rid
    for r in runs:
        m = _SLOT_KEY_RE.match(str(r.get("run_id") or ""))
        if m and m.group(1) == lane and r.get("state") == "RUN_FAILED" and r.get("mode") == "live":
            return str(r["run_id"])
    return None


# ---------------------------------------------------------------- live heal gate


def _p1_lanes(cutover_policy: Optional[Mapping[str, Any]]) -> frozenset[str]:
    if not isinstance(cutover_policy, Mapping):
        return frozenset()
    out: set[str] = set()
    for key in ("p1_lanes", "p1", "never_auto_live"):
        v = cutover_policy.get(key)
        if isinstance(v, list):
            out.update(str(x) for x in v)
    for row in cutover_policy.get("lanes") or []:
        if isinstance(row, Mapping) and str(row.get("priority") or row.get("tier") or "").upper() == "P1":
            out.add(str(row.get("lane_id")))
    return frozenset(out)


def live_heal_gate(lane: str, *, registry_row: Optional[Mapping[str, Any]], effect_spec: Optional[Mapping[str, Any]],
                   effect_owner: Optional[str], failure_class: str, catalogue_entry: Optional[Mapping[str, Any]],
                   cutover_policy: Optional[Mapping[str, Any]] = None, live_heals_today: int = 0
                   ) -> tuple[bool, str]:
    """(allowed, reason). Every condition is checked; the first failing one is the reason."""
    reg = registry_row or {}
    sched = reg.get("scheduler") if isinstance(reg.get("scheduler"), Mapping) else {}
    dispatch = reg.get("dispatch") if isinstance(reg.get("dispatch"), Mapping) else {}
    low = lane.lower()
    if effect_owner != "n8n":
        return False, f"effect_owner_not_n8n:{effect_owner or 'none'}"
    if sched.get("stage") not in LIVE_HEAL_STAGES:
        return False, f"stage_not_canary_or_cutover:{sched.get('stage') or 'none'}"
    if reg.get("state") not in (None, "ACTIVE"):
        return False, f"registry_state:{reg.get('state')}"
    klass = str(dispatch.get("class") or "").lower()
    if klass in SENDER_CLASSES or any(w in low for w in SENDER_WORDS):
        return False, "sender_lane"
    fam = str(reg.get("family") or dispatch.get("family") or "").upper()
    if fam in NEVER_LIVE_FAMILIES or any(w in low for w in NEVER_LIVE_WORDS):
        return False, "broker_order_stop_options_lane"
    prio = dispatch.get("priority")
    if lane in _p1_lanes(cutover_policy) or (isinstance(prio, int) and not isinstance(prio, bool)
                                             and prio <= P1_DISPATCH_PRIORITY_MAX):
        return False, "p1_lane"
    if (catalogue_entry or {}).get("severity") in ("Critical", "High"):
        return False, f"severity_{(catalogue_entry or {}).get('severity')}"
    if failure_class != TRANSIENT:
        return False, f"failure_not_transient:{failure_class}"
    if not effect_spec:
        return False, "no_effect_key:duplicate_effect_not_excluded"
    if live_heals_today >= LIVE_HEAL_MAX_PER_LANE_DAY:
        return False, "live_heal_daily_cap"
    return True, "ok"

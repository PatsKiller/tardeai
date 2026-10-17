"""n8n lane self-healing: the deterministic tier, failure signatures and the live-heal gate (pure; no I/O).

Operator 2026-10-16 ("yes make self healing now"). Measured that day: 612 diagnosis events, 12 diagnosed, 0
remediation runs, 695 open escalations. The diagnoser (scripts/n8n_failure_diagnosis.py) spent its model budget
on the same failure over and over (the 3-per-lane-per-day cap counted retries of ONE failure), sent known
deterministic patterns to the model, and had no action that could heal a live lane. This module holds the rules;
the CLI applies them before the model path. Tranche defect fixes (operator directive, same day) are marked [Dn]:

1. ``signature`` — lane + event_type + failure CLASS + normalized error tail [D3]. Meaningful codes (HTTP status,
   errno, exit code) and classes (auth / rate_limit / client / timeout / server / network / code_error:<Exc>) are
   kept; only volatile tokens (timestamps, slots, uuids, hex, run ids, pids, paths, other numbers) collapse.
2. ``deterministic_verdict`` — no model call; each occurrence on its OWN evidence:
   * a lock skip -> ``covered`` only by another run that completed VERIFIED in the same mode and the same semantic
     slot (``lock_skip_cover``) [D2]; a nearby dry run never covers a live run. "Verified" is ONE shared rule,
     scripts/lib/recovery_validator.validate (architect review 2026-10-16, finding 1): the EFFECTIVE mode from the
     receipt (a live request the stage clamp ran as dry_run is a dry run), and for live the output contract met;
   * RUN_TIMEOUT executor_lost (or an overdue RUNNING orphan) -> the existing ``reap_orphan_run`` handler;
   * NO_OUTPUT / STALE_OUTPUT -> ``output_recovered`` only when a later run that EXECUTED live has an output verdict
     saying the expected output was produced [D1] (a fresh shared file mtime / JSON timestamp alone never counts,
     finding 1); any other failure -> ``self_recovered`` only on a later run verified in the failed mode.
3. ``classify_failure`` — transient | code_error | auth | unknown (auth is never transient) [D3].
4. ``attach_decision`` — an occurrence rides an episode only while the episode is open and it is no more severe; a
   severity upgrade or an occurrence after recovery is processed on its own (a new episode = a new incident) [D4].
5. Explicit heal states ``recovery_requested`` -> ``attempt_executed`` -> ``output_recovered`` ->
   ``incident_resolved``; only the last two are healed (``is_healed``) [D6].
6. ``live_heal_gate`` + ``retry_coordination`` + ``effect_hold`` — ``rerun_live_once`` only when ALL hold: effect
   owner n8n, stage canary or cutover, on the relay live list, not held / sender / P1 / F07 / F09-broker-order-stop
   -options, a transient failure, a semantic effect key, the slot's retry owner is not already retrying (and its
   budget not spent), and the parent slot's effect claim is pre-effect (ambiguous / post-effect = HELD, never
   released) [D7]. At most one per lane per day; bound to the FAILED parent; through ``host_run_request`` only.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0: nothing here sizes, orders, stops, sends or touches a broker.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from scripts.lib import recovery_validator as RV

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

#: 2026-10-16 defect fix 3 (operator): a fingerprint keeps the codes that MEAN something (HTTP status, errno, exit
#: code, signal) and normalizes only volatile tokens (timestamps, slots, uuids, hex ids, run/siem ids, pids, paths,
#: other numbers). Before this, ``\d+ -> <n>`` made HTTP 401 and HTTP 500 one signature.
_PROTECTED_CODE_RES = (
    re.compile(r"\b(HTTP(?:/\d(?:\.\d)?)?|status(?:_code)?|code|errno|Errno|exit(?:_code)?|exit status|rc|"
               r"returncode|signal|sig)\b([\s:=#\[(/]*)(-?\d{1,3})\b", re.I),
    re.compile(r"\b([1-5]\d\d)(?=\s+(?:Unauthorized|Forbidden|Not Found|Too Many Requests|Bad Request|Conflict|"
               r"Internal Server Error|Bad Gateway|Service Unavailable|Gateway Time-?out|Request Timeout)\b)", re.I),
)
_NORMALIZERS = (
    (re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:[+-]\d\d:?\d\d|Z)?"), "<ts>"),
    (re.compile(r"\b\d{8}T\d{4}\b"), "<slot>"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{10,}\b", re.I), "<hex>"),
    (re.compile(r"\b(?:siem|run|rem|d|e|g|p)[:-][A-Za-z0-9._:-]{6,}"), "<id>"),
    (re.compile(r"\bpid[\s:=]*\d+", re.I), "pid=<pid>"),
    (re.compile(r"(?<![\w.])(?:~|\.{0,2})/[\w.@+-]+(?:/[\w.@+-]+)+"), "<path>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
)
SIGNATURE_TAIL_CHARS = 240
#: Failure classes a fingerprint never merges (operator 2026-10-16: auth != server != timeout != code error).
AUTH = "auth"
KIND_AUTH, KIND_RATE_LIMIT, KIND_SERVER, KIND_TIMEOUT, KIND_NETWORK, KIND_CLIENT = (
    "auth", "rate_limit", "server", "timeout", "network", "client")
KIND_CODE_ERROR_PREFIX = "code_error:"
_AUTH_RES = tuple(re.compile(p, re.I) for p in (
    r"\b(?:HTTP|status(?:_code)?|code)[\s:=/]*40[13]\b", r"\b40[13] (?:Unauthorized|Forbidden)\b", r"\bUnauthorized\b",
    r"\bForbidden\b", r"\binvalid_grant\b", r"\binvalid_client\b", r"\b(?:token|credential)s? (?:expired|invalid|revoked)\b",
    r"\bAuthenticationError\b", r"\bPermissionDenied\b", r"\bauth(?:entication|orization)? failed\b",
))
_RATE_RES = tuple(re.compile(p, re.I) for p in (
    r"\b(?:HTTP|status(?:_code)?|code)[\s:=/]*429\b", r"\b429 Too Many Requests\b", r"\brate[ _-]?limit", r"\bRateLimitError\b",
))
_CLIENT_RES = (re.compile(r"\b(?:HTTP|status(?:_code)?|code)[\s:=/]*4\d\d\b", re.I),)
_TIMEOUT_RES = tuple(re.compile(p, re.I) for p in (
    r"\btimed?[ _-]?out\b", r"\btimeout\b", r"\bRUN_TIMEOUT\b", r"\bdeadline exceeded\b", r"\bReadTimeout\b",
    r"\bConnectTimeout\b", r"\b(?:HTTP|status(?:_code)?|code)[\s:=/]*504\b",
))
_SERVER_RES = (re.compile(r"\b(?:HTTP|status(?:_code)?|code)[\s:=/]*5\d\d\b", re.I),
               re.compile(r"\b5\d\d (?:Internal Server Error|Bad Gateway|Service Unavailable)\b", re.I))
_EXC_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception))\b")


def _protect(text: str) -> tuple[str, list[str]]:
    """Replace meaningful codes with digit-free placeholders so the number normalizer cannot touch them."""
    kept: list[str] = []

    def hold(token: str) -> str:
        kept.append(token)
        return f"\ue000{chr(0xE100 + len(kept) - 1)}\ue001"

    out = _PROTECTED_CODE_RES[0].sub(lambda m: hold(f"{m.group(1).lower()}={m.group(3)}"), text)
    out = _PROTECTED_CODE_RES[1].sub(lambda m: hold(f"http={m.group(1)}"), out)
    return out, kept


def normalize_error(text: Any) -> str:
    out, kept = _protect(str(text or ""))
    for rx, rep in _NORMALIZERS:
        out = rx.sub(rep, out)
    for i, token in enumerate(kept):
        out = out.replace(f"\ue000{chr(0xE100 + i)}\ue001", token)
    return out.strip().lower()[-SIGNATURE_TAIL_CHARS:]


def failure_kind(text: Any, *, event_type: Any = None) -> str:
    """The failure CLASS a fingerprint keeps apart: ``code_error:<Exception>`` | auth | rate_limit | client | timeout
    | server | network | ``<EVENT_TYPE>`` | unknown. A code error wins (the bug is in the lane), then auth, rate limit,
    timeout, server, network. Pure."""
    blob = str(text or "")
    if any(rx.search(blob) for rx in _CODE_ERROR_RES):
        m = _EXC_NAME_RE.search(blob)
        return KIND_CODE_ERROR_PREFIX + (m.group(1) if m else "python")
    for kind, rxs in ((KIND_AUTH, _AUTH_RES), (KIND_RATE_LIMIT, _RATE_RES), (KIND_TIMEOUT, _TIMEOUT_RES),
                      (KIND_SERVER, _SERVER_RES), (KIND_CLIENT, _CLIENT_RES)):
        if any(rx.search(blob) for rx in rxs):
            return kind
    if any(rx.search(blob) for rx in _TRANSIENT_RES):
        return KIND_NETWORK
    et = str(event_type or "").upper()
    return et.lower() if et == "RUN_TIMEOUT" else "unknown"


def signature(lane: str, event_type: Any, error_text: Any) -> str:
    """Stable id of one failure KIND on one lane: lane | event type | failure class | normalized error tail. The lane
    prefix the SIEM bridge puts on its error is dropped. Volatile tokens collapse; codes and classes do not."""
    err = str(error_text or "")
    if err.startswith(f"{lane}:"):
        err = err[len(lane) + 1:]
    et = str(event_type or "").upper()
    raw = f"{lane}|{et}|{failure_kind(err, event_type=et)}|{normalize_error(err)}"
    return "sig-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def classify_failure(text: Any, *, event_type: Any = None, run_reason: Any = None) -> str:
    """transient | code_error | auth | unknown. A code error wins over a transient word in the same text; an auth
    failure (401/403, invalid_grant, expired token) is never transient: a rerun cannot fix a credential."""
    blob = " ".join(str(x or "") for x in (event_type, run_reason, text))
    if any(rx.search(blob) for rx in _CODE_ERROR_RES):
        return CODE_ERROR
    if any(rx.search(blob) for rx in _AUTH_RES):
        return AUTH
    if any(rx.search(blob) for rx in _RATE_RES) or any(rx.search(blob) for rx in _CLIENT_RES):
        return UNKNOWN
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
    return RV.receipt_of(run)


_MODE_RE = re.compile(r"\bmode=(dry_run|live)\b")
_KEY_MODE_RE = re.compile(r"^[deg]:[^:]+:(dry_run|live):")
#: A semantic slot key: ``<ns>:<lane>:<mode>:<slot>[:aN]`` (d:/e:/g: dispatcher keys, p: process-step keys).
_SEMANTIC_KEY_RE = RV.SEMANTIC_KEY_RE
#: Failure kinds whose breached condition is the lane's OUTPUT (defect fix 1): only fresh output closes them.
OUTPUT_KINDS = frozenset({"NO_OUTPUT", "STALE_OUTPUT"})
#: n8n_output_verdict verdicts that mean "the expected output was produced by the lane's contract".
OUTPUT_MET = RV.OUTPUT_MET
OUTPUT_FAILED = RV.OUTPUT_FAILED
#: heartbeat_watch.classify verdict that means "fresh by the lane's contract" (cadence or cron, x2 factor).
CONTRACT_FRESH = "FRESH"
_SKIP_REASONS = RV.SKIP_REASONS

# ---------------------------------------------------------------- explicit heal states (defect fix 6)
#: A recovery was requested (a REQUESTED ledger row exists). NOT healed.
RECOVERY_REQUESTED = "recovery_requested"
#: The requested run finished (RUN_DONE / RUN_FAILED / ...). NOT healed by itself.
ATTEMPT_EXECUTED = "attempt_executed"
#: The breached condition recovered: output fresh by the lane's contract, or a verified run in the failed mode/slot.
OUTPUT_RECOVERED = "output_recovered"
#: The incident's lifecycle closed (its escalation cleared, its episode resolved). Only after OUTPUT_RECOVERED.
INCIDENT_RESOLVED = "incident_resolved"
HEAL_STATES = (RECOVERY_REQUESTED, ATTEMPT_EXECUTED, OUTPUT_RECOVERED, INCIDENT_RESOLVED)
#: The only states that may be reported as healed.
HEALED_STATES = frozenset({OUTPUT_RECOVERED, INCIDENT_RESOLVED})


def is_healed(heal_state: Any) -> bool:
    return heal_state in HEALED_STATES


def failure_mode(fields: Mapping[str, Any], error_text: Any) -> Optional[str]:
    m = _MODE_RE.search(str(error_text or ""))
    if m:
        return m.group(1)
    m = _KEY_MODE_RE.match(str(fields.get("run") or ""))
    return m.group(1) if m else None


def semantic_slot(run: Mapping[str, Any]) -> Optional[tuple[str, str, str]]:
    """(lane, mode, slot) of a run from its slot_key, run_id or (slot-bound retry) parent_run_id; None = unknown.
    The mode element is the REQUESTED mode of the key; evidence checks use ``RV.effective_mode``."""
    return RV.semantic_slot(run)


def _ok_done(run: Mapping[str, Any]) -> bool:
    if run.get("state") != "RUN_DONE":
        return False
    ec = run.get("exit_code")
    if ec is None:
        ec = _receipt(run).get("exit_code")
    return ec in (None, 0, "0")


def _output_verdict(run: Mapping[str, Any]) -> Optional[str]:
    return RV.output_verdict(run)


def verified_done(run: Mapping[str, Any], mode: Optional[str]) -> bool:
    """The run completed the REQUIRED work, verified, in ``mode`` — scripts/lib/recovery_validator.validate, the one
    shared rule (architect review 2026-10-16, finding 1): the EFFECTIVE mode from the receipt (a live request
    clamped to dry_run is not a live run), RUN_DONE exit 0, not a skip, and for a live run the lane's output
    contract met (``output_verdict`` produced / empty_allowed; an advancing mtime is not evidence)."""
    return RV.validate(run, mode=mode)[0]


def output_contract_fresh(output_state: Optional[Mapping[str, Any]], since: Optional[float]) -> bool:
    """The lane's output signal is FRESH by heartbeat_watch.classify AND newer than ``since``. EVIDENCE ONLY since
    the 2026-10-16 architect review (finding 1): a shared file mtime or JSON timestamp never closes an incident;
    ``output_recovered`` no longer reads it. Kept for the evidence pack / receipts."""
    if not isinstance(output_state, Mapping) or output_state.get("verdict") != CONTRACT_FRESH:
        return False
    last = _ts(output_state.get("last_output_at"))
    return last is not None and (since is None or last > since)


def output_recovered(event_type: Any, *, failure_mode_: Optional[str], since: Optional[float],
                     runs: Iterable[Mapping[str, Any]], output_state: Optional[Mapping[str, Any]] = None,
                     exclude_run: Optional[str] = None, slot: Optional[tuple[str, str, str]] = None,
                     lane: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Evidence that the BREACHED condition recovered, or None (pure). Both branches go through
    scripts/lib/recovery_validator (finding 1, architect review 2026-10-16):

    * NO_OUTPUT / STALE_OUTPUT: a later run that EXECUTED live (effective mode) with ``output_verdict`` produced /
      empty_allowed (in ``slot`` when given). ``output_state`` (a fresh shared file) is never evidence.
    * Any other failure: a later run verified in the failed mode (``RV.validate``); in ``slot`` when given."""
    del output_state            # evidence only (the caller records it); never a recovery basis
    et = str(event_type or "").upper()
    if et in OUTPUT_KINDS:
        ev = RV.output_recovered(lane, since, {"mode": "live", "slot": slot}, runs=runs, exclude_run=exclude_run) \
            if lane is not None else _first_valid(runs, mode="live", since=since, slot=slot, exclude_run=exclude_run)
        if ev is None:
            return None
        return {"basis": "expected_output_produced", "evidence": ev["evidence"], "output_verdict": ev["output_verdict"],
                "effective_mode": ev["effective_mode"]}
    ev = _first_valid(runs, mode=failure_mode_, since=since, slot=slot, exclude_run=exclude_run, lane=lane)
    if ev is None:
        return None
    return {"basis": "verified_run_same_mode", "evidence": ev["evidence"], "mode": failure_mode_,
            "effective_mode": ev["effective_mode"]}


def _first_valid(runs: Iterable[Mapping[str, Any]], *, mode: Optional[str], since: Optional[float],
                 slot: Optional[tuple[str, str, str]], exclude_run: Optional[str],
                 lane: Optional[str] = None) -> Optional[dict[str, Any]]:
    for r in runs:
        ok, _why = RV.validate(r, mode=mode, lane=lane, slot=slot, since=since, exclude_run=exclude_run)
        if ok:
            return {"evidence": [f"run:{r.get('run_id')}"], "effective_mode": RV.effective_mode(r),
                    "output_verdict": RV.output_verdict(r)}
    return None


def _is_lock_skip(event_type: str, error_text: str, run_reason: Any) -> bool:
    blob = f"{error_text} {run_reason or ''}".lower()
    return event_type == "RUN_SKIPPED_LOCK" or "flock_held" in blob or "lock_skipped" in blob


def lock_skip_cover(failed: Optional[Mapping[str, Any]], fields: Mapping[str, Any], err: str,
                    runs: Iterable[Mapping[str, Any]]) -> tuple[Optional[Mapping[str, Any]], str]:
    """(covering run, why). A lock skip is covered ONLY by another run of the SAME semantic slot that completed the
    required work, verified by scripts/lib/recovery_validator.validate in the skip's mode — the EFFECTIVE mode from
    the covering run's receipt (architect review 2026-10-16, finding 1: a live-requested run the stage clamp executed
    as dry_run never covers a live skip). The skip's own mode is its effective mode when its receipt has one, else
    its requested mode (the stricter reading)."""
    me = dict(failed or {})
    if not me.get("run_id") and fields.get("run"):
        me["run_id"] = fields.get("run")
    slot = semantic_slot(me)
    mode = (RV.effective_mode(me) if _receipt(me) else None) or me.get("mode") or failure_mode(fields, err) \
        or (slot[1] if slot else None)
    if slot is None:
        return None, "skip_slot_unknown"
    if mode is None:
        return None, "skip_mode_unknown"
    why = "no_verified_run_in_slot_and_mode"
    for r in runs:
        if r.get("run_id") == me.get("run_id"):
            continue
        ok, reason = RV.validate(r, mode=mode, slot=slot)
        if ok:
            return r, "covered"
        if reason not in ("other_slot", "slot_unknown"):
            why = f"no_verified_run_in_slot_and_mode:{reason}"
    return None, why


def deterministic_verdict(row: Mapping[str, Any], *, fields: Mapping[str, Any], runs: Iterable[Mapping[str, Any]],
                          now: float, output_state: Optional[Mapping[str, Any]] = None) -> Optional[dict[str, Any]]:
    """{kind: auto_close|reap, outcome, evidence, cause} or None (the model path decides).

    ``row`` is the SIEM row, ``fields`` its parsed message (lane, run, error, at), ``runs`` the lane's recent
    ledger rows (newest first), ``output_state`` the lane's output signal judged by its contract (None = unknown)."""
    runs = list(runs)
    et = str(row.get("event_type") or "").upper()
    err = str(fields.get("error") or row.get("message") or "")
    failed_run_id = fields.get("run")
    failed = next((r for r in runs if r.get("run_id") == failed_run_id), None) if failed_run_id else None
    reason = (_receipt(failed).get("reason") if failed else None) or ""
    t_fail = (_ts((failed or {}).get("finished_at")) or _ts((failed or {}).get("requested_at"))
              or _ts(fields.get("at")) or _ts(row.get("created_at")))
    # 1. lock skip covered by a verified run of the same mode and semantic slot
    if _is_lock_skip(et, err, reason) or (failed and failed.get("state") == "RUN_SKIPPED_LOCK"):
        cover, _why = lock_skip_cover(failed, fields, err, runs)
        if cover is not None:
            return {"kind": "auto_close", "outcome": "covered", "evidence": [f"run:{cover.get('run_id')}"],
                    "heal_state": OUTPUT_RECOVERED,
                    "cause": f"lock held by a {cover.get('mode')} run of the same slot that completed verified"}
        return None
    # 2. executor_lost -> the existing reaper
    if (et == "RUN_TIMEOUT" and "executor_lost" in f"{err} {reason}".lower()) or any(
            r.get("state") in ("RUNNING", "RUN_RUNNING") and _orphan(r, now) for r in runs):
        return {"kind": "reap", "outcome": "reap_orphan_run", "action_id": "reap_orphan_run",
                "evidence": [f"run:{r.get('run_id')}" for r in runs if r.get("state") in ("RUNNING", "RUN_RUNNING")][:3],
                "cause": "RUN_TIMEOUT executor_lost: the run lost its executor; reap the orphan row"}
    # 3. the breached condition recovered (output fresh by contract / a later verified run in the failed mode)
    if t_fail is not None:
        mode = failed_effective_mode(failed, fields, err)
        ev = output_recovered(et, failure_mode_=mode, since=t_fail, runs=runs, output_state=output_state,
                              exclude_run=failed_run_id, lane=fields.get("lane") or (failed or {}).get("lane_id"))
        if ev is not None:
            outcome = "output_recovered" if et in OUTPUT_KINDS else "self_recovered"
            return {"kind": "auto_close", "outcome": outcome, "evidence": ev["evidence"], "basis": ev["basis"],
                    "heal_state": OUTPUT_RECOVERED,
                    "cause": f"breached condition recovered after the failure ({ev['basis']})"}
    return None


def failed_effective_mode(failed: Optional[Mapping[str, Any]], fields: Mapping[str, Any], err: Any) -> Optional[str]:
    """The mode the FAILED run executed in: its receipt's effective mode when it has a receipt, else the requested
    mode (row / message / key). One rule for the diagnoser and the deterministic tier (finding 1)."""
    f = failed or {}
    return (RV.effective_mode(f) if _receipt(f) else None) or f.get("mode") or failure_mode(fields, err)


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


#: Families never live-healed: F09 (broker/execution) and F07 (host daemons, kept off n8n by the 10-15 directive).
POLICY_NEVER_LIVE_FAMILIES = frozenset({"F07", "F09"})
LIVE_LIST_ENV = "TRADEAI_N8N_RELAY_LIVE_LANES"   # == scripts/lib/n8n_due.LIVE_LANES_ENV (the relay's live list)


def _p1_lanes(cutover_policy: Optional[Mapping[str, Any]]) -> frozenset[str]:
    """P1 lanes from config/lane_cutover_policy.json (``p1_last``, the 2026-10-16 shape) or the older list keys."""
    if not isinstance(cutover_policy, Mapping):
        return frozenset()
    out: set[str] = set()
    for key in ("p1_last", "p1_lanes", "p1", "never_auto_live"):
        v = cutover_policy.get(key)
        if isinstance(v, list):
            out.update(str(x) for x in v)
    for row in cutover_policy.get("lanes") or []:
        if isinstance(row, Mapping) and str(row.get("priority") or row.get("tier") or "").upper() == "P1":
            out.add(str(row.get("lane_id")))
    return frozenset(out)


def _policy_family(lane: str, cutover_policy: Optional[Mapping[str, Any]]) -> str:
    fams = cutover_policy.get("families") if isinstance(cutover_policy, Mapping) else None
    return str(fams.get(lane) or "").upper() if isinstance(fams, Mapping) else ""


def _held(lane: str, cutover_policy: Optional[Mapping[str, Any]]) -> Optional[str]:
    holds = cutover_policy.get("holds") if isinstance(cutover_policy, Mapping) else None
    if isinstance(holds, Mapping) and lane in holds:
        return str(holds[lane])[:60] or "hold"
    if isinstance(holds, list) and lane in holds:
        return "hold"
    return None


def parse_live_list(environ: Mapping[str, str]) -> Optional[frozenset[str]]:
    """The relay's live-lane list; None when the variable is absent (unknown = no live heal, never an empty pass)."""
    if LIVE_LIST_ENV not in environ:
        return None
    return frozenset(p for p in str(environ.get(LIVE_LIST_ENV) or "").split() if p)


def live_heal_gate(lane: str, *, registry_row: Optional[Mapping[str, Any]], effect_spec: Optional[Mapping[str, Any]],
                   effect_owner: Optional[str], failure_class: str, catalogue_entry: Optional[Mapping[str, Any]],
                   cutover_policy: Optional[Mapping[str, Any]] = None, live_heals_today: int = 0,
                   live_lanes: Optional[frozenset[str]] = None) -> tuple[bool, str]:
    """(allowed, reason). Every condition is checked; the first failing one is the reason. ``live_lanes`` is the
    relay's current live list (None = unavailable = refused): a lane n8n does not run live is never healed live."""
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
    if live_lanes is None:
        return False, "live_list_unavailable"
    if lane not in live_lanes:
        return False, "not_on_live_list"
    held = _held(lane, cutover_policy)
    if held:
        return False, f"cutover_policy_hold:{held}"
    klass = str(dispatch.get("class") or "").lower()
    if klass in SENDER_CLASSES or any(w in low for w in SENDER_WORDS):
        return False, "sender_lane"
    fam = str(reg.get("family") or dispatch.get("family") or "").upper() or _policy_family(lane, cutover_policy)
    if fam in NEVER_LIVE_FAMILIES or fam in POLICY_NEVER_LIVE_FAMILIES or any(w in low for w in NEVER_LIVE_WORDS):
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


# ---------------------------------------------------------------- retry owner + effect hold (defect fix 7)

RETRY_OWNER_HOST = "host_policy"          # == scripts/n8n_run_executor.RETRY_OWNER_HOST


def retry_coordination(parent: Optional[Mapping[str, Any]], runs: Iterable[Mapping[str, Any]] = ()) -> tuple[bool, str]:
    """(may_heal, why). ONE retry owner per slot (audit DD04): the parent's receipt ``retry`` block decides.

    * no parent row / not RUN_FAILED                          -> no (nothing proven to retry);
    * a later attempt of the same slot exists                 -> no (the owner already retried);
    * owner ``host_policy`` and ``retryable``                 -> no: coordination/due mints the RETRY_DUE attempt;
    * verdict ``terminal`` or the owner's budget exhausted    -> no: a heal would exceed the owner's budget;
    * owner not ``host_policy`` (run_lane / executor_inline)  -> no: that owner retries, not the diagnoser;
    * no retry decision on the parent (policies unavailable when it finished) -> yes, as the slot's ONE extra
      attempt, and only while the slot's effect claim allows it (``effect_hold``)."""
    if not parent:
        return False, "parent_missing"
    if parent.get("state") != "RUN_FAILED":
        return False, f"parent_not_failed:{parent.get('state')}"
    ps = semantic_slot(parent)
    t_parent = _ts(parent.get("requested_at")) or 0.0
    for r in runs:
        if r.get("run_id") == parent.get("run_id"):
            continue
        rs = semantic_slot(r)
        if ps and rs and rs == ps and (_ts(r.get("requested_at")) or 0.0) > t_parent:
            return False, f"slot_already_retried:{r.get('run_id')}"
    retry = _receipt(parent).get("retry")
    if not isinstance(retry, Mapping) or retry.get("verdict") is None:
        return True, "no_owner_decision"
    owner = retry.get("owner")
    if owner != RETRY_OWNER_HOST:
        return False, f"retry_owner:{owner}"
    if retry.get("retryable"):
        return False, "host_retry_pending"
    if retry.get("verdict") == "terminal":
        return False, f"host_verdict_terminal:{str(retry.get('terminal_reason') or '')[:40]}"
    return False, "host_retry_budget_exhausted"


def effect_hold(claim: Optional[Mapping[str, Any]], *, readable: bool = True) -> tuple[bool, str]:
    """(may_heal, why) from the parent slot's effect claim (read-only). Ambiguous or post-effect failures are HELD:
    the diagnoser never releases a claim to make a retry succeed."""
    if not readable:
        return False, "held:effect_ledger_unreadable"
    if claim is None:
        return True, "no_claim:pre_effect"
    state = str(claim.get("state") or "")
    if claim.get("fence_passed_at"):
        return False, "held:post_fence"
    if state == "FAILED":
        return (True, "failed_pre_effect") if claim.get("pre_effect") else (False, "held:failed_unproven_pre_effect")
    if state == "RELEASED":
        return True, "released_by_operator"
    if state == "DONE":
        return False, "held:effect_done"
    if state == "CLAIMED":
        return False, "held:claim_in_flight"
    return False, f"held:ambiguous_{state.lower() or 'unknown'}"


# ---------------------------------------------------------------- severity + episodes (defect fix 4)

SEVERITY_RANK = {"CRITICAL": 0, "URGENT": 1, "WARN": 2, "INFO": 3}


def severity_rank(sev: Any) -> int:
    return SEVERITY_RANK.get(str(sev or "").upper(), 9)


def attach_decision(episode: Optional[Mapping[str, Any]], *, key: str, severity: Any) -> tuple[bool, str]:
    """(attach, why). An occurrence rides an episode's lead ONLY while that episode is open and the occurrence is no
    more severe than the episode. A severity upgrade is processed (and escalated) on its own; an occurrence after the
    episode resolved opens a NEW episode. Evaluated on every occurrence, every cycle."""
    if not episode or not episode.get("lead"):
        return False, "no_open_episode"
    if episode.get("lead") == key:
        return False, "is_lead"
    if episode.get("status") != "open":
        return False, "episode_resolved:new_episode"
    if severity_rank(severity) < severity_rank(episode.get("severity")):
        return False, f"severity_upgrade:{episode.get('severity')}->{str(severity or '').upper()}"
    return True, "duplicate_signature"

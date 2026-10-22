"""Release train n8n coordination: the records, their validators and the read-only views (Phase 4, 2026-10-21).

Contract: ``docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md``. This is the part of the contract the gateway serves to n8n and
the Phase 3 controller validates with:

    TrainWindowRequest@v1     one request that the controller consider a window (written by the request lane)
    TrainWindowReceipt@v1     the controller's answer (written only by the controller)
    ReleaseTrainReadiness@v1  the read-only view n8n gates and reports on (relay GET /release-train-window?view=readiness)
    ReleaseTrainWindowView@v1 one request + its receipt, by run_id or slot (relay GET /release-train-window?run_id=|slot=)

Deliberately small, because it sits in the gateway's import closure (``scripts/n8n_coordination_gateway.py`` loads it
lazily for the ``release_train_window`` read operation, and other lanes' reviewed env inventories walk that closure):
stdlib plus ``release_train_contracts`` (stdlib only) and NO environment read. Every path is passed in by the caller;
the gateway derives the release-window state dir from its own ledger's state root. It never imports the Phase 1 view,
the classifier, the queue store, the deployer (``release_window.py``) or the Phase 2 authority modules.

Read-only: nothing here writes, runs, merges, pushes, promotes, rolls back, issues a capability, touches the STOP latch
or sends. AUTHORITY: READ_ONLY_ADVISORY (a request is REQUEST_ONLY: never authority). MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

try:
    from lib import release_train_contracts as C
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_contracts as C  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "release_train_n8n.json"
POLICY_PATH = ROOT / "config" / "release_train_policy.json"
SCHEMA_DIR = ROOT / "config" / "schemas" / "release_train"
#: Phase 2's default host path for the standing delegation (scripts/lib/release_delegation.py DEFAULT_PATH).
DELEGATION_PATH = Path.home() / ".config" / "tradeai" / "release_train" / "delegation.json"
CONFIG_SCHEMA = "ReleaseTrainN8nCoordination@v1"
TRAIN_WINDOW_REQUEST = "TrainWindowRequest@v1"
TRAIN_WINDOW_RECEIPT = "TrainWindowReceipt@v1"
READINESS_SCHEMA = "ReleaseTrainReadiness@v1"
WINDOW_VIEW_SCHEMA = "ReleaseTrainWindowView@v1"
SCHEMA_FILES = {
    TRAIN_WINDOW_REQUEST: "train_window_request.v1.schema.json",
    TRAIN_WINDOW_RECEIPT: "train_window_receipt.v1.schema.json",
}
AUTHORITY = "READ_ONLY_ADVISORY"
SLOTS = ("1800", "0000", "0600", "0800")
LANE_PREFIX = "release-train-request-"
LATCH_STATES = ("ABSENT", "SET", "UNREADABLE")
REQUEST_ID_RE = re.compile(r"^rtw-([0-9]{8})-(0000|0600|0800|1800)-(win|f[0-9a-f]{6})$")
SLOT_RE = re.compile(r"^(0000|0600|0800|1800)$")
#: The executor's run id alphabet (scripts/lib/n8n_coordination_gateway.py RUN_ID_RE is the authority at the relay).
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
SPOOL_DIR = "train_requests"
JOURNAL, PENDING, CLAIMED, RECEIPTS = "journal", "pending", "claimed", "receipts"
REQUEST_STATES = ("PENDING", "CLAIMED", "NOT_FOUND")
TERMINAL_RECEIPT_STATES = ("COMPLETED", "REFUSED", "EXPIRED", "FAILED")
DELEGATION_STATES = ("ACTIVE", "PAUSED", "REVOKED", "NOT_CONFIGURED", "INVALID", "UNAVAILABLE")
#: How many spool files a lookup reads at most (newest first by name; names sort by window date/time).
MAX_SCAN = 400
#: The relay answers in one bounded body; projections keep it small.
NEEDS_ACTION_MAX = 20
#: The gateway request keys this operation accepts, beyond route/operation/claim/signature: exactly one of these.
QUERY_KEYS = ("view", "run_id", "slot")


class ContractError(ValueError):
    """A config, request or receipt that fails its contract."""


# ── config ────────────────────────────────────────────────────────────────────────────────────────────────────


def validate_config(cfg: Any) -> list[str]:
    """Defects in a ReleaseTrainN8nCoordination@v1 document; [] when valid. Pure."""
    if not isinstance(cfg, Mapping):
        return ["config is not an object"]
    errs: list[str] = []
    if cfg.get("schema") != CONFIG_SCHEMA:
        errs.append(f"schema must be {CONFIG_SCHEMA}")
    if cfg.get("timezone") != "America/New_York":
        errs.append("timezone must be America/New_York")
    for k, lo, hi in (("request_lead_min", 15, 180), ("report_after_min", 20, 180), ("on_window_skew_min", 0, 30),
                      ("grace_min", 1, 60), ("off_window_expiry_min", 5, 240)):
        v = cfg.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            errs.append(f"{k} must be an int in [{lo}, {hi}]")
    shadow = cfg.get("shadow")
    if not isinstance(shadow, Mapping) or not isinstance(shadow.get("enabled"), bool):
        errs.append("shadow.enabled must be a boolean")
    slots = cfg.get("slots")
    if not isinstance(slots, list) or [s.get("slot") for s in slots if isinstance(s, Mapping)] != list(SLOTS):
        errs.append(f"slots must be exactly {list(SLOTS)} in that order")
    else:
        for s in slots:
            if s.get("lane_id") != LANE_PREFIX + s["slot"]:
                errs.append(f"slot {s['slot']}: lane_id must be {LANE_PREFIX + s['slot']}")
            if s.get("local_time") != f"{s['slot'][:2]}:{s['slot'][2:]}":
                errs.append(f"slot {s['slot']}: local_time mismatch")
    waits = cfg.get("receipt_wait_s")
    if not isinstance(waits, Mapping) or set(waits) != {"request", "report", "forced"} or not all(
        isinstance(v, int) and not isinstance(v, bool) and 30 <= v <= 1200 for v in waits.values()
    ):
        errs.append("receipt_wait_s must be {request, report, forced} ints in [30, 1200]")
    if cfg.get("reminder_slot") not in SLOTS:
        errs.append("reminder_slot must be one of the slots")
    if cfg.get("workflow_id") != "tradeai-fabric-release-train":
        errs.append("workflow_id must be tradeai-fabric-release-train")
    return errs


def load_config(path: Optional[Path] = None) -> dict:
    """The coordination config. Raises ContractError when it is missing, unreadable or invalid (fail closed)."""
    p = Path(path) if path is not None else CONFIG_PATH
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"config unreadable: {type(exc).__name__}") from exc
    errs = validate_config(cfg)
    if errs:
        raise ContractError("config invalid: " + "; ".join(errs[:5]))
    return cfg


def lane_for_slot(slot: str) -> str:
    if slot not in SLOTS:
        raise ContractError(f"unknown slot {slot!r}")
    return LANE_PREFIX + slot


# ── windows (pure) ────────────────────────────────────────────────────────────────────────────────────────────


def _tz(cfg: Mapping[str, Any]) -> ZoneInfo:
    return ZoneInfo(str(cfg.get("timezone") or "America/New_York"))


def window_id(local_dt: datetime) -> str:
    """``YYYY-MM-DDTHH:MM±HH:MM`` (the Phase 1 ``release_train_view.window_id`` format)."""
    iso = local_dt.isoformat()
    return iso[:16] + iso[19:]


def window_start(slot: str, now: datetime, cfg: Mapping[str, Any]) -> datetime:
    """The slot's occurrence whose start is the first at or after ``now - grace_min``, as an aware local time.

    Built as a wall-clock time in America/New_York (fold=0) and compared in UTC, so it is DST-safe and a repeated
    local hour never yields two windows; a window past its grace is gone until the next day (no catch-up)."""
    if slot not in SLOTS:
        raise ContractError(f"unknown slot {slot!r}")
    if now.tzinfo is None:
        raise ContractError("now must be timezone-aware")
    tz = _tz(cfg)
    hh, mm = int(slot[:2]), int(slot[2:])
    floor = now.astimezone(timezone.utc) - timedelta(minutes=int(cfg["grace_min"]))
    local = now.astimezone(tz)
    for days in range(-1, 3):
        d = (local + timedelta(days=days)).date()
        cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        if cand.astimezone(timezone.utc) >= floor:
            return cand
    raise ContractError("no window found")  # pragma: no cover - unreachable for a valid slot


def tick_kind(start: datetime, now: datetime, cfg: Mapping[str, Any]) -> str:
    """``on_window`` when ``start - lead - skew <= now < start + grace``; else ``off_window`` (contract §3)."""
    lead = timedelta(minutes=int(cfg["request_lead_min"]) + int(cfg["on_window_skew_min"]))
    grace = timedelta(minutes=int(cfg["grace_min"]))
    s = start.astimezone(timezone.utc)
    n = now.astimezone(timezone.utc)
    return "on_window" if s - lead <= n < s + grace else "off_window"


def request_id_for(slot: str, start: datetime, tick: str, run_id: str) -> str:
    """``rtw-<YYYYMMDD>-<HHMM>-win`` (one per window) or ``rtw-<YYYYMMDD>-<HHMM>-f<6 hex of sha256(run_id)>``."""
    suffix = "win" if tick == "on_window" else "f" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:6]
    return f"rtw-{start.strftime('%Y%m%d')}-{slot}-{suffix}"


#: Host-validated LIVE run-key namespace for the four request lanes (operator 2026-10-21 "rtw yes"; contract O3):
#: ``rtw:<slot>:<window date YYYYMMDD>:<shadow|live>``. Exact lower-case form only.
RUN_KEY_PREFIX = "rtw:"
RUN_KEY_RE = re.compile(r"^rtw:(0000|0600|0800|1800):([0-9]{8}):(shadow|live)$")


def window_run_key(slot: str, now: datetime, cfg: Mapping[str, Any], kind: str) -> str:
    """The one deterministic live run key for ``slot``'s current window (window date = ``window_start``'s local
    date). One key per lane, window and kind, so a repeat of the same window is the same key (idempotent). Pure."""
    if kind not in ("shadow", "live"):
        raise ContractError(f"unknown run-key kind {kind!r}")
    return f"{RUN_KEY_PREFIX}{slot}:{window_start(slot, now, cfg).strftime('%Y%m%d')}:{kind}"


def check_window_run_key(run_id: str, lane_id: str, mode: str, now: datetime,
                         cfg: Optional[Mapping[str, Any]] = None) -> tuple[bool, str]:
    """(ok, state) for an ``rtw:`` key as the gateway sees it. ok only when the key is well formed, the request is
    ``live``, the slot is the lane's own, and the date is the slot's CURRENT window date (``window_start`` at
    ``now``). States: OK, MALFORMED_KEY, MODE_NOT_LIVE, SLOT_MISMATCH, WINDOW_DATE_MISMATCH, CONFIG_UNAVAILABLE.
    Pure apart from loading the default config when ``cfg`` is None."""
    m = RUN_KEY_RE.fullmatch(run_id or "")
    if m is None:
        return False, "MALFORMED_KEY"
    if mode != "live":
        return False, "MODE_NOT_LIVE"
    slot, date = m.group(1), m.group(2)
    if lane_id != LANE_PREFIX + slot:
        return False, "SLOT_MISMATCH"
    try:
        c = cfg if cfg is not None else load_config()
        expected = window_start(slot, now, c).strftime("%Y%m%d")
    except (ContractError, OSError, ValueError, KeyError):
        return False, "CONFIG_UNAVAILABLE"
    if date != expected:
        return False, "WINDOW_DATE_MISMATCH"
    return True, "OK"


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ── host facts read from files (fail closed) ──────────────────────────────────────────────────────────────────


def read_latch(state_dir: Path) -> str:
    """``<state_dir>/STOP.json`` in the ``release_window.State.read_latch`` vocabulary: ABSENT only when no path
    exists; SET for a readable JSON object; UNREADABLE otherwise (a STOP). Same semantics as Phase 1's file reader."""
    latch = Path(state_dir) / "STOP.json"
    try:
        os.stat(latch)
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        return "UNREADABLE"
    try:
        body = json.loads(latch.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "UNREADABLE"
    return "SET" if isinstance(body, dict) else "UNREADABLE"


def read_policy(path: Optional[Path] = None) -> Optional[dict]:
    """The ReleaseTrainPolicy@v1 document, or None (no policy = not armed, no window enabled)."""
    try:
        doc = json.loads(Path(path or POLICY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == "ReleaseTrainPolicy@v1" else None


def policy_window(policy: Optional[Mapping[str, Any]], slot: str) -> dict[str, Any]:
    hhmm = f"{slot[:2]}:{slot[2:]}"
    for w in (policy or {}).get("windows") or ():
        if isinstance(w, Mapping) and w.get("local_time") == hhmm:
            return {"enabled": w.get("enabled") is True, "role": w.get("role")}
    return {"enabled": False, "role": None}


def declared_delegation_state(path: Optional[Path] = None) -> str:
    """The standing delegation's DECLARED status (ACTIVE / PAUSED / REVOKED), NOT_CONFIGURED when the file does not
    exist, INVALID when it is unreadable or names no known status. Advisory only: Phase 2's ``release_delegation.load``
    (full validation) is what the lane and the controller use; this is what the gateway can read cheaply."""
    p = Path(path or DELEGATION_PATH)
    if not os.path.lexists(p):
        return "NOT_CONFIGURED"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "INVALID"
    status = doc.get("status") if isinstance(doc, dict) else None
    return status if status in ("ACTIVE", "PAUSED", "REVOKED") else "INVALID"


# ── validators ────────────────────────────────────────────────────────────────────────────────────────────────


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


def schema_errors(name: str, doc: Any) -> list[str]:
    """JSON-Schema-only defects, with the Phase 1 validator subset (``release_train_contracts``)."""
    schema = load_schema(name)
    errs: list[str] = []
    C._check(doc, schema, schema, "$", errs)  # noqa: SLF001 - the shared keyword-subset validator
    return errs


def validate_request(doc: Any) -> list[str]:
    """Schema + program rules for TrainWindowRequest@v1; [] when valid."""
    errs = schema_errors(TRAIN_WINDOW_REQUEST, doc)
    if errs:
        return errs
    m = REQUEST_ID_RE.fullmatch(doc["request_id"])
    start = C.parse_ts(doc["window_start"])
    if m is None or start is None:
        return ["request_id or window_start unparseable"]
    local = start.astimezone(ZoneInfo("America/New_York"))
    if m.group(1) != local.strftime("%Y%m%d") or m.group(2) != doc["window_slot"]:
        errs.append("request_id date/slot must equal the window's local date and slot")
    if local.strftime("%H%M") != doc["window_slot"] or window_id(local) != doc["window_id"]:
        errs.append("window_start, window_id and window_slot disagree")
    if (m.group(3) == "win") != (doc["tick"] == "on_window"):
        errs.append("request_id suffix must be 'win' exactly when tick is on_window")
    if doc["shadow"] is False and (doc["tick"] != "on_window" or doc["shadow_reason"] is not None):
        errs.append("shadow=false needs tick=on_window and shadow_reason=null")
    if doc["shadow"] is True and doc["shadow_reason"] is None:
        errs.append("shadow=true needs a shadow_reason")
    if doc["tick"] == "off_window" and doc["shadow"] is not True:
        errs.append("an off_window request is always shadow")
    if doc["requested_by"]["lane_id"] != lane_for_slot(doc["window_slot"]):
        errs.append("requested_by.lane_id must be the slot's lane")
    req, exp = C.parse_ts(doc["requested_at"]), C.parse_ts(doc["expires_at"])
    if req is None or exp is None or exp <= req:
        errs.append("expires_at must be after requested_at")
    return errs


def validate_receipt(doc: Any) -> list[str]:
    """Schema + program rules for TrainWindowReceipt@v1; [] when valid."""
    errs = schema_errors(TRAIN_WINDOW_RECEIPT, doc)
    if errs:
        return errs
    if doc["shadow"] is True and doc["mode"] != "simulate":
        errs.append("shadow=true requires mode=simulate (contract C3)")
    state = doc["state"]
    if state == "ACKNOWLEDGED":
        if doc["outcome"] is not None or doc["refusal"] is not None or doc["finished_at"] is not None:
            errs.append("ACKNOWLEDGED has no outcome, refusal or finished_at")
    elif state == "COMPLETED":
        if doc["outcome"] is None or doc["refusal"] is not None:
            errs.append("COMPLETED needs an outcome and no refusal")
    else:
        if doc["refusal"] is None or doc["outcome"] is not None:
            errs.append(f"{state} needs a refusal and no outcome")
    if state in TERMINAL_RECEIPT_STATES:
        ack, fin = C.parse_ts(doc["acknowledged_at"]), C.parse_ts(doc["finished_at"])
        if fin is None or ack is None or fin < ack:
            errs.append("a terminal receipt needs finished_at >= acknowledged_at")
    if REQUEST_ID_RE.fullmatch(doc["request_id"]).group(2) != doc["window_slot"]:  # type: ignore[union-attr]
        errs.append("request_id slot must equal window_slot")
    return errs


# ── spool readers ─────────────────────────────────────────────────────────────────────────────────────────────


def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _request_files(base: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for state, sub in (("PENDING", PENDING), ("CLAIMED", CLAIMED)):
        d = base / sub
        try:
            names = [n for n in os.listdir(d) if n.endswith(".json") and REQUEST_ID_RE.fullmatch(n[:-5])]
        except OSError:
            continue
        out += [(state, d / n) for n in names]
    out.sort(key=lambda x: x[1].name, reverse=True)
    return out[:MAX_SCAN]


def request_projection(doc: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("request_id", "window_slot", "window_id", "tick", "shadow", "shadow_reason", "requested_at",
            "expires_at")
    return {k: doc.get(k) for k in keys}


def receipt_projection(doc: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """The receipt without ``evidence_refs`` (paths stay on the host), needs_action bounded."""
    if not doc:
        return None
    out = {k: v for k, v in doc.items() if k != "evidence_refs"}
    out["needs_action"] = list(doc.get("needs_action") or [])[:NEEDS_ACTION_MAX]
    return out


def find_request(
    state_dir: Path,
    *,
    run_id: Optional[str] = None,
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[str, Optional[dict], Optional[dict], Optional[str]]:
    """(request_state, request, receipt, receipt_problem) for the newest request matching ``run_id`` or ``slot``
    (a slot matches a window that started within the last 24 h). Read-only. A receipt that exists but cannot be
    read (mode 0600 under another user, or bad JSON) is ``receipt_unreadable``; one that fails its contract is
    ``receipt_invalid``; neither is passed through."""
    if (run_id is None) == (slot is None):
        raise ContractError("exactly one of run_id or slot")
    now = now or datetime.now(timezone.utc)
    base = Path(state_dir) / SPOOL_DIR
    for state, path in _request_files(base):
        doc = _read_json(path)
        if doc is None or validate_request(doc):
            continue
        if run_id is not None and doc["requested_by"]["run_id"] != run_id:
            continue
        if slot is not None:
            start = C.parse_ts(doc["window_start"])
            if doc["window_slot"] != slot or start is None or not (
                now - timedelta(hours=24) <= start <= now + timedelta(hours=3)
            ):
                continue
        rec_path = base / RECEIPTS / f"{doc['request_id']}.json"
        rec = _read_json(rec_path) if rec_path.exists() else None
        problem = None
        if rec is not None:
            errs = validate_receipt(rec)
            if errs or rec.get("request_id") != doc["request_id"]:
                problem, rec = "receipt_invalid", None
        elif rec_path.exists():
            problem = "receipt_unreadable"
        return state, doc, rec, problem
    return "NOT_FOUND", None, None, None


def shadow_coverage(state_dir: Path) -> list[dict[str, Any]]:
    """Per slot, the newest shadow request and its receipt state (the manual run's forced-tick choice, contract §10).
    Read-only; an unreadable spool reads as no coverage."""
    base = Path(state_dir) / SPOOL_DIR
    newest: dict[str, dict[str, Any]] = {}
    for _state, path in _request_files(base):
        doc = _read_json(path)
        if doc is None or validate_request(doc) or doc.get("shadow") is not True:
            continue
        slot = doc["window_slot"]
        if slot in newest and newest[slot]["last_requested_at"] >= doc["requested_at"]:
            continue
        rec = _read_json(base / RECEIPTS / f"{doc['request_id']}.json")
        newest[slot] = {"slot": slot, "last_requested_at": doc["requested_at"], "request_id": doc["request_id"],
                        "receipt_state": rec.get("state") if isinstance(rec, dict) else None}
    return [newest.get(s, {"slot": s, "last_requested_at": None, "request_id": None, "receipt_state": None})
            for s in SLOTS]


def _census(path: Optional[Path]) -> Optional[dict[str, Any]]:
    """open_prs and as_of from the PR-hygiene lane receipt (Phase 1's census source); None when absent."""
    if path is None:
        return None
    doc = _read_json(Path(path))
    summary = (doc or {}).get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("open_prs"), int):
        return None
    return {"open_prs": summary["open_prs"], "as_of": summary.get("as_of") or (doc or {}).get("finished_at")}


# ── relay-facing views ────────────────────────────────────────────────────────────────────────────────────────


def readiness_from_files(
    now: datetime,
    state_dir: Path,
    *,
    cfg: Optional[Mapping[str, Any]] = None,
    policy_path: Optional[Path] = None,
    delegation_state: Optional[Callable[[], tuple[str, str]]] = None,
    census_path: Optional[Path] = None,
) -> dict[str, Any]:
    """ReleaseTrainReadiness@v1. Queue counts are the Command Center API's (Postgres); the gateway holds no DB
    credential, so they are ``null`` / ``UNAVAILABLE`` here, never zero. STOP fails closed. Never raises."""
    try:
        cfg = cfg if cfg is not None else load_config()
    except ContractError as exc:
        return {"schema": READINESS_SCHEMA, "state": "REFUSED", "reason": f"config:{str(exc)[:80]}"}
    try:
        stop_state = read_latch(state_dir)
    except Exception:  # noqa: BLE001 - fail closed
        stop_state = "UNAVAILABLE"
    pol = read_policy(policy_path)
    if delegation_state is not None:
        try:
            dstate, dsrc = delegation_state()
        except Exception:  # noqa: BLE001
            dstate, dsrc = "UNAVAILABLE", "error"
    else:
        dstate, dsrc = declared_delegation_state(), "declared:delegation.json"
    windows = []
    for slot in SLOTS:
        start = window_start(slot, now, cfg)
        pw = policy_window(pol, slot)
        windows.append({"slot": slot, "window_id": window_id(start), "starts_at": start.isoformat(),
                        "enabled": pw["enabled"], "role": pw["role"]})
    return {
        "schema": READINESS_SCHEMA,
        "state": "OK",
        "authority": AUTHORITY,
        "as_of": _iso_utc(now),
        "stop": {"state": stop_state, "effective_stop": stop_state != "ABSENT",
                 "freshness": "OK" if stop_state in LATCH_STATES else "UNAVAILABLE"},
        "armed": (pol.get("armed") is True) if pol is not None else None,
        "shadow_enabled": bool((cfg.get("shadow") or {}).get("enabled") is True),
        "delegation": {"state": dstate if dstate in DELEGATION_STATES else "INVALID", "source": dsrc},
        "policy_version": pol.get("policy_version") if pol is not None else None,
        "windows": windows,
        "queue_counts": None,
        "queue_freshness": "UNAVAILABLE",
        "census": _census(census_path),
        "current_train": None,
        "last_outcome": None,
        "shadow_coverage": shadow_coverage(state_dir),
    }


def window_view(
    state_dir: Path,
    *,
    run_id: Optional[str] = None,
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """ReleaseTrainWindowView@v1 for one request (by Run Lane run_id, or the newest for a slot). Never raises."""
    now = now or datetime.now(timezone.utc)
    if run_id is not None and not RUN_ID_RE.fullmatch(run_id):
        return {"schema": WINDOW_VIEW_SCHEMA, "state": "REFUSED", "reason": "bad_run_id"}
    if slot is not None and not SLOT_RE.fullmatch(slot):
        return {"schema": WINDOW_VIEW_SCHEMA, "state": "REFUSED", "reason": "bad_slot"}
    try:
        state, req, rec, problem = find_request(state_dir, run_id=run_id, slot=slot, now=now)
    except ContractError:
        return {"schema": WINDOW_VIEW_SCHEMA, "state": "REFUSED", "reason": "bad_query"}
    except Exception as exc:  # noqa: BLE001
        return {"schema": WINDOW_VIEW_SCHEMA, "state": "REFUSED", "reason": f"spool:{type(exc).__name__}"}
    return {
        "schema": WINDOW_VIEW_SCHEMA,
        "state": "OK",
        "authority": AUTHORITY,
        "as_of": _iso_utc(now),
        "request_state": state,
        "request": request_projection(req) if req else None,
        "receipt": receipt_projection(rec),
        "receipt_problem": problem,
    }


def gateway_answer(
    request: Mapping[str, Any],
    now: datetime,
    *,
    state_dir: Path,
    census_path: Optional[Path] = None,
    readiness: Optional[Callable[[datetime], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """The gateway's ``release_train_window`` read operation: exactly one of view=readiness, run_id, slot."""
    present = [k for k in QUERY_KEYS if k in request]
    if len(present) != 1:
        return {"state": "REFUSED", "reason": "release_train_window_bad_query"}
    key = present[0]
    value = request[key]
    if not isinstance(value, str):
        return {"state": "REFUSED", "reason": "release_train_window_bad_query"}
    if key == "view":
        if value != "readiness":
            return {"state": "REFUSED", "reason": "release_train_window_bad_query"}
        if readiness is not None:
            return readiness(now)
        return readiness_from_files(now, state_dir, census_path=census_path)
    if key == "run_id":
        return window_view(state_dir, run_id=value, now=now)
    return window_view(state_dir, slot=value, now=now)

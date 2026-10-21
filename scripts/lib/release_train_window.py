"""Release train n8n coordination contract (Release Train v2, Phase 4, 2026-10-21). BUILD ONLY; nothing armed.

Contract: ``docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md``. This module is the host half that n8n may reach, and the
validators the Phase 3 controller uses for the two records it shares with n8n:

    TrainWindowRequest@v1     one request that the controller consider a window (written by the request lane)
    TrainWindowReceipt@v1     the controller's answer (written only by the controller)
    ReleaseTrainReadiness@v1  the read-only view n8n gates and reports on (relay GET /release-train-window?view=readiness)
    ReleaseTrainWindowView@v1 one request + its receipt, by run_id or slot (relay GET /release-train-window?run_id=|slot=)

Trust boundary (AGENTS.md §23.3, §23.14, §23.23, §24.1, §24.5). n8n coordinates only. Nothing here merges, pushes,
promotes, rolls back, issues or reserves a capability, writes the STOP latch or the epoch, sends a message or opens a
network connection. The only write in this module is ``append_request`` (one JSON file created with O_EXCL in the
request spool), and only the request lane calls it, only with ``--append``. Every value that decides what a request
says (window, tick, shadow) is derived here from the host clock, the lane's argv slot, the STOP latch, the policy and
the delegation, never from anything n8n sends: a run request names only a lane and a mode (§23.3).

Pre-build check (AGENTS §13.5): reuses ``release_train_view`` (STOP latch reader, state-dir resolution, the Phase 1
summary), ``release_train_classify.load_policy`` (armed, windows), ``release_train_contracts`` (schema validator
subset) and, when Phase 2 is merged, ``release_delegation.load``. New: the two schemas, the request spool, the
readiness/window projections.

AUTHORITY: READ_ONLY_ADVISORY (a request is REQUEST_ONLY: never authority). MBI_BEHAVIOR = 0.
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
SCHEMA_DIR = ROOT / "config" / "schemas" / "release_train"
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
REQUEST_AUTHORITY = "REQUEST_ONLY"
REQUEST_NOTE = "A request is not authority. The controller re-validates every gate; shadow=true is simulate-only."
SLOTS = ("1800", "0000", "0600", "0800")
LANE_PREFIX = "release-train-request-"
REQUEST_ID_RE = re.compile(r"^rtw-([0-9]{8})-(0000|0600|0800|1800)-(win|f[0-9a-f]{6})$")
SLOT_RE = re.compile(r"^(0000|0600|0800|1800)$")
#: The executor's run id alphabet (scripts/lib/n8n_coordination_gateway.py RUN_ID_RE is the authority at the relay).
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
SPOOL_DIR = "train_requests"
JOURNAL, PENDING, CLAIMED, RECEIPTS = "journal", "pending", "claimed", "receipts"
REQUEST_STATES = ("PENDING", "CLAIMED", "NOT_FOUND")
TERMINAL_RECEIPT_STATES = ("COMPLETED", "REFUSED", "EXPIRED", "FAILED")
DELEGATION_STATES = ("ACTIVE", "PAUSED", "REVOKED", "NOT_CONFIGURED", "INVALID", "UNAVAILABLE")
SHADOW_REASONS = ("off_window", "shadow_only_lane", "train_not_armed", "delegation_not_active", "window_not_enabled")
NO_OP_REASONS = ("stop_set", "stop_unreadable", "not_armed")
#: How many spool files a lookup reads at most (newest first by name; names sort by window date/time).
MAX_SCAN = 400
#: The relay answers in one bounded body; projections keep it small.
NEEDS_ACTION_MAX = 20


class ContractError(ValueError):
    """A config, request or receipt that fails its contract."""


class _NoReleaseWindow:
    """Passed as ``release_window_module`` so the Phase 1 readers use their file reader and the state-dir formula
    instead of importing ``scripts/release_window.py`` (the deployer). Same fail-closed semantics; the n8n-reachable
    host code (this module, the request lane, the gateway view) never loads the deployer."""


NO_RELEASE_WINDOW = _NoReleaseWindow()


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


# ── host readiness (the authoritative re-check the lane makes) ────────────────────────────────────────────────


def _view_module():
    try:
        from lib import release_train_view as V  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.lib import release_train_view as V  # type: ignore[no-redef]
    return V


def _classify_module():
    try:
        from lib import release_train_classify as CLS  # type: ignore
    except ImportError:  # pragma: no cover
        from scripts.lib import release_train_classify as CLS  # type: ignore[no-redef]
    return CLS


def delegation_state(loader: Optional[Callable[[], Any]] = None, fallback: Optional[str] = None) -> tuple[str, str]:
    """(state, source). Phase 2's ``release_delegation.load()`` when importable, mapped to the contract vocabulary;
    else ``fallback`` (the Phase 1 summary's standing_policy state) or NOT_CONFIGURED. Never raises."""
    if loader is None:
        try:
            try:
                from lib import release_delegation as RD  # type: ignore
            except ImportError:
                from scripts.lib import release_delegation as RD  # type: ignore[no-redef]
            loader = RD.load
        except Exception:  # noqa: BLE001 - Phase 2 not merged: the Phase 1 view's state stands
            loader = None
    if loader is None:
        st = fallback if fallback in DELEGATION_STATES else "NOT_CONFIGURED"
        return st, "release_train_view.standing_policy"
    try:
        v = loader()
        code = str(getattr(v, "code", "") or "")
    except Exception:  # noqa: BLE001 - an unreadable verdict is not ACTIVE
        return "UNAVAILABLE", "release_delegation.load"
    mapping = {"AUTHORIZED": "ACTIVE", "MISSING": "NOT_CONFIGURED", "PAUSED": "PAUSED", "REVOKED": "REVOKED"}
    return mapping.get(code, "INVALID"), "release_delegation.load"


def host_snapshot(
    now: datetime,
    slot: str,
    cfg: Mapping[str, Any],
    *,
    stop_dir: Optional[Path] = None,
    policy: Optional[Mapping[str, Any]] = None,
    delegation_loader: Optional[Callable[[], Any]] = None,
    release_window_module: Any = None,
) -> dict[str, Any]:
    """Everything the lane decides on, read now on the host. A read that fails reads as the restrictive value."""
    V = _view_module()
    rw = NO_RELEASE_WINDOW if release_window_module is None else release_window_module
    try:
        stop = V.read_stop(stop_dir, release_window_module=rw)
        stop_state = stop.get("state") if stop.get("state") in V.LATCH_STATES else "UNREADABLE"
    except Exception:  # noqa: BLE001 - fail closed: an unreadable latch is a STOP
        stop_state = "UNREADABLE"
    pol: Optional[Mapping[str, Any]] = policy
    if pol is None:
        try:
            pol = _classify_module().load_policy()
        except Exception:  # noqa: BLE001 - no policy: not armed, no enabled window
            pol = None
    armed = bool(pol.get("armed")) if isinstance(pol, Mapping) and pol.get("armed") is True else False
    hhmm = f"{slot[:2]}:{slot[2:]}"
    window_enabled = False
    if isinstance(pol, Mapping):
        for w in pol.get("windows") or ():
            if isinstance(w, Mapping) and w.get("local_time") == hhmm:
                window_enabled = w.get("enabled") is True
    dstate, _src = delegation_state(delegation_loader)
    return {
        "stop_state": stop_state,
        "armed": armed,
        "shadow_enabled": bool((cfg.get("shadow") or {}).get("enabled") is True),
        "delegation_state": dstate,
        "window_enabled": window_enabled,
        "policy_version": (str(pol.get("policy_version"))[:64] if isinstance(pol, Mapping)
                           and pol.get("policy_version") is not None else None),
    }


def decide(snapshot: Mapping[str, Any], tick: str, *, shadow_only: bool) -> dict[str, Any]:
    """The host gate (contract §5). Returns {disposition: request|no_op, shadow, shadow_reason, no_op_reason}."""
    stop_state = snapshot.get("stop_state")
    if stop_state != "ABSENT":
        reason = "stop_set" if stop_state == "SET" else "stop_unreadable"
        return {"disposition": "no_op", "shadow": None, "shadow_reason": None, "no_op_reason": reason}
    checks = (
        ("off_window", tick == "on_window"),
        ("shadow_only_lane", not shadow_only),
        ("train_not_armed", snapshot.get("armed") is True),
        ("delegation_not_active", snapshot.get("delegation_state") == "ACTIVE"),
        ("window_not_enabled", snapshot.get("window_enabled") is True),
    )
    failed = next((name for name, ok in checks if not ok), None)
    if failed is None:
        return {"disposition": "request", "shadow": False, "shadow_reason": None, "no_op_reason": None}
    if snapshot.get("shadow_enabled") is True:
        return {"disposition": "request", "shadow": True, "shadow_reason": failed, "no_op_reason": None}
    return {"disposition": "no_op", "shadow": None, "shadow_reason": None, "no_op_reason": "not_armed"}


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def build_request(
    slot: str,
    now: datetime,
    cfg: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    decision: Mapping[str, Any],
    *,
    run_id: str,
    attempt: Optional[int],
    run_mode: Optional[str],
    code_sha: Optional[str],
) -> dict[str, Any]:
    """A TrainWindowRequest@v1 for an accepted decision. Raises ContractError for a no-op decision."""
    if decision.get("disposition") != "request":
        raise ContractError("a no-op decision has no request")
    start = window_start(slot, now, cfg)
    tick = tick_kind(start, now, cfg)
    if tick == "on_window":
        expires = start + timedelta(minutes=int(cfg["grace_min"]))
    else:
        expires = now + timedelta(minutes=int(cfg["off_window_expiry_min"]))
    sha = code_sha if isinstance(code_sha, str) and re.fullmatch(r"[0-9a-f]{7,40}", code_sha) else None
    doc = {
        "schema": TRAIN_WINDOW_REQUEST,
        "request_id": request_id_for(slot, start, tick, run_id),
        "window_slot": slot,
        "window_id": window_id(start),
        "window_start": start.isoformat(),
        "tick": tick,
        "shadow": bool(decision["shadow"]),
        "shadow_reason": decision.get("shadow_reason"),
        "requested_at": _iso_utc(now),
        "expires_at": _iso_utc(expires),
        "requested_by": {"lane_id": lane_for_slot(slot), "run_id": run_id[:160],
                         "attempt": attempt if isinstance(attempt, int) and attempt >= 1 else None,
                         "run_mode": run_mode if run_mode in ("live", "dry_run") else None, "code_sha": sha},
        "readiness": {k: snapshot[k] for k in ("stop_state", "armed", "shadow_enabled", "delegation_state",
                                               "window_enabled", "policy_version")},
        "authority": REQUEST_AUTHORITY,
        "note": REQUEST_NOTE,
    }
    errs = validate_request(doc)
    if errs:
        raise ContractError("built request is invalid: " + "; ".join(errs[:5]))
    return doc


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


# ── spool ─────────────────────────────────────────────────────────────────────────────────────────────────────


def spool_dir(state_dir: Optional[Path] = None) -> Path:
    if state_dir is None:
        state_dir, _src = _view_module().resolve_state_dir(NO_RELEASE_WINDOW)
    return Path(state_dir) / SPOOL_DIR


def append_request(doc: Mapping[str, Any], state_dir: Optional[Path] = None) -> tuple[str, Path]:
    """Append one request. Returns ("appended" | "duplicate", path). Never overwrites, never deletes (§0 rule 6).

    1. ``journal/<request_id>.json`` is created with O_EXCL, written and fsynced: the append-only record of every
       request ever made, and the uniqueness check (an on-window id is one per window, so a second on-window request
       for the same window is a ``duplicate``).
    2. ``pending/<request_id>.json`` is a hard link to it, made only after the body is durable, so the controller's
       path unit never sees a partial file. The controller claims by renaming the pending link into ``claimed/``;
       the journal name stays."""
    errs = validate_request(doc)
    if errs:
        raise ContractError("refusing to append an invalid request: " + "; ".join(errs[:5]))
    base = spool_dir(state_dir)
    rid = str(doc["request_id"])
    journal, pending = base / JOURNAL, base / PENDING
    journal.mkdir(parents=True, exist_ok=True)
    pending.mkdir(parents=True, exist_ok=True)
    jpath, final = journal / f"{rid}.json", pending / f"{rid}.json"
    body = (json.dumps(dict(doc), indent=1, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(str(jpath), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return "duplicate", jpath
    with os.fdopen(fd, "wb") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(jpath, final)
    except FileExistsError:
        return "duplicate", final
    for d in (journal, pending):
        dfd = os.open(str(d), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    return "appended", final


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
    """The receipt without ``evidence_refs`` (paths stay on the host), needs_action bounded. None when absent or
    invalid: an invalid receipt is reported as ``receipt_invalid`` by ``window_view``, never passed through."""
    if not doc:
        return None
    out = {k: v for k, v in doc.items() if k != "evidence_refs"}
    out["needs_action"] = list(doc.get("needs_action") or [])[:NEEDS_ACTION_MAX]
    return out


def find_request(
    *,
    run_id: Optional[str] = None,
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
    state_dir: Optional[Path] = None,
) -> tuple[str, Optional[dict], Optional[dict], Optional[str]]:
    """(request_state, request, receipt, receipt_problem) for the newest request matching ``run_id`` or ``slot``
    (a slot matches a window that started within the last 24 h). Read-only."""
    if (run_id is None) == (slot is None):
        raise ContractError("exactly one of run_id or slot")
    now = now or datetime.now(timezone.utc)
    base = spool_dir(state_dir)
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


def shadow_coverage(state_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    """Per slot, the newest shadow request and its receipt state (the manual run's forced-tick choice, contract §10).
    Read-only; an unreadable spool reads as no coverage."""
    base = spool_dir(state_dir)
    newest: dict[str, dict[str, Any]] = {}
    try:
        files = _request_files(base)
    except Exception:  # noqa: BLE001
        files = []
    for _state, path in files:
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


# ── relay-facing views (served by the gateway's read-only release_train_window operation) ─────────────────────


def _null_db(*_a: Any, **_k: Any) -> None:
    return None


def readiness_view(
    now: Optional[datetime] = None,
    *,
    db_query: Optional[Callable[..., Any]] = None,
    cfg: Optional[Mapping[str, Any]] = None,
    stop_dir: Optional[Path] = None,
    delegation_loader: Optional[Callable[[], Any]] = None,
    census_path: Optional[Path] = None,
    release_window_module: Any = None,
    state_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """ReleaseTrainReadiness@v1 from the Phase 1 summary (``build_summary``). The gateway holds no DB credential, so
    by default the queue fields are UNAVAILABLE (never zero). STOP that could not be read is ``UNAVAILABLE`` and
    ``effective_stop`` true. Never raises: any failure is ``state: REFUSED`` with a reason."""
    now = now or datetime.now(timezone.utc)
    try:
        cfg = cfg if cfg is not None else load_config()
    except ContractError as exc:
        return {"schema": READINESS_SCHEMA, "state": "REFUSED", "reason": f"config:{str(exc)[:80]}"}
    V = _view_module()
    try:
        s = V.build_summary(db_query or _null_db, now=now, census_path=census_path, stop_dir=stop_dir,
                            release_window_module=NO_RELEASE_WINDOW if release_window_module is None
                            else release_window_module)
    except Exception as exc:  # noqa: BLE001 - the view must answer, and fail closed
        return {"schema": READINESS_SCHEMA, "state": "REFUSED", "reason": f"summary:{type(exc).__name__}"}
    stop_f = s.get("stop") or {}
    if stop_f.get("freshness") == "OK" and isinstance(stop_f.get("value"), Mapping):
        sv = stop_f["value"]
        stop = {"state": sv.get("state") if sv.get("state") in V.LATCH_STATES else "UNREADABLE",
                "effective_stop": sv.get("state") != "ABSENT", "freshness": "OK"}
    else:
        stop = {"state": "UNAVAILABLE", "effective_stop": True, "freshness": "UNAVAILABLE"}
    armed_f = s.get("armed") or {}
    armed = armed_f.get("value") if armed_f.get("freshness") == "OK" else None
    fallback = ((s.get("standing_policy") or {}).get("value") or {}).get("state")
    dstate, dsrc = delegation_state(delegation_loader, fallback=fallback)
    wins = []
    win_f = s.get("windows") or {}
    for w in (win_f.get("value") or []) if win_f.get("freshness") == "OK" else []:
        lt = str(w.get("local_time") or "")
        wins.append({"slot": lt.replace(":", ""), "window_id": w.get("window_id"), "starts_at": w.get("starts_at"),
                     "enabled": w.get("enabled") is True, "role": w.get("role")})
    counts_f = s.get("queue_counts") or {}
    census_f = s.get("census") or {}
    census_v = census_f.get("value") if isinstance(census_f, Mapping) else None
    census = ({"status": census_v.get("status"), "open_prs": census_v.get("open_prs")}
              if isinstance(census_v, Mapping) else None)
    cur_f, last_f = s.get("current_train") or {}, s.get("last_outcome") or {}
    pol_f = s.get("policy") or {}
    return {
        "schema": READINESS_SCHEMA,
        "state": "OK",
        "authority": AUTHORITY,
        "as_of": s.get("generated_at"),
        "stop": stop,
        "armed": armed if isinstance(armed, bool) else None,
        "shadow_enabled": bool((cfg.get("shadow") or {}).get("enabled") is True),
        "delegation": {"state": dstate, "source": dsrc},
        "policy_version": (pol_f.get("value") or {}).get("policy_version") if pol_f.get("freshness") != "UNAVAILABLE"
        else None,
        "windows": wins,
        "queue_counts": counts_f.get("value") if counts_f.get("freshness") == "OK" else None,
        "queue_freshness": counts_f.get("freshness") or "UNAVAILABLE",
        "census": census,
        "current_train": cur_f.get("value") if cur_f.get("freshness") == "OK" else None,
        "last_outcome": last_f.get("value") if last_f.get("freshness") == "OK" else None,
        "shadow_coverage": shadow_coverage(state_dir),
    }


def window_view(
    *,
    run_id: Optional[str] = None,
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
    state_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """ReleaseTrainWindowView@v1 for one request (by Run Lane run_id, or the newest for a slot). Never raises."""
    now = now or datetime.now(timezone.utc)
    if run_id is not None and not RUN_ID_RE.fullmatch(run_id):
        return {"schema": WINDOW_VIEW_SCHEMA, "state": "REFUSED", "reason": "bad_run_id"}
    if slot is not None and not SLOT_RE.fullmatch(slot):
        return {"schema": WINDOW_VIEW_SCHEMA, "state": "REFUSED", "reason": "bad_slot"}
    try:
        state, req, rec, problem = find_request(run_id=run_id, slot=slot, now=now, state_dir=state_dir)
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


#: The gateway request keys this operation accepts, beyond route/operation/claim/signature: exactly one of these.
QUERY_KEYS = ("view", "run_id", "slot")


def gateway_answer(request: Mapping[str, Any], now: datetime, *, state_dir: Optional[Path] = None,
                   db_query: Optional[Callable[..., Any]] = None) -> dict[str, Any]:
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
        return readiness_view(now, db_query=db_query, state_dir=state_dir)
    if key == "run_id":
        return window_view(run_id=value, now=now, state_dir=state_dir)
    return window_view(slot=value, now=now, state_dir=state_dir)

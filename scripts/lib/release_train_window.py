"""Release train n8n coordination, host half (Release Train v2, Phase 4, 2026-10-21). BUILD ONLY; nothing armed.

Contract: ``docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md``. The records, validators and read-only views live in
``release_train_window_view`` (kept stdlib-only and environment-free because the gateway loads it); this module adds
what only the request lane does, and re-exports the view module's names so callers have one import:

* the host gate: the STOP latch, the policy, the standing delegation (Phase 2's ``release_delegation.load`` when it is
  importable, else the declared status) and the coordination config, read now (``host_snapshot``, ``decide``);
* the request builder (``build_request``) and the only write, ``append_request``: one ``journal/<id>.json`` created
  with O_EXCL plus its ``pending/`` hard link;
* state-dir resolution from the environment, exactly as ``scripts/release_window.py`` resolves it
  (``TRADEAI_RELEASE_WINDOW_STATE_DIR``, else ``$TRADEAI_STATE_ROOT/data/runtime/release_window``), without importing
  the deployer.

Trust boundary (AGENTS.md §23.3, §23.14, §23.23, §24.1, §24.5): every value that decides what a request says (window,
tick, shadow) comes from the host clock, the lane's argv slot and host files, never from n8n (a run request names only a
lane and a mode). Nothing here merges, pushes, promotes, rolls back, issues a capability, writes the STOP latch or sends.

AUTHORITY: READ_ONLY_ADVISORY (a request is REQUEST_ONLY: never authority). MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from lib import release_train_window_view as V
except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
    from scripts.lib import release_train_window_view as V  # type: ignore[no-redef]

# One import for callers: the view module's contract surface.
AUTHORITY = V.AUTHORITY
CLAIMED, JOURNAL, PENDING, RECEIPTS, SPOOL_DIR = V.CLAIMED, V.JOURNAL, V.PENDING, V.RECEIPTS, V.SPOOL_DIR
CONFIG_PATH, CONFIG_SCHEMA = V.CONFIG_PATH, V.CONFIG_SCHEMA
ContractError = V.ContractError
DELEGATION_STATES = V.DELEGATION_STATES
LANE_PREFIX, SLOTS, SLOT_RE, REQUEST_ID_RE, RUN_ID_RE = V.LANE_PREFIX, V.SLOTS, V.SLOT_RE, V.REQUEST_ID_RE, V.RUN_ID_RE
QUERY_KEYS = V.QUERY_KEYS
READINESS_SCHEMA, WINDOW_VIEW_SCHEMA = V.READINESS_SCHEMA, V.WINDOW_VIEW_SCHEMA
TRAIN_WINDOW_RECEIPT, TRAIN_WINDOW_REQUEST = V.TRAIN_WINDOW_RECEIPT, V.TRAIN_WINDOW_REQUEST
lane_for_slot, load_config, validate_config = V.lane_for_slot, V.load_config, V.validate_config
request_id_for, tick_kind, window_id, window_start = V.request_id_for, V.tick_kind, V.window_id, V.window_start
validate_receipt, validate_request, schema_errors = V.validate_receipt, V.validate_request, V.schema_errors

REQUEST_AUTHORITY = "REQUEST_ONLY"
REQUEST_NOTE = "A request is not authority. The controller re-validates every gate; shadow=true is simulate-only."
SHADOW_REASONS = ("off_window", "shadow_only_lane", "train_not_armed", "delegation_not_active", "window_not_enabled")
NO_OP_REASONS = ("stop_set", "stop_unreadable", "not_armed")


# ── host state ────────────────────────────────────────────────────────────────────────────────────────────────


def resolve_state_dir() -> Path:
    """The release-window state dir, resolved as ``scripts/release_window.py`` does (without importing it)."""
    env = os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR")
    if env:
        return Path(env)
    root = os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "runtime" / "release_window"


def spool_dir(state_dir: Optional[Path] = None) -> Path:
    return Path(state_dir if state_dir is not None else resolve_state_dir()) / SPOOL_DIR


def delegation_state(loader: Optional[Callable[[], Any]] = None) -> tuple[str, str]:
    """(state, source). Phase 2's ``release_delegation.load()`` when importable (full validation), mapped to the
    contract vocabulary; else the declared status of the delegation file. Never raises."""
    if loader is None:
        try:
            try:
                from lib import release_delegation as RD  # type: ignore
            except ImportError:
                from scripts.lib import release_delegation as RD  # type: ignore[no-redef]
            loader = RD.load
        except Exception:  # noqa: BLE001 - Phase 2 not merged here: the declared status stands
            return V.declared_delegation_state(), "declared:delegation.json"
    try:
        code = str(getattr(loader(), "code", "") or "")
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
) -> dict[str, Any]:
    """Everything the lane decides on, read now on the host. A read that fails reads as the restrictive value."""
    try:
        stop_state = V.read_latch(stop_dir if stop_dir is not None else resolve_state_dir())
    except Exception:  # noqa: BLE001 - fail closed: an unreadable latch is a STOP
        stop_state = "UNREADABLE"
    pol = policy if policy is not None else V.read_policy()
    dstate, _src = delegation_state(delegation_loader)
    return {
        "stop_state": stop_state,
        "armed": isinstance(pol, Mapping) and pol.get("armed") is True,
        "shadow_enabled": bool((cfg.get("shadow") or {}).get("enabled") is True),
        "delegation_state": dstate,
        "window_enabled": V.policy_window(pol, slot)["enabled"],
        "policy_version": (
            str(pol.get("policy_version"))[:64]
            if isinstance(pol, Mapping) and pol.get("policy_version") is not None
            else None
        ),
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
        "requested_at": now.astimezone(timezone.utc).isoformat(),
        "expires_at": expires.astimezone(timezone.utc).isoformat(),
        "requested_by": {
            "lane_id": lane_for_slot(slot),
            "run_id": run_id[:160],
            "attempt": attempt if isinstance(attempt, int) and attempt >= 1 else None,
            "run_mode": run_mode if run_mode in ("live", "dry_run") else None,
            "code_sha": sha,
        },
        "readiness": {
            k: snapshot[k]
            for k in ("stop_state", "armed", "shadow_enabled", "delegation_state", "window_enabled", "policy_version")
        },
        "authority": REQUEST_AUTHORITY,
        "note": REQUEST_NOTE,
    }
    errs = validate_request(doc)
    if errs:
        raise ContractError("built request is invalid: " + "; ".join(errs[:5]))
    return doc


INJECTION_SCHEMA = "TrainInjection@v1"
INJECTIONS = ("red-check", "conflict", "stop-midrun", "corrupt-latch", "crash")


def write_injection(doc: Mapping[str, Any], inject: str, state_dir: Optional[Path] = None) -> Path:
    """Operator drill (arming finding 5): ``injections/<request_id>.json`` (TrainInjection@v1, O_EXCL, mode 600)
    naming ONE simulated failure for a SHADOW request. Written before the request is appended, so the claimer always
    sees it. Never for a live request (refused here and again by the claimer); never overwritten or deleted."""
    if inject not in INJECTIONS:
        raise ContractError(f"unknown injection {inject!r}")
    if doc.get("shadow") is not True:
        raise ContractError("--inject is for shadow requests only")
    d = spool_dir(state_dir) / "injections"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{doc['request_id']}.json"
    body = {
        "schema": INJECTION_SCHEMA,
        "request_id": doc["request_id"],
        "inject": inject,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "operator_cli",
    }
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(body, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return p


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


# ── views with environment defaults (the lane, tests and operator tooling; the gateway calls the view module) ──


def _state(state_dir: Optional[Path]) -> Path:
    return Path(state_dir) if state_dir is not None else resolve_state_dir()


def find_request(
    *,
    run_id: Optional[str] = None,
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
    state_dir: Optional[Path] = None,
):
    return V.find_request(_state(state_dir), run_id=run_id, slot=slot, now=now)


def shadow_coverage(state_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    return V.shadow_coverage(_state(state_dir))


def window_view(
    *,
    run_id: Optional[str] = None,
    slot: Optional[str] = None,
    now: Optional[datetime] = None,
    state_dir: Optional[Path] = None,
) -> dict[str, Any]:
    return V.window_view(_state(state_dir), run_id=run_id, slot=slot, now=now)


def readiness_view(
    now: Optional[datetime] = None,
    *,
    cfg: Optional[Mapping[str, Any]] = None,
    stop_dir: Optional[Path] = None,
    delegation_loader: Optional[Callable[[], Any]] = None,
    census_path: Optional[Path] = None,
    state_dir: Optional[Path] = None,
    policy_path: Optional[Path] = None,
) -> dict[str, Any]:
    """ReleaseTrainReadiness@v1 with the lane's delegation reader (Phase 2 loader when importable)."""
    sdir = _state(stop_dir if stop_dir is not None else state_dir)
    return V.readiness_from_files(
        now or datetime.now(timezone.utc),
        sdir,
        cfg=cfg,
        policy_path=policy_path,
        delegation_state=lambda: delegation_state(delegation_loader),
        census_path=census_path,
    )


def gateway_answer(request: Mapping[str, Any], now: datetime, *, state_dir: Optional[Path] = None) -> dict[str, Any]:
    return V.gateway_answer(request, now, state_dir=_state(state_dir))

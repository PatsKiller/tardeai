"""Wave C — heavy CC jobs via host_run_request (advisory / analyst / brief).

Env gate ``TRADEAI_N8N_CC_WAVE_C_MODE``:
  * ``off`` (default) — keep prior Thread / sync behaviour (CURRENT-safe)
  * ``dry_run`` — enqueue allowlisted lane with mode=dry_run (prove path; no paid LLM)
  * ``apply`` — enqueue with mode=live (executor stage-clamps shadow → dry_run)

AUTHORITY: READ_ONLY_ADVISORY. No send, no broker, no n8n messaging (§23 / §24.1).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

WAVE_C_MODE_ENV = "TRADEAI_N8N_CC_WAVE_C_MODE"
WAVE_C_MODES = frozenset({"off", "dry_run", "apply"})
DEFAULT_MODE = "off"
AUTHORITY = "READ_ONLY_ADVISORY"
REQUEST_DIR_REL = "data/runtime/n8n_cc_wave_c/requests"
CALLER_ID = "tradeai-cc-wave-c"
REQUESTED_BY = "host:cc-wave-c"

LANE_ADVISORY = "advisory-desk-run-now"
LANE_ANALYST = "analyst-prospectus-generate"
LANE_BRIEF = "aegis-brief-regenerate"

# Legacy Ops Run buttons — prefer refuse; retarget only when the lane is allowlisted.
LEGACY_RUN_DISPOSITION: dict[str, dict[str, Any]] = {
    "/api/run-portfolio": {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": "portfolio-daily-cadence",
        "http_status": 409,
        "reason": "legacy_thread_spawn_disabled; portfolio-daily-cadence is pending_tranches.N2 (not runnable)",
    },
    "/api/run-trade-ai": {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": None,
        "http_status": 410,
        "reason": "legacy_thread_spawn_disabled; no safe allowlisted lane for run_continuous.sh",
    },
    "/api/run-aegis": {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": None,
        "http_status": 410,
        "reason": "legacy_thread_spawn_disabled; aegis_overnight is not an allowlisted host_run lane",
    },
    "/api/run-pipeline": {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": None,
        "http_status": 410,
        "reason": "legacy_thread_spawn_disabled; pipeline launchers are not allowlisted for CC Run buttons",
    },
    "/api/run-recovery-review": {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": None,
        "http_status": 410,
        "reason": "legacy_thread_spawn_disabled; recovery_watch_daily is not an allowlisted host_run lane",
    },
    "/api/run-reprice": {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": None,
        "http_status": 410,
        "reason": "legacy_thread_spawn_disabled; reprice launcher is not an allowlisted host_run lane",
    },
}


def wave_c_mode(env: Mapping[str, str] | None = None) -> str:
    e = env if env is not None else os.environ
    raw = str(e.get(WAVE_C_MODE_ENV) or DEFAULT_MODE).strip().lower()
    if raw in {"0", "false", "no", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "live"}:
        return "apply"
    return raw if raw in WAVE_C_MODES else DEFAULT_MODE


def state_root(env: Mapping[str, str] | None = None) -> Path:
    e = env if env is not None else os.environ
    return Path(e.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def ledger_path(root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    e = env if env is not None else os.environ
    explicit = e.get("TRADEAI_N8N_COORDINATION_LEDGER")
    if explicit:
        return Path(explicit)
    return (root or state_root(e)) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def allowlist_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "n8n_run_allowlist.json"


def load_allowlist(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or allowlist_path()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return {str(x.get("lane_id")): x for x in (doc.get("lanes") or []) if x.get("lane_id")}


def mint_run_id(lane_id: str) -> str:
    """Gateway RUN_ID_RE: 16–128 of [A-Za-z0-9._:-]; must not start with d:/e:/g:."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:12]
    return f"wc:{lane_id}:{stamp}:{suffix}"[:128]


def write_request_payload(lane_id: str, payload: Mapping[str, Any], *, root: Path | None = None) -> Path:
    root = root or state_root()
    dest = root / REQUEST_DIR_REL / f"{lane_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "N8nCcWaveCRequest@v1",
        "lane_id": lane_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": AUTHORITY,
        "payload": dict(payload),
    }
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest


def read_request_payload(lane_id: str, *, root: Path | None = None) -> dict[str, Any]:
    root = root or state_root()
    path = root / REQUEST_DIR_REL / f"{lane_id}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    payload = doc.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _rw_store(ledger: Path):
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

    return LedgerRunStore(CoordinationLedger(ledger))


def enqueue_host_run(
    *,
    lane_id: str,
    mode: str,
    run_id: str | None = None,
    requested_by: str = REQUESTED_BY,
    caller_id: str = CALLER_ID,
    allowlist: Mapping[str, Any] | None = None,
    ledger: Path | None = None,
    now: float | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Enqueue via gateway ``host_run_request`` (same validation as n8n failure-diagnosis reruns)."""
    from scripts.lib import n8n_coordination_gateway as G

    allow = dict(allowlist) if allowlist is not None else load_allowlist()
    if lane_id not in allow:
        return {
            "ok": False,
            "accepted": False,
            "state": "REFUSED",
            "reason": "lane_not_allowlisted",
            "lane_id": lane_id,
            "authority": AUTHORITY,
        }
    entry = allow[lane_id]
    arg_key = "dry_run_arg" if mode == "dry_run" else "live_arg"
    if entry.get(arg_key) is None:
        return {
            "ok": False,
            "accepted": False,
            "state": "REFUSED",
            "reason": f"mode_unavailable:{mode}",
            "lane_id": lane_id,
            "authority": AUTHORITY,
        }
    rid = run_id or mint_run_id(lane_id)
    ts = float(now if now is not None else time.time())
    run_store = store if store is not None else _rw_store(ledger or ledger_path())
    env = G.host_run_request(
        lane_id=lane_id,
        mode=mode,
        run_id=rid,
        requested_by=requested_by,
        caller_id=caller_id,
        run_store=run_store,
        run_allowlist=frozenset(allow),
        now=ts,
    )
    if env.get("state") == "REFUSED":
        return {
            "ok": False,
            "accepted": False,
            "state": "REFUSED",
            "reason": env.get("reason"),
            "run_id": rid,
            "lane_id": lane_id,
            "mode": mode,
            "authority": AUTHORITY,
            "ledger": str(ledger or ledger_path()),
        }
    return {
        "ok": True,
        "accepted": True,
        "state": env.get("state") or "REQUESTED",
        "run_id": rid,
        "lane_id": lane_id,
        "mode": mode,
        "duplicate": bool(env.get("duplicate")),
        "authority": AUTHORITY,
        "financial_action": False,
        "broker_write_authority": "NONE",
        "ledger": str(ledger or ledger_path()),
        "http_status": 202,
    }


def enqueue_for_wave_c_mode(
    *,
    lane_id: str,
    payload: Mapping[str, Any] | None = None,
    mode: str | None = None,
    root: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Resolve Wave C mode and enqueue. ``off`` returns skipped (caller keeps legacy path)."""
    resolved = mode or wave_c_mode()
    out: dict[str, Any] = {
        "ok": True,
        "wave_c_mode": resolved,
        "lane_id": lane_id,
        "authority": AUTHORITY,
    }
    if resolved == "off":
        out["skipped"] = True
        out["accepted"] = False
        out["reason"] = "wave_c_mode_off"
        return out
    if payload:
        path = write_request_payload(lane_id, payload, root=root)
        out["request_path"] = str(path)
    run_mode = "dry_run" if resolved == "dry_run" else "live"
    got = enqueue_host_run(lane_id=lane_id, mode=run_mode, **kwargs)
    got["wave_c_mode"] = resolved
    return got


def legacy_run_refuse(path: str, *, allowlist: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """JSON refuse (or retarget) for legacy portfolio_server Run buttons."""
    meta = LEGACY_RUN_DISPOSITION.get(path) or {
        "disposition": "refuse_until_allowlisted",
        "mapped_lane": None,
        "http_status": 410,
        "reason": "legacy_thread_spawn_disabled",
    }
    allow = allowlist if allowlist is not None else load_allowlist()
    mapped = meta.get("mapped_lane")
    if mapped and mapped in allow:
        # Prefer retarget only when a full allowlist entry exists (not pending_tranches).
        got = enqueue_for_wave_c_mode(lane_id=str(mapped), mode="apply")
        if got.get("accepted"):
            return 202, {
                "ok": True,
                "accepted": True,
                "disposition": "retarget_host_run",
                "mapped_lane": mapped,
                "run_id": got.get("run_id"),
                "lane_id": mapped,
                "authority": AUTHORITY,
                "message": f"Enqueued via host_run_request on {mapped}",
            }
        # Fall through to refuse if enqueue failed (e.g. mode off / busy).
    status = int(meta.get("http_status") or 409)
    return status, {
        "ok": False,
        "accepted": False,
        "disposition": meta.get("disposition"),
        "mapped_lane": mapped,
        "mapped_lane_allowlisted": bool(mapped and mapped in allow),
        "reason": meta.get("reason"),
        "authority": AUTHORITY,
        "financial_action": False,
        "broker_write_authority": "NONE",
        "message": (
            "Legacy Run button disabled: Thread/subprocess spawn removed (Wave C). "
            "Use an allowlisted coordination/run lane or the scheduled host cadence."
        ),
    }


def write_lane_receipt(
    lane_id: str,
    *,
    ok: bool,
    mode: str,
    detail: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> Path:
    root = root or state_root()
    rel = f"data/runtime/{lane_id}_last.json"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "schema": "LaneRunReceipt@v1",
        "lane_id": lane_id,
        "authority": AUTHORITY,
        "mode": mode,
        "ok": ok,
        "ok_at": now if ok else None,
        "as_of": now,
        "financial_action": False,
        "broker_write_authority": "NONE",
        **(dict(detail) if detail else {}),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path

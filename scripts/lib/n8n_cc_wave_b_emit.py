"""Wave B Command Center → coordination ledger emit helpers (additive shadow first).

Hooks from RI run-topic, CIO NEED_DATA, and watch-decision-refresh call these. Default mode
is ``dry_run``: write sidecars + a last.json spotlight under the state root, post nothing.
``apply`` also posts ``accept_event`` (fail-soft). ``off`` is a no-op.

AUTHORITY: READ_ONLY_ADVISORY. No send, no broker, no LLM. n8n never sends (§24.1).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.lib import n8n_research_intake as ri
from scripts.lib import n8n_watch_refresh_events as wr
from scripts.lib.n8n_pilot_observations import served_sha, state_root

EMIT_MODE_ENV = "TRADEAI_N8N_CC_EMIT_MODE"
EMIT_MODES = frozenset({"off", "dry_run", "apply"})
DEFAULT_MODE = "dry_run"
SPOTLIGHT_REL = "data/runtime/n8n_cc_wave_b/spotlights.json"
AUTHORITY = "READ_ONLY_ADVISORY"


def emit_mode(env: Mapping[str, str] | None = None) -> str:
    e = env if env is not None else os.environ
    raw = str(e.get(EMIT_MODE_ENV) or DEFAULT_MODE).strip().lower()
    if raw in {"0", "false", "no", "disabled"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "live"}:
        return "apply"
    return raw if raw in EMIT_MODES else DEFAULT_MODE


def _write_json(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(doc), indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _update_spotlight(root: Path, *, lane_id: str, entry: Mapping[str, Any]) -> None:
    path = root / SPOTLIGHT_REL
    try:
        cur = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    lanes = cur.get("lanes") if isinstance(cur.get("lanes"), dict) else {}
    lanes[lane_id] = dict(entry)
    doc = {
        "schema": "N8nCcWaveBSpotlights@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": AUTHORITY,
        "lanes": lanes,
    }
    _write_json(path, doc)


def _post(event: Mapping[str, Any], *, client: Any | None) -> dict[str, Any]:
    if client is None:
        from scripts.lib.n8n_gateway_client import GatewayClient

        client = GatewayClient(caller_id="tradeai-cc-wave-b")
    try:
        return client.accept_event(event)
    except Exception as exc:  # fail-soft: never break the CC path
        return {"state": "REFUSED", "reason": f"emit_error:{type(exc).__name__}", "durable": False}


def emit_research_intake(
    *,
    subject: str,
    request_type: str = "topic",
    requested_by: str = "operator",
    reason: str = "",
    priority: str = "P2",
    client: Any | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Shadow/apply a research_request/v1 event for RI run-topic / NEED_DATA side-effects."""
    mode = mode or emit_mode()
    out: dict[str, Any] = {"ok": True, "mode": mode, "lane_id": ri.LANE, "authority": AUTHORITY}
    if mode == "off":
        out["skipped"] = True
        return out
    now = now or datetime.now(timezone.utc)
    sha = served_sha() or ""
    try:
        event, sidecar = ri.build_request(
            subject=subject,
            request_type=request_type,
            requested_by=requested_by,
            reason=reason or f"cc wave-b {request_type}",
            priority=priority,
            origin_sha=sha,
            now=now,
        )
    except ri.RequestError as exc:
        out.update(ok=False, state="REFUSED", reason=exc.reason)
        return out
    root = root or state_root()
    side_path = root / "data" / "runtime" / ri.sidecar_rel(event["idempotency_key"])
    _write_json(side_path, sidecar)
    out.update(
        idempotency_key=event["idempotency_key"],
        event_id=event["event_id"],
        sidecar_path=str(side_path),
        subject=subject,
        request_type=request_type,
    )
    gateway: dict[str, Any] = {"state": "DRY_RUN", "reason": "emit_mode_dry_run", "durable": False}
    if mode == "apply":
        gateway = _post(event, client=client)
    out["gateway"] = {k: gateway.get(k) for k in ("state", "reason", "duplicate", "durable")}
    _update_spotlight(
        root,
        lane_id=ri.LANE,
        entry={
            "lane_id": ri.LANE,
            "kind": "research_intake",
            "mode": mode,
            "idempotency_key": event["idempotency_key"],
            "event_id": event["event_id"],
            "subject": subject,
            "request_type": request_type,
            "requested_by": requested_by,
            "gateway_state": out["gateway"].get("state"),
            "as_of": now.isoformat(),
            "sidecar": str(side_path),
        },
    )
    return out


def emit_watch_refresh(
    *,
    run_id: int | str,
    phase: str,
    symbols: list[str] | None = None,
    terminal_state: str = "",
    requested_by: str = "operator",
    reason: str = "",
    client: Any | None = None,
    root: Path | None = None,
    now: datetime | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Shadow/apply a watch_refresh_lifecycle/v1 event (start or terminal)."""
    mode = mode or emit_mode()
    out: dict[str, Any] = {"ok": True, "mode": mode, "lane_id": wr.LANE, "authority": AUTHORITY}
    if mode == "off":
        out["skipped"] = True
        return out
    now = now or datetime.now(timezone.utc)
    sha = served_sha() or ""
    try:
        event, sidecar = wr.build_event(
            run_id=run_id,
            phase=phase,
            origin_sha=sha,
            symbols=symbols,
            terminal_state=terminal_state,
            requested_by=requested_by,
            reason=reason,
            now=now,
        )
    except wr.WatchRefreshEventError as exc:
        out.update(ok=False, state="REFUSED", reason=exc.reason)
        return out
    root = root or state_root()
    side_path = root / "data" / "runtime" / wr.sidecar_rel(event["idempotency_key"])
    _write_json(side_path, sidecar)
    out.update(
        idempotency_key=event["idempotency_key"],
        event_id=event["event_id"],
        sidecar_path=str(side_path),
        run_id=int(run_id),
        phase=phase,
        terminal_state=str(terminal_state or "").upper() or None,
    )
    gateway: dict[str, Any] = {"state": "DRY_RUN", "reason": "emit_mode_dry_run", "durable": False}
    if mode == "apply":
        gateway = _post(event, client=client)
    out["gateway"] = {k: gateway.get(k) for k in ("state", "reason", "duplicate", "durable")}
    _update_spotlight(
        root,
        lane_id=wr.LANE,
        entry={
            "lane_id": wr.LANE,
            "kind": "watch_refresh",
            "mode": mode,
            "idempotency_key": event["idempotency_key"],
            "event_id": event["event_id"],
            "run_id": int(run_id),
            "phase": phase,
            "terminal_state": out.get("terminal_state"),
            "gateway_state": out["gateway"].get("state"),
            "as_of": now.isoformat(),
            "sidecar": str(side_path),
        },
    )
    return out


def safe_emit_research_intake(**kwargs: Any) -> dict[str, Any]:
    try:
        return emit_research_intake(**kwargs)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:200], "authority": AUTHORITY}


def safe_emit_watch_refresh(**kwargs: Any) -> dict[str, Any]:
    try:
        return emit_watch_refresh(**kwargs)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"[:200], "authority": AUTHORITY}

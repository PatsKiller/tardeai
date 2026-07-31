"""Operator-only bounded dispatch HTTP surface (SHADOW / LAB).

Separate from the zero-authority read plane. Invokes the same
``run_bounded_batch`` entrypoint as ``run_once.py --once``.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Tuple

from .readiness import (
    DEFAULT_ENABLE_FILE,
    DISPATCH_DSN_ENV,
    ENABLE_FILE_ENV,
    OPERATOR_AUTH_ENV,
    PROVIDER_MODULE_ENV,
    QUEUE_MODULE_ENV,
    _dispatch_state,
    _enable_file,
    _truthy,
)

DISPATCH_PATH = "/api/v3/agent-runtime/dispatch"
DISPATCH_CONTRACT = "agent-runtime-operator-dispatch-v1"
RATE_LIMIT_SECONDS = 60
MAX_BATCH_CAP = 8

_LOCK = threading.Lock()
_LAST_DISPATCH: dict[str, float] = {}


def _audit_log(root: Path, record: Mapping[str, Any]) -> None:
    log_dir = root / "state" / "agent_runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "dispatch_audit.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(record), default=str) + "\n")


def _rate_limited(agent_id: str) -> bool:
    now = time.time()
    with _LOCK:
        last = _LAST_DISPATCH.get(agent_id, 0)
        if now - last < RATE_LIMIT_SECONDS:
            return True
        _LAST_DISPATCH[agent_id] = now
    return False


def _dispatch_blocker(env: Mapping[str, str]) -> str | None:
    if not _truthy(env, OPERATOR_AUTH_ENV):
        return "AGENT_RUNTIME_OPERATOR_AUTH is not set"
    if _dispatch_state(env) != "WIRED":
        return f"dispatch not wired ({_dispatch_state(env)})"
    if not str(env.get(DISPATCH_DSN_ENV, "")).strip():
        return "missing dispatch DSN"
    if not str(env.get(PROVIDER_MODULE_ENV, "")).strip():
        return "missing provider module"
    if not str(env.get(QUEUE_MODULE_ENV, "")).strip():
        return "missing queue module"
    if not _enable_file(env).exists():
        return f"kill switch off ({env.get(ENABLE_FILE_ENV, DEFAULT_ENABLE_FILE)})"
    return None


def dispatch_post(
    body: Mapping[str, Any] | None,
    *,
    root: Path,
    env: Mapping[str, str] | None = None,
) -> Tuple[int, dict[str, Any]]:
    env = os.environ if env is None else env
    blocker = _dispatch_blocker(env)
    if blocker:
        return 403, {
            "contract": DISPATCH_CONTRACT,
            "detail": blocker,
            "authority": {"mutation": True, "financial_action": False, "schedule_change": False},
        }

    agent_id = str((body or {}).get("agent_id") or "").strip()
    if not agent_id:
        return 400, {"contract": DISPATCH_CONTRACT, "detail": "agent_id required"}

    try:
        max_batch = int((body or {}).get("max_batch") or 1)
    except (TypeError, ValueError):
        return 400, {"contract": DISPATCH_CONTRACT, "detail": "max_batch must be an integer"}
    max_batch = max(1, min(max_batch, MAX_BATCH_CAP))

    from agent_runtime.agents.definitions import FLEET

    if agent_id not in FLEET:
        return 404, {"contract": DISPATCH_CONTRACT, "detail": f"unknown agent: {agent_id}"}
    spec = FLEET[agent_id]
    if not spec.is_operable_now:
        return 403, {"contract": DISPATCH_CONTRACT, "detail": f"{agent_id} is not SHADOW-operable"}

    if _rate_limited(agent_id):
        return 429, {
            "contract": DISPATCH_CONTRACT,
            "detail": f"rate limited: wait {RATE_LIMIT_SECONDS}s between dispatches per agent",
        }

    dispatch_id = f"dispatch_{uuid.uuid4().hex}"
    try:
        import agent_runtime_dispatch_boot as boot

        summary = boot.run_bounded_batch(agent_id, max_batch)
    except Exception as exc:
        _audit_log(root, {
            "dispatch_id": dispatch_id,
            "agent_id": agent_id,
            "max_batch": max_batch,
            "ok": False,
            "error": str(exc),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        return 500, {"contract": DISPATCH_CONTRACT, "detail": "dispatch failed"}

    run_ids: list[str] = []
    _audit_log(root, {
        "dispatch_id": dispatch_id,
        "agent_id": agent_id,
        "max_batch": max_batch,
        "ok": True,
        "outcomes": summary.get("outcomes"),
        "run_ids": run_ids,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    return 200, {
        "contract": DISPATCH_CONTRACT,
        "dispatch_id": dispatch_id,
        "agent_id": agent_id,
        "max_batch": max_batch,
        "outcomes": summary.get("outcomes") or {},
        "run_ids": run_ids,
        "detail": "bounded SHADOW dispatch completed",
        "authority": {"mutation": True, "financial_action": False, "schedule_change": False},
    }

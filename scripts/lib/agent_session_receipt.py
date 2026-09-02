"""Mandatory agent session receipt (SOP Stage 3)."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_clients_registry import get_client, mutating_allowed
from scripts.lib.agent_file_lease import HEARTBEAT_S, LeaseCoordinator, coordination_root

SCHEMA = "AgentSessionReceipt@v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True).strip()


def build_receipt(
    *,
    agent_id: str,
    repo_root: Path,
    claimed_paths: list[str],
    claimed_stores: list[str] | None = None,
    docs_read: list[str] | None = None,
    docs_searched: list[str] | None = None,
    mode: str = "read_only",
    task_scope: str = "",
    acknowledge_dirty: bool = False,
    parent_session_id: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    client = get_client(agent_id)
    base_sha = _git(["rev-parse", "HEAD"], root)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    dirty = _git(["status", "--porcelain"], root)
    dirty_lines = [ln for ln in dirty.splitlines() if ln.strip()]
    try:
        hooks_path = _git(["config", "--get", "core.hooksPath"], root)
    except Exception:  # noqa: BLE001
        hooks_path = ""
    common = Path(_git(["rev-parse", "--git-common-dir"], root)).resolve()
    hub = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild").resolve()
    is_hub = root == hub

    denials = {
        "remote_sync": True,
        "deployment": True,
        "production": True,
        "financial": True,
    }
    mutating = mode == "mutating"
    errors: list[str] = []
    if mutating:
        if client.get("unknown") or client.get("enforcement_level") != "MECHANICAL":
            errors.append("ADVISORY_OR_UNKNOWN_CLIENT_CANNOT_MUTATE")
        if is_hub:
            errors.append("CANONICAL_HUB_MUTATION_DENIED")
        if not hooks_path:
            errors.append("HOOKS_PATH_MISSING")
        if not base_sha:
            errors.append("BASE_SHA_UNPROVEN")
        if dirty_lines and not acknowledge_dirty:
            errors.append("DIRTY_UNACKNOWLEDGED")
        if not docs_read:
            errors.append("DOCUMENTATION_ATTESTATION_INCOMPLETE")

    session_id = str(uuid.uuid4())
    now = _now()
    receipt = {
        "schema": SCHEMA,
        "receipt_version": "1.0.0",
        "session_id": session_id,
        "agent_id": client.get("agent_id"),
        "adapter_version": client.get("adapter_version"),
        "enforcement_level": client.get("enforcement_level"),
        "task_scope": task_scope,
        "authority_ceiling": "READ_ONLY_ADVISORY" if not mutating else "MUTATING_LOCAL_ONLY",
        "mode": mode,
        "repository": "PatsKiller/tardeai",
        "base_sha": base_sha,
        "branch": branch,
        "worktree_path": str(root),
        "claimed_paths": list(claimed_paths),
        "claimed_stores": list(claimed_stores or []),
        "documentation_searched": list(docs_searched or []),
        "documentation_read": list(docs_read or []),
        "hook_installation": {"core.hooksPath": hooks_path or None},
        "dirty_before": dirty_lines,
        "lease": None,
        "parent_session_id": parent_session_id,
        "denials": denials,
        "errors": errors,
        "ok": not errors,
        "issued_at": now.replace(microsecond=0).isoformat(),
        "heartbeat_interval_s": HEARTBEAT_S,
        "git_common_dir": str(common),
    }
    return receipt


def start_session(
    *,
    agent_id: str,
    repo_root: Path,
    claimed_paths: list[str],
    claimed_stores: list[str] | None = None,
    docs_read: list[str] | None = None,
    docs_searched: list[str] | None = None,
    mode: str = "read_only",
    task_scope: str = "",
    acknowledge_dirty: bool = False,
    coordination_root_path: Path | None = None,
) -> dict[str, Any]:
    receipt = build_receipt(
        agent_id=agent_id,
        repo_root=repo_root,
        claimed_paths=claimed_paths,
        claimed_stores=claimed_stores,
        docs_read=docs_read,
        docs_searched=docs_searched,
        mode=mode,
        task_scope=task_scope,
        acknowledge_dirty=acknowledge_dirty,
    )
    if not receipt["ok"]:
        return receipt
    if mode == "mutating" and claimed_paths:
        coord = LeaseCoordinator(root=coordination_root_path) if coordination_root_path else LeaseCoordinator()
        try:
            lease = coord.acquire(
                session_id=receipt["session_id"],
                agent_id=str(receipt["agent_id"]),
                paths=claimed_paths,
                stores=claimed_stores or [],
            )
            receipt["lease"] = lease.to_dict()
        except Exception as e:  # noqa: BLE001
            receipt["ok"] = False
            receipt["errors"] = list(receipt.get("errors") or []) + [f"LEASE_REFUSED:{e}"]
            return receipt
    # Persist receipt host-locally
    store = coordination_root_path or coordination_root(receipt["git_common_dir"])
    receipts = Path(store) / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    path = receipts / f"{receipt['session_id']}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    receipt["receipt_path"] = str(path)
    return receipt

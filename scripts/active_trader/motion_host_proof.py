"""Data-only proof harness for the deployed Active Trader motion read path.

This command does not install, enable, restart, or mutate a service. It verifies an
already-running deployment by checking runtime heartbeat/state, journal freshness,
the direct read contract, optional HTTP GET parity, and byte-for-byte GET-no-write
behavior. Restart recovery can be asserted after an operator-controlled service restart
with ``--require-restored-state`` and ``--previous-pid``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Optional

from .motion_api import MOTION_CONTRACT, motion_snapshot
from .motion_journal import resolve_path
from .motion_runtime import RUNTIME_HEARTBEAT_CONTRACT, RUNTIME_STATE_CONTRACT


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _file_fingerprint(path: Path) -> Optional[dict[str, Any]]:
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _http_get_json(url: str, timeout_s: float) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    request = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8")
            if response.status != 200:
                return None, f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        body = json.loads(raw)
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"
    return (body if isinstance(body, dict) else None), None


def run_proof(
    *,
    journal_path: Path,
    heartbeat_path: Path,
    state_path: Path,
    endpoint: Optional[str],
    max_age_s: float,
    timeout_s: float,
    require_restored_state: bool,
    previous_pid: Optional[int],
    now: Optional[float] = None,
) -> dict[str, Any]:
    current = time.time() if now is None else float(now)
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    heartbeat = _read_json(heartbeat_path)
    state = _read_json(state_path)
    before = _file_fingerprint(journal_path)

    checks["journal_exists"] = before is not None
    checks["heartbeat_contract"] = bool(
        heartbeat and heartbeat.get("contract") == RUNTIME_HEARTBEAT_CONTRACT
    )
    checks["heartbeat_healthy"] = bool(heartbeat and heartbeat.get("status") == "healthy")
    checks["state_contract"] = bool(state and state.get("contract") == RUNTIME_STATE_CONTRACT)

    last_success = _finite(heartbeat.get("last_success_at")) if heartbeat else None
    heartbeat_age = None if last_success is None else max(0.0, current - last_success)
    checks["heartbeat_fresh"] = heartbeat_age is not None and heartbeat_age <= max_age_s
    details["heartbeat_age_s"] = heartbeat_age
    details["runtime_pid"] = heartbeat.get("pid") if heartbeat else None
    details["process_started_at"] = heartbeat.get("process_started_at") if heartbeat else None

    authority = heartbeat.get("authority") if heartbeat else None
    checks["zero_authority"] = bool(
        isinstance(authority, Mapping) and authority and not any(bool(v) for v in authority.values())
    )
    checks["write_scope_bounded"] = bool(
        heartbeat
        and heartbeat.get("write_scope") == "motion_journal_and_runtime_metadata_only"
    )

    if require_restored_state:
        checks["restart_state_restored"] = bool(heartbeat and heartbeat.get("restored_state") is True)
    if previous_pid is not None:
        current_pid = heartbeat.get("pid") if heartbeat else None
        checks["process_restarted"] = isinstance(current_pid, int) and current_pid != previous_pid

    direct = motion_snapshot(path=journal_path, now=current, max_age_s=max_age_s)
    checks["direct_contract"] = direct.get("contract") == MOTION_CONTRACT
    checks["direct_fresh"] = direct.get("stale") is False and direct.get("data_state") == "LIVE_DATA"
    checks["direct_read_only"] = direct.get("read_only") is True and direct.get("write") is False
    direct_authority = direct.get("authority")
    checks["direct_zero_authority"] = bool(
        isinstance(direct_authority, Mapping)
        and direct_authority
        and not any(bool(v) for v in direct_authority.values())
    )

    http_body: Optional[dict[str, Any]] = None
    http_error: Optional[str] = None
    if endpoint:
        http_body, http_error = _http_get_json(endpoint, timeout_s)
        checks["http_get_200_json"] = http_body is not None
        checks["http_contract"] = bool(http_body and http_body.get("contract") == MOTION_CONTRACT)
        checks["http_fresh"] = bool(http_body and http_body.get("stale") is False)
        checks["http_read_only"] = bool(
            http_body and http_body.get("read_only") is True and http_body.get("write") is False
        )
        details["http_error"] = http_error

    after = _file_fingerprint(journal_path)
    checks["get_performed_no_journal_write"] = before is not None and before == after
    details["journal_before"] = before
    details["journal_after"] = after
    details["snapshot_generated_at"] = direct.get("generated_at")
    details["heartbeat"] = heartbeat

    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "details": details,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument(
        "--heartbeat",
        type=Path,
        default=Path("data/active_trader/motion_runtime_heartbeat.json"),
    )
    parser.add_argument(
        "--state", type=Path, default=Path("data/active_trader/motion_runtime_state.json")
    )
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--max-age-s", type=float, default=60.0)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--require-restored-state", action="store_true")
    parser.add_argument("--previous-pid", type=int, default=None)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_proof(
        journal_path=args.journal or resolve_path(),
        heartbeat_path=args.heartbeat,
        state_path=args.state,
        endpoint=args.endpoint,
        max_age_s=max(0.0, args.max_age_s),
        timeout_s=max(0.1, args.timeout_s),
        require_restored_state=args.require_restored_state,
        previous_pid=args.previous_pid,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - operator proof entrypoint
    raise SystemExit(main())

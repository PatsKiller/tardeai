"""Per-lane run receipt ``<state_root>/data/runtime/<lane_id>_last.json`` (LaneRunReceipt@v1).

n8n refactor wave 1 (cron -> n8n, 2026-10-10). One helper for all four wave-1 buckets (W1-W4 each
grew their own; consolidated here at integration -- W4's ``lane_ok_receipt`` callers were repointed,
no second module). A cron lane whose registry ``output_signal`` is its own ``>> logs/...`` redirect
proves only that cron opened a file (AGENTS.md §9.3, §0 rail 8). This receipt is the durable artifact
a dispatcher or the registry reads instead, as a ``json_key`` signal on ``ok_at``:

* written by a REAL run only -- a dry run never calls :func:`write_lane_receipt`; it calls
  :func:`dry_run_report`, which only prints (AGENTS.md §6: a dry run cannot reach the write);
* ``ok_at`` advances only on a successful run; a failed run still writes the file
  (``status: failed``) but carries the previous ``ok_at`` forward, so a failing lane goes stale
  instead of green;
* resolved against the persistent state root (explicit root -> ``TRADEAI_STATE_ROOT`` ->
  ``persistent_state_root.resolve_durable_dir("data/runtime")``), never the release dir or the
  checkout the code happens to run from (§9.4);
* atomic replace (``atomic_json_store.atomic_write_json``);
* never stores stdout, credentials or exception text: ``error`` and any ``*error`` summary value of
  the form ``"SomeError: message"`` is reduced to the exception type name;
* never raises into the caller: a receipt failure is reported on stderr and returns ``None`` -- the
  run's own result and exit code come first. (W3's original ``write_receipt`` raised; no W3 caller
  or test relied on that.)

:func:`enforce_readonly` puts a dry run's psycopg2 session in READ ONLY at the server.

Monitor bookkeeping only: MBI_BEHAVIOR = 0, no broker, no send.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "LaneRunReceipt@v1"

_TYPE_PREFIX = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*:")
_MAX_ERROR = 300


def _resolve_durable_dir(rel: str) -> Path:
    try:
        from scripts.lib.persistent_state_root import resolve_durable_dir
    except ImportError:  # scripts/ on sys.path, repo root not
        from lib.persistent_state_root import resolve_durable_dir  # type: ignore[no-redef]
    return Path(resolve_durable_dir(rel))


def runtime_dir(state_root: Path | str | None = None) -> Path:
    """``<state_root>/data/runtime``: explicit root, else TRADEAI_STATE_ROOT, else the durable-dir resolver."""
    if state_root:
        return Path(state_root) / "data" / "runtime"
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env) / "data" / "runtime"
    return _resolve_durable_dir("data/runtime")


def _state_root() -> Path:
    """The state root whose ``data/runtime`` holds the receipts (back-compat for W1/W2/W3 callers)."""
    return runtime_dir().parent.parent


def receipt_path(
    lane_id: str,
    state_root: Path | str | None = None,
    *,
    root: Path | str | None = None,
) -> Path:
    """``<state_root>/data/runtime/<lane_id>_last.json``. Rejects path-like lane ids."""
    if not lane_id or "/" in lane_id or "\\" in lane_id or lane_id.startswith("."):
        raise ValueError(f"bad lane_id {lane_id!r}")
    return runtime_dir(state_root or root) / f"{lane_id}_last.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def previous_ok_at(path: Path | str) -> str | None:
    try:
        prev = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- no or unreadable previous receipt
        return None
    val = prev.get("ok_at") if isinstance(prev, dict) else None
    return str(val) if val else None


_previous_ok_at = previous_ok_at  # W1/W3/W4 spelling


def _scrub_error(value: Any) -> Any:
    """``"OSError: No space left on device"`` -> ``"OSError"``; other strings are length-capped."""
    if not isinstance(value, str):
        return value
    m = _TYPE_PREFIX.match(value)
    if m:
        return m.group(1)
    return value[:_MAX_ERROR]


def _scrub_summary(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(summary or {})
    for key, val in list(out.items()):
        if isinstance(key, str) and key.lower().endswith("error"):
            out[key] = _scrub_error(val)
    return out


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def build_receipt(
    lane_id: str,
    *,
    ok: bool,
    exit_code: int | None = None,
    started_at: str | datetime | None = None,
    script: str | None = None,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
    previous_ok_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    finished = finished_at or now_iso()
    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "lane_id": lane_id,
        "script": script or lane_id,
        "mode": "live",
        "status": "ok" if ok else "failed",
        "exit": int(exit_code) if exit_code is not None else None,
        "started_at": _iso(started_at),
        "finished_at": finished,
        "ok_at": finished if ok else previous_ok_at,
        "pid": os.getpid(),
        "summary": _scrub_summary(summary),
    }
    if error:
        doc["error"] = _scrub_error(str(error))
    return doc


def write_lane_receipt(
    lane_id: str,
    *,
    ok: bool,
    exit_code: int | None = None,
    started_at: str | datetime | None = None,
    script: str | None = None,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
    path: Path | str | None = None,
) -> Path | None:
    """Atomically replace the lane receipt for one REAL run. Returns the path, or None on failure.

    Never raises: the run's own result comes first. Never call this from a dry-run branch.
    """
    try:
        target = Path(path) if path else receipt_path(lane_id)
        doc = build_receipt(
            lane_id,
            ok=ok,
            exit_code=exit_code,
            started_at=started_at,
            script=script,
            summary=summary,
            error=error,
            previous_ok_at=previous_ok_at(target),
        )
        try:
            from scripts.lib.atomic_json_store import atomic_write_json
        except ImportError:
            from lib.atomic_json_store import atomic_write_json  # type: ignore[no-redef]
        atomic_write_json(target, doc, indent=1)
        return target
    except Exception as exc:  # noqa: BLE001 -- the receipt must never mask the run's own result
        print(f"[{lane_id}] lane receipt write failed: {type(exc).__name__}", file=sys.stderr)
        return None


def write_receipt(
    name: str,
    *,
    ok: bool,
    summary: Mapping[str, Any] | None = None,
    error: str | None = None,
    started_at: str | datetime | None = None,
    path: Path | str | None = None,
    exit_code: int | None = None,
) -> Path | None:
    """W3 spelling of :func:`write_lane_receipt` (``name`` is the lane id and the script name)."""
    return write_lane_receipt(
        name,
        ok=ok,
        exit_code=exit_code,
        started_at=started_at,
        summary=summary,
        error=error,
        path=path,
    )


def dry_run_report(
    lane_id: str,
    summary: Mapping[str, Any],
    *,
    would_write: list[str] | None = None,
    receipt: Path | str | None = None,
) -> dict:
    """Print (and return) what a real run would have written. Writes nothing."""
    try:
        target = str(receipt or receipt_path(lane_id))
    except Exception as exc:  # noqa: BLE001 -- a dry run reports, it does not fail on path resolution
        target = f"<unresolved: {type(exc).__name__}>"
    report = {
        "dry_run": True,
        "lane_id": lane_id,
        "would_write_receipt": target,
        "would_write": list(would_write or []),
        "summary": dict(summary),
    }
    print("DRY-RUN " + json.dumps(report, default=str, sort_keys=True), flush=True)
    return report


def enforce_readonly(conn: Any) -> Any:
    """Make a dry run's DB session READ ONLY at the server (AGENTS.md §6).

    Defence in depth for scripts whose dry run still runs SELECTs: even if a write statement were
    reached, PostgreSQL refuses it (``cannot execute INSERT in a read-only transaction``) instead of
    the script trusting a flag. Ends any open transaction first (set_session must run outside one).
    """
    set_session = getattr(conn, "set_session", None)
    if set_session is None:  # not a psycopg2 connection (test double); nothing to enforce
        return conn
    conn.rollback()
    set_session(readonly=True)
    return conn

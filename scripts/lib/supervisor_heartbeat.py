"""supervisor_heartbeat — one heartbeat helper for every lane (06 §3).

``beat(lane_id, **fields)`` always writes the file fallback ``data/runtime/heartbeats/<lane_id>.json``
(atomic tmp+replace) and, when a Postgres connection is given AND the ``intelligence.heartbeat``
table exists, upserts the row there. The detector reads both and says which it used. A beat is not
success: ``last_success`` moves only when the lane's output signal is observed (pass
``success=True`` from the place that proved the artifact exists).

No connection is opened here. Callers pass ``conn`` (psycopg2) or nothing; the file path is the
only side effect without one. Postgres failures never raise out of ``beat`` — a lane that cannot
record a beat must not die of it; the file still lands and the failure is in ``pg_error``.

Approval: pkg-20260927-cogx-w1-d9e1 item 7. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "LaneHeartbeat@v1"
_BOOT_ID: str | None = None


def boot_id() -> str:
    """Stable per process: /proc/sys/kernel/random/boot_id + pid, else a uuid."""
    global _BOOT_ID
    if _BOOT_ID:
        return _BOOT_ID
    try:
        host_boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        host_boot = uuid.uuid4().hex
    _BOOT_ID = f"{host_boot[:8]}-{os.getpid()}"
    return _BOOT_ID


def heartbeat_dir(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_HEARTBEAT_DIR"):
        return Path(env["TRADEAI_HEARTBEAT_DIR"])
    base = Path(root) if root else Path(env.get("TRADEAI_ROOT") or Path.cwd())
    return base / "data" / "runtime" / "heartbeats"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def beat(lane_id: str, *, conn: Any = None, success: bool = False, output_signal: bool = False,
         work_claimed: int = 0, work_done: int = 0, work_failed: int = 0, queue_depth: int | None = None,
         oldest_queued: str | None = None, memory_context_ok: bool | None = None,
         degraded_reasons: list[str] | None = None, release_sha: str | None = None,
         root: Path | None = None, env: dict | None = None) -> dict:
    """Write the beat. Returns the row written (with ``pg`` = written|absent|error|skipped)."""
    env = os.environ if env is None else env
    if not lane_id or not str(lane_id).strip():
        raise ValueError("lane_id is required")
    now = _now_iso()
    row = {
        "schema": SCHEMA, "lane_id": str(lane_id), "boot_id": boot_id(), "pid": os.getpid(),
        "host": socket.gethostname(), "release_sha": release_sha or env.get("TRADEAI_RELEASE_SHA"),
        "cwd": str(Path.cwd()), "last_beat": now,
        "last_success": now if success else None, "last_output_signal": now if output_signal else None,
        "work_claimed": int(work_claimed), "work_done": int(work_done), "work_failed": int(work_failed),
        "queue_depth": queue_depth, "oldest_queued": oldest_queued, "memory_context_ok": memory_context_ok,
        "degraded_reasons": list(degraded_reasons or []), "authority": "READ_ONLY_ADVISORY",
    }
    # file fallback (always): keep previous last_success/last_output_signal if this beat didn't prove one
    d = heartbeat_dir(root, env)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{row['lane_id']}.json"
    prev: dict = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    if not success:
        row["last_success"] = prev.get("last_success")
    if not output_signal:
        row["last_output_signal"] = prev.get("last_output_signal")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    row["file"] = str(path)
    # Postgres (optional)
    if conn is None:
        row["pg"] = "skipped"
        return row
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('intelligence.heartbeat')")
            if cur.fetchone()[0] is None:
                row["pg"] = "absent"
                return row
            cur.execute(
                """
                INSERT INTO intelligence.heartbeat
                    (lane_id, boot_id, pid, release_sha, cwd, last_beat, last_success, last_output_signal,
                     work_claimed, work_done, work_failed, queue_depth, oldest_queued, memory_context_ok, degraded_reasons)
                VALUES (%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (lane_id, boot_id) DO UPDATE SET
                    pid = EXCLUDED.pid, release_sha = EXCLUDED.release_sha, cwd = EXCLUDED.cwd, last_beat = now(),
                    last_success = COALESCE(EXCLUDED.last_success, intelligence.heartbeat.last_success),
                    last_output_signal = COALESCE(EXCLUDED.last_output_signal, intelligence.heartbeat.last_output_signal),
                    work_claimed = intelligence.heartbeat.work_claimed + EXCLUDED.work_claimed,
                    work_done = intelligence.heartbeat.work_done + EXCLUDED.work_done,
                    work_failed = intelligence.heartbeat.work_failed + EXCLUDED.work_failed,
                    queue_depth = EXCLUDED.queue_depth, oldest_queued = EXCLUDED.oldest_queued,
                    memory_context_ok = EXCLUDED.memory_context_ok, degraded_reasons = EXCLUDED.degraded_reasons
                """,
                (row["lane_id"], row["boot_id"], row["pid"], row["release_sha"], row["cwd"],
                 now if success else None, now if output_signal else None,
                 row["work_claimed"], row["work_done"], row["work_failed"], row["queue_depth"],
                 row["oldest_queued"], row["memory_context_ok"], row["degraded_reasons"]),
            )
        conn.commit()
        row["pg"] = "written"
    except Exception as exc:  # noqa: BLE001 — never kill a lane over its own heartbeat
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        row["pg"] = "error"
        row["pg_error"] = f"{type(exc).__name__}: {exc}"[:200]
    return row


def read_all(root: Path | None = None, env: dict | None = None) -> list[dict]:
    """Every file-fallback heartbeat (for the detector and the conformance report)."""
    d = heartbeat_dir(root, env)
    out: list[dict] = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            out.append({"lane_id": p.stem, "malformed": True})
    return out


__all__ = ["beat", "read_all", "heartbeat_dir", "boot_id", "SCHEMA"]

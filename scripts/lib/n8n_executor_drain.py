"""Graceful drain of the n8n run executor across a release promote (LQ-20261107-137).

Why: ``tradeai-n8n-run-executor.service`` has no ``KillMode=``, so systemd's default ``control-group`` SIGTERMs
every process in the unit's cgroup on ``systemctl restart``, including the lane child a worker is supervising.
Every promote that restarts the executor therefore killed in-flight runs, which the next executor reaped as
``RUN_TIMEOUT`` / ``executor_lost`` (7 watchlist-enrichment-sweep timeouts in the week to 2026-11-07, plus
finviz-screener-runner 11-06 after 1233 s).

How (no unit change, no operator install):

1. The deploy writes ``ExecutorDrainRequest@v1`` naming the release it just promoted (``target``) instead of
   restarting the executor straight away.
2. An executor whose own ``code_root`` is not ``target`` stops claiming new runs, lets the runs in flight finish,
   then exits 0. ``Restart=always`` starts a fresh process, and ``WorkingDirectory=CURRENT`` resolves the new
   release.
3. The new executor's ``code_root`` is ``target``, so the same request is inert for it. Nothing has to clear it.

Fail-safe in both directions:

* An unreadable, malformed, old (``MAX_AGE_S``) or pointless request (target missing, or already the code root)
  is ignored: the executor keeps working exactly as before.
* After ``deadline_s`` the drain is ``forced``: the executor exits even if a run is still in flight. That is
  today's behaviour, only later. The default deadline is longer than the heaviest lane timeout plus the lost
  grace, so in practice every in-flight child has already finished or been timed out by its own worker.
* The deploy helper (``scripts/n8n_executor_drain.py``) falls back to the old ``systemctl restart`` when the
  executor never acknowledges the request, e.g. the first promote that ships this code, when the running
  executor is still the old one.

AUTHORITY: READ_ONLY_ADVISORY. Writes one request file under the state root and reads the executor status file.
It never signals, restarts or kills anything itself.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "ExecutorDrainRequest@v1"
REQUEST_REL = Path("data") / "runtime" / "n8n_executor_drain_request.json"
STATUS_REL = Path("data") / "runtime" / "n8n_run_executor_last.json"
EXECUTOR_UNIT = "tradeai-n8n-run-executor.service"
#: > heavy_timeout_s (1800) + lost_grace_s (120) + margin: a forced exit should never meet a live child.
DEFAULT_DEADLINE_S = 2400.0
#: A request older than this is history, not an instruction.
MAX_AGE_S = 6 * 3600.0

RESULT_RE_RESOLVED = "re_resolved"
RESULT_DEFERRED = "deferred_draining"
RESULT_NOT_ACKED = "not_acknowledged"


def request_path(state_root: Path) -> Path:
    return Path(state_root) / REQUEST_REL


def write_request(
    state_root: Path,
    target: str | Path,
    *,
    now: float | None = None,
    deadline_s: float = DEFAULT_DEADLINE_S,
    requested_by: str = "deploy",
) -> Path:
    """Atomically write the drain request. Returns its path."""
    path = request_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": SCHEMA,
        "target": str(Path(target).resolve()),
        "requested_at": float(time.time() if now is None else now),
        "deadline_s": float(deadline_s),
        "requested_by": str(requested_by)[:80],
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_request(state_root: Path) -> dict[str, Any] | None:
    """The request, or None when absent, unreadable or not ``ExecutorDrainRequest@v1`` (fail open: no drain)."""
    try:
        doc = json.loads(request_path(state_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return None
    try:
        requested_at = float(doc["requested_at"])
        deadline_s = float(doc.get("deadline_s", DEFAULT_DEADLINE_S))
        target = str(doc["target"])
    except (KeyError, TypeError, ValueError):
        return None
    if not target or deadline_s <= 0:
        return None
    return {**doc, "requested_at": requested_at, "deadline_s": deadline_s, "target": target}


def drain_state(state_root: Path, code_root: Path, now: float) -> dict[str, Any] | None:
    """What a running executor at ``code_root`` should do now. None = keep working (no applicable request)."""
    req = read_request(state_root)
    if req is None:
        return None
    target = Path(req["target"])
    try:
        if not target.is_dir() or target.resolve() == Path(code_root).resolve():
            return None
    except OSError:
        return None
    age = float(now) - req["requested_at"]
    if age < -60.0 or age > MAX_AGE_S:  # a clock-skewed future request or an old one: history, not an instruction
        return None
    deadline_at = req["requested_at"] + req["deadline_s"]
    return {
        "target": str(target.resolve()),
        "requested_at": req["requested_at"],
        "deadline_at": deadline_at,
        "forced": float(now) >= deadline_at,
        "requested_by": req.get("requested_by"),
    }


def acknowledged(status: Mapping[str, Any] | None, target: str | Path) -> bool:
    """True when the executor status file reports it is draining towards ``target``."""
    if not isinstance(status, Mapping):
        return False
    d = status.get("draining")
    return isinstance(d, Mapping) and str(d.get("target")) == str(Path(target).resolve())


def read_status(state_root: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads((Path(state_root) / STATUS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def wait_for_drain(
    state_root: Path,
    target: str | Path,
    *,
    on_target: Callable[[], bool],
    wait_s: float = 90.0,
    ack_s: float = 20.0,
    poll_s: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    status_reader: Callable[[], Mapping[str, Any] | None] | None = None,
) -> str:
    """After ``write_request``: wait until the executor runs from ``target`` (``on_target()``).

    Returns RESULT_RE_RESOLVED when it does within ``wait_s``; RESULT_NOT_ACKED when within ``ack_s`` it has
    neither restarted nor reported ``draining`` for this target (an executor that predates the drain: the caller
    should restart it the old way); otherwise RESULT_DEFERRED (it is draining and restarts itself when idle).
    """
    read = status_reader or (lambda: read_status(state_root))
    start = clock()
    acked = False
    while True:
        if on_target():
            return RESULT_RE_RESOLVED
        acked = acked or acknowledged(read(), target)
        elapsed = clock() - start
        if not acked and elapsed >= ack_s:
            return RESULT_NOT_ACKED
        if elapsed >= wait_s:
            return RESULT_DEFERRED if acked else RESULT_NOT_ACKED
        sleeper(poll_s)

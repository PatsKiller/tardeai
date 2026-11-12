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

LQ-20261107-1685 (measured 2026-11-09: a 2894 s and a 1730 s window with zero run starts):

* A rewritten request keeps the earliest ``requested_at`` and the largest ``deadline_s``. Before, a second
  promote overwrote both, and the backstop moved 33 minutes later (14:57:16 asked again; deadline
  15:03:43 -> 15:37:16).
* ``deadline_for`` raises the deadline to the longest in-flight lane timeout plus ``lost_grace_s``, so a
  forced exit never meets a live child.
* ``market_guard`` is the activation check (E): in regular market hours on a trading day, a drain that would
  stop starts while a run older than 300 s is in flight is refused and the release waits.

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
from datetime import datetime, time as dt_time, timedelta, timezone
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
#: A lane with no allowlist entry is allowed this long (ExecutorV2 config unknown_lane_timeout_s).
DEFAULT_LANE_TIMEOUT_S = 3600.0

#: LQ-20261107-1685 (E): the activation window and the run age that makes a drain unsafe.
try:
    from zoneinfo import ZoneInfo  # noqa: PLC0415 - stdlib on 3.9+; the fallback keeps the module importable

    ET = ZoneInfo("America/New_York")
except ImportError:  # pragma: no cover - the repo runs 3.12+
    ET = timezone(timedelta(hours=-5))
MARKET_GUARD_START = dt_time(9, 30)
MARKET_GUARD_END = dt_time(16, 15)
MARKET_GUARD_MIN_AGE_S = 300.0

RESULT_RE_RESOLVED = "re_resolved"
RESULT_DEFERRED = "deferred_draining"
RESULT_NOT_ACKED = "not_acknowledged"
RESULT_REFUSED_MARKET_BUSY = "refused_market_busy"


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
    """Atomically write the drain request. Returns its path.

    LQ-20261107-1685 (D): an un-acted request keeps its ``requested_at`` and its largest ``deadline_s``; only
    the target moves. A rewrite therefore never postpones the backstop, which is what let the 14:22 ET drain
    run to 15:37 instead of 15:03.
    """
    path = request_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    at = float(time.time() if now is None else now)
    requested_at, deadline = at, float(deadline_s)
    prev = read_request(state_root)
    if prev is not None:
        age = at - prev["requested_at"]
        if 0.0 <= age <= MAX_AGE_S:  # the same un-acted drain: earliest request wins, never a later deadline
            requested_at = prev["requested_at"]
            deadline = max(deadline, float(prev["deadline_s"]))
    doc = {
        "schema": SCHEMA,
        "target": str(Path(target).resolve()),
        "requested_at": requested_at,
        "deadline_s": deadline,
        "written_at": at,
        "requested_by": str(requested_by)[:80],
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def retarget(state_root: Path, target: str | Path, *, now: float | None = None) -> dict[str, Any]:
    """Point an existing request at ``target`` and read it back. Never creates a request.

    LQ-20261107-2246: the promote runs this before it restarts the executor by any path, so a request left by
    an earlier promote can never outlive the restart naming a stale release. ``result`` is ``absent`` (nothing
    to fix), ``ok`` (read back equal) or ``mismatch`` (the write did not stick: the caller must not restart)."""
    want = str(Path(target).resolve())
    prev = read_request(state_root)
    if prev is None:
        return {"result": "absent", "target": want}
    if str(Path(prev["target"]).resolve()) != want:
        write_request(state_root, want, now=now, requested_by="deploy-retarget")
    back = read_request(state_root)
    ok = back is not None and str(Path(back["target"]).resolve()) == want
    return {"result": "ok" if ok else "mismatch", "target": want, "was": prev["target"]}


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


CURRENT_LINK_NAME = "CURRENT"
CURRENT_ENV = "TRADEAI_RELEASE_CURRENT_LINK"


def current_release(code_root: Path, env: Mapping[str, str] | None = None) -> Path | None:
    """The release ``CURRENT`` resolves to, or None when it cannot be determined (a dev checkout, a test tree).

    LQ-20261107-2246: the promote points ``CURRENT`` at the new release *before* it asks the executor to drain,
    so a request is only an instruction while its target is what ``CURRENT`` resolves to. The link is the
    ``CURRENT`` sibling of the executor's own release directory, or ``$TRADEAI_RELEASE_CURRENT_LINK``."""
    environ = os.environ if env is None else env
    try:
        link = Path(environ.get(CURRENT_ENV) or (Path(code_root).resolve().parent / CURRENT_LINK_NAME))
        return link.resolve() if link.is_dir() else None
    except OSError:
        return None


def drain_state(
    state_root: Path, code_root: Path, now: float, *, current_root: Path | None = None
) -> dict[str, Any] | None:
    """What a running executor at ``code_root`` should do now. None = keep working (no applicable request).

    LQ-20261107-2246: a request whose target is not the CURRENT release is inert. On 2026-11-12 09:46 ET a
    request left by the previous promote (target e58903163, 65 min old, never acted on) made the executor of the
    next release drain and exit every ~10 s for 2 min: its code_root differed from the stale target. A target
    that is not CURRENT is stale by definition. ``current_root`` overrides the detected CURRENT (tests); when
    CURRENT cannot be determined the old behaviour holds."""
    req = read_request(state_root)
    if req is None:
        return None
    target = Path(req["target"])
    try:
        if not target.is_dir() or target.resolve() == Path(code_root).resolve():
            return None
        current = Path(current_root).resolve() if current_root is not None else current_release(code_root)
        if current is not None and target.resolve() != current:
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


def timeout_by_lane(allowlist: Mapping[str, Any] | None) -> dict[str, float]:
    """``{lane_id: timeout_s}`` from an N8nRunAllowlist@v1 document (or a ``{lane: entry}`` mapping)."""
    out: dict[str, float] = {}
    if not isinstance(allowlist, Mapping):
        return out
    lanes = allowlist.get("lanes")
    entries: list[Mapping[str, Any]] = []
    if isinstance(lanes, list):
        entries = [e for e in lanes if isinstance(e, Mapping)]
    else:  # a resolved mapping: {lane_id: entry}
        entries = [dict(e, lane_id=str(k)) for k, e in allowlist.items() if isinstance(e, Mapping)]
    for entry in entries:
        lane = entry.get("lane_id")
        timeout_s = entry.get("timeout_s")
        if isinstance(lane, str) and isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool):
            out[lane] = float(timeout_s)
    return out


def deadline_for(
    busy: Any,
    allowlist: Mapping[str, Any] | None,
    *,
    default: float = DEFAULT_DEADLINE_S,
    lost_grace_s: float = 120.0,
) -> float:
    """LQ-20261107-1685 (D): a backstop that outlives every in-flight run's own timeout.

    The old fixed 2400 s was documented as ``heavy_timeout_s 1800 + lost_grace 120``, which is false for the
    22 allowlist rows with ``timeout_s >= 1800`` (disk-hygiene is 3600). A forced exit below that kills the
    child and the next executor reaps it ``executor_lost``."""
    timeouts = timeout_by_lane(allowlist)
    longest = default
    for row in busy or ():
        lane = row.get("lane_id") if isinstance(row, Mapping) else None
        longest = max(longest, timeouts.get(str(lane), DEFAULT_LANE_TIMEOUT_S) + float(lost_grace_s))
    return float(max(default, longest))


def _trading_day_default(d) -> bool:
    try:
        from scripts.market_session import is_trading_day  # noqa: PLC0415 - a heavy import, only on this path

        return bool(is_trading_day(d))
    except Exception:  # noqa: BLE001 - an unreadable calendar fails closed: weekdays are trading days
        return d.weekday() < 5


def market_guard(
    status: Mapping[str, Any] | None,
    *,
    now: float | None = None,
    allowlist: Mapping[str, Any] | None = None,
    trading_day: Callable[[datetime], bool] | None = None,
    min_age_s: float = MARKET_GUARD_MIN_AGE_S,
) -> dict[str, Any] | None:
    """LQ-20261107-1685 (E): why a drain must wait, or None when it may proceed.

    During 09:30-16:15 ET on a trading day, a run already in flight for longer than ``min_age_s`` means a
    drain would stop every new start for up to an hour (2026-11-09: 2894 s and 1730 s). The refusal names the
    lane, its age and how long it may still run."""
    at = float(time.time() if now is None else now)
    when = datetime.fromtimestamp(at, ET)
    if not (MARKET_GUARD_START <= when.time() <= MARKET_GUARD_END):
        return None
    if not (trading_day or _trading_day_default)(when):
        return None
    timeouts = timeout_by_lane(allowlist)
    oldest: dict[str, Any] | None = None
    for row in (status or {}).get("busy") or ():
        if not isinstance(row, Mapping):
            continue
        try:
            started = datetime.fromisoformat(str(row.get("started_at")))
        except (TypeError, ValueError):
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age = at - started.timestamp()
        if age < float(min_age_s) or (oldest is not None and age <= oldest["age_s"]):
            continue
        lane = str(row.get("lane_id") or "?")
        remaining = max(0.0, timeouts.get(lane, DEFAULT_LANE_TIMEOUT_S) - age)
        oldest = {
            "reason": "market_hours_long_run",
            "lane_id": lane,
            "run_id": row.get("run_id"),
            "age_s": round(age, 3),
            "predicted_end_s": round(remaining, 3),
            "started_at": started.isoformat(),
        }
    return oldest


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

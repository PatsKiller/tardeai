"""HomeDoNowSnapshot@v1: the Home "Do now" queue built out of process, read on the GET and never built there.

S2 item 2 (operator 2026-11-14). Before this module the route ``/api/v2/home/do-now`` built its body on the
request thread whenever the in-process cache was empty — the first Home open after a restart, or a second reader
that arrived while the first build was still running. That build is a fan-out over eight probes (needs-action's
own aggregate among them); measured at 5.0 s on the 2026-11-14 16:17Z capture (``sources.needs_action.ms``).
Cold-start, cache-miss and producer-down therefore each cost a request a heavy computation.

The split now:

* the n8n lane ``home-do-now-snapshot`` (scripts/build_home_do_now_snapshot.py) runs the same build in its own
  process and replaces this file atomically, with the body, its ``as_of``, the build instant, the code identity and
  the mtimes of the stores it read;
* the route READS the file. One ``stat`` per request, a parse only when the file changed. There is no compute path
  in this module: no callable to fall back to, so a GET cannot build even by accident.

What the reader answers, and never more:

* ``age <= FRESH_S`` — the snapshot, ``served.stale = false``;
* ``FRESH_S < age <= LAST_GOOD_MAX_S`` — LAST-KNOWN-GOOD **with its age**, ``served.stale = true``. A body written
  by another release (a deploy has just moved) is served this way too, with ``served.reason = "code_mismatch"``:
  blanking do-now for the minute between a deploy and the lane's next tick would be worse than a labelled body;
* missing / unreadable / not ``status: ok`` / older than ``LAST_GOOD_MAX_S`` / from the future — a NAMED UNKNOWN
  (``unknown_data``): ``status: "UNKNOWN"``, counts ``None`` (never zeros — an unknown queue is not an empty
  queue), and ``unknown.owner`` + ``unknown.next_action`` naming who fixes it and how.

``reauthorize`` is the per-request authorization recheck: the snapshot is built by the lane under the service
principal, so a caller that is neither the operator session nor the service token must not receive a
principal-gated item (today: pending paper proposals). Dropped items are named in ``authorization`` and their
source is restated ``UNAUTHORIZED`` / ``scope_excluded`` — the same shape ``build_home`` uses for approvals.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "HomeDoNowSnapshot@v1"
ROUTE = "/api/v2/home/do-now"
PATH_ENV = "TRADEAI_HOME_DO_NOW_SNAPSHOT_PATH"
FILE_NAME = "home_do_now_snapshot.json"
#: a body younger than this is served as current (the lane's cadence is 60 s; 2x covers one missed tick)
FRESH_S = 120.0
#: older than this, a body is not shown at all: a do-now queue an hour old is a different answer, not an old one
LAST_GOOD_MAX_S = 1800.0
#: a snapshot stamped this far in the future is a clock problem, not a fresh read
FUTURE_TOLERANCE_S = 5.0
#: the stores whose mtimes are recorded on each build (evidence of what the body read, not a gate)
INPUT_FILES = ("holdings.json", "trade_journal.json", "risk_management.json", "needs_action_cache.json")
OWNER = "lane home-do-now-snapshot (scripts/build_home_do_now_snapshot.py, n8n dispatcher)"
NEXT_ACTION = {
    "missing": "Dispatch the lane, or check its next tick: n8n dispatcher row `home-do-now-snapshot` "
               "(scripts/build_home_do_now_snapshot.py --apply). The snapshot file has never been written.",
    "unreadable": "Check the file's permissions and the state root; the lane rewrite is atomic, so a half-written "
                  "file should be impossible — if it persists, inspect the filesystem, then re-dispatch the lane.",
    "corrupt": "Re-dispatch the lane; if the rewritten file still does not parse, read the producer receipt for a "
               "failed build (the build validates a dict body before replacing the file).",
    "not_ok": "Re-dispatch the lane and read its receipt: the last build reported a non-ok status.",
    "expired": "The lane has not landed a body inside its last-good window. Check the lane receipt and the n8n "
               "dispatch, then re-dispatch `home-do-now-snapshot`; do not read the queue as empty meanwhile.",
    "clock_skew": "The snapshot's clock is ahead of this host's. Compare the producer host and this one; the "
                  "producer clock, not the body, is wrong.",
    "default": "Re-dispatch the lane `home-do-now-snapshot` and read its receipt.",
}
#: sources whose items are principal-gated (the producer runs as the service principal, a reader may not)
GATED_SOURCES = ("proposals",)
SOURCE = "snapshot"


def projection_path(root: Path | str | None = None) -> Path:
    """The snapshot file: ``$TRADEAI_HOME_DO_NOW_SNAPSHOT_PATH``, else ``<state root>/data/runtime/``."""
    if root is None:
        raw = os.environ.get(PATH_ENV)
        if raw:
            return Path(raw)
        try:
            from lib.canonical_store_registry import production_state_root
        except ImportError:  # pragma: no cover - imported as scripts.lib
            from scripts.lib.canonical_store_registry import production_state_root
        root = production_state_root()
    return Path(root) / "data" / "runtime" / FILE_NAME


def lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def code_identity(project_root: Path | str) -> str:
    """The code a body was computed by: the release's BUILD_SHA (or GIT_SHA), else the resolved tree path."""
    root = Path(project_root)
    for name in ("BUILD_SHA", "GIT_SHA"):
        try:
            sha = (root / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if sha:
            return "sha:" + sha
    return "path:" + str(root.resolve())


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _input_mtimes(state_dir: Path | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in INPUT_FILES:
        try:
            out[name] = _iso((Path(state_dir) / name).stat().st_mtime) if state_dir else None
        except OSError:
            out[name] = None
    return out


def _atomic_write(path: Path, doc: dict) -> None:
    """Replace the file in one step: a reader sees the previous body or the new one, never half of either."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"), default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def build(compute: Callable[[], Any], *, path: Path, identity: str | Callable[[], str],
          clock: Callable[[], float] = time.time,
          state_dir: Path | None | Callable[[], Path | None] = None) -> dict:
    """Compute one do-now body and replace the snapshot. Single flight: a held lock is refused, not queued.

    Returns ``{"status": "ok"|"failed"|"refused", ...}``. A failed build leaves the previous snapshot in place
    (the reader serves it with its age until ``LAST_GOOD_MAX_S``, then reports the named UNKNOWN)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path(path), "a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "refused", "reason": "build_in_flight"}
        started = clock()
        try:
            body = json.loads(json.dumps(compute(), default=str))
            if not isinstance(body, dict):
                raise TypeError(f"do-now body is {type(body).__name__}, not a dict")
            built = clock()
            # ACC-CACHE item 3: a build never moves the file backwards. Two producers (a retried run, a second host
            # sharing the state root) can finish out of order; the fresher body is the one the queue must keep.
            existing, _why = _load(path)
            if existing is not None and float(existing["built_at_epoch"]) >= built:
                return {"status": "refused", "reason": "newer_build_present",
                        "existing_built_at": existing.get("built_at")}
            identity = identity() if callable(identity) else identity
            state_dir = state_dir() if callable(state_dir) else state_dir
            doc = {
                "schema": SCHEMA,
                "status": "ok",
                "started_at": _iso(started),
                "built_at": _iso(built),
                "started_at_epoch": started,
                "built_at_epoch": built,
                "build_ms": int(round((built - started) * 1000)),
                "code_identity": identity,
                "as_of": body.get("as_of"),
                "inputs": _input_mtimes(state_dir),
                "body": body,
            }
            _atomic_write(path, doc)
        except Exception as exc:  # noqa: BLE001 -- typed; the previous snapshot keeps being served with its age
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
                    "started_at": _iso(started)}
    return {"status": "ok", "built_at": doc["built_at"], "as_of": doc["as_of"], "build_ms": doc["build_ms"],
            "code_identity": identity, "bytes": path.stat().st_size, "path": str(path)}


# (path, st_ino, st_mtime_ns, st_size) -> parsed document; one entry, so a rebuilt file replaces it
_PARSED: dict[tuple, dict] = {}


def _load(path: Path) -> tuple[dict | None, str | None]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    key = (str(path), st.st_ino, st.st_mtime_ns, st.st_size)
    doc = _PARSED.get(key)
    if doc is None:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, "missing"
        except (OSError, ValueError):
            return None, "corrupt"
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
            return None, "corrupt"
        if doc.get("status") != "ok":
            return None, "not_ok"
        if not isinstance(doc.get("body"), dict) or not isinstance(doc.get("started_at_epoch"), (int, float)) \
                or not isinstance(doc.get("built_at_epoch"), (int, float)):
            return None, "corrupt"
        _PARSED.clear()
        _PARSED[key] = doc
    return doc, None


def read(path: Path | None = None, *, identity: str | None = None, now: float | None = None,
         fresh_s: float = FRESH_S, last_good_max_s: float = LAST_GOOD_MAX_S) -> tuple[dict | None, dict]:
    """(doc, meta). ``doc`` is None exactly when the body must NOT be served; ``meta`` always names why."""
    doc, reason = _load(Path(path) if path is not None else projection_path())
    if doc is None:
        return None, {"source": "none", "reason": reason}
    now = time.time() if now is None else now
    age = now - float(doc["built_at_epoch"])
    base: dict[str, Any] = {
        "as_of": doc.get("as_of") or (doc.get("body") or {}).get("as_of"),
        "built_at": doc.get("built_at"),
        "age_s": round(max(age, 0.0), 1),
        "code_identity": doc.get("code_identity"),
    }
    if age < -FUTURE_TOLERANCE_S:
        return None, {"source": "none", "reason": "clock_skew", **base}
    if age > last_good_max_s:
        return None, {"source": "none", "reason": "expired", **base}
    # a body from another release is LAST-KNOWN-GOOD and says so; it is not a reason to blank the queue, but it is
    # never CURRENT either — a reviewer reading `stale: false, reason: code_mismatch` would be told two things.
    why = "code_mismatch" if (identity and doc.get("code_identity") not in (None, identity)) else None
    return doc, {"source": SOURCE, "reason": why, "stale": (age > fresh_s) or bool(why), **base}


def serve(*, identity: str | None = None, path: Path | None = None,
          now: float | None = None) -> tuple[dict | None, dict]:
    """(body, meta): the snapshot body, or None with a named reason. There is no compute callable — by design."""
    doc, meta = read(path, identity=identity, now=now)
    if doc is None:
        return None, meta
    body = doc["body"]
    return {**body, "items": list(body.get("items") or [])}, meta


def reauthorize(body: dict, authorized: bool) -> dict:
    """Drop principal-gated items for a caller that may not see them, and name the exclusion.

    A copy is returned either way: the parsed snapshot is shared between reads and is never mutated."""
    if authorized:
        return body
    items = [i for i in (body.get("items") or [])
             if not (set(i.get("sources") or ()) & set(GATED_SOURCES))]
    sources: dict[str, Any] = {}
    for name, mark in (body.get("sources") or {}).items():
        if name in GATED_SOURCES and isinstance(mark, dict):
            sources[name] = {**mark, "status": "UNAUTHORIZED", "scope_excluded": True}
        else:
            sources[name] = mark
    counts = {"all": len(items), **{c: sum(1 for i in items if i.get("category") == c)
                                    for c in {i.get("category") for i in items} if c}}
    severity = {sev: sum(1 for i in items if i.get("severity") == sev)
                for sev in {i.get("severity") for i in items} if sev}
    return {**body, "items": items, "counts": counts, "severity_counts": severity, "sources": sources,
            "authorization": {
                "scope": "not_operator",
                "excluded_sources": list(GATED_SOURCES),
                "reason": "the snapshot is built by the service principal; an item from a principal-gated source "
                          "is dropped unless the caller is the operator session or the service token",
            }}


def unknown_data(meta: dict) -> dict:
    """The NAMED UNKNOWN, in the route's own body shape. Counts are null: an unknown queue is not an empty one."""
    schema, authority = "HomeDoNow@v1", "READ_ONLY_ADVISORY"
    try:
        from lib.data_broker import home_do_now as _hdn
        schema, authority = _hdn.SCHEMA, _hdn.AUTHORITY
    except Exception:  # noqa: BLE001 -- the UNKNOWN must not depend on a module that may itself be unavailable
        try:
            from scripts.lib.data_broker import home_do_now as _hdn  # type: ignore
            schema, authority = _hdn.SCHEMA, _hdn.AUTHORITY
        except Exception:  # noqa: BLE001
            pass
    reason = str(meta.get("reason") or "missing")
    return {
        "schema": schema,
        "authority": authority,
        "as_of": None,
        "status": "UNKNOWN",
        "all_sources_answered": False,
        "any_source_stale": True,
        "sort": None,
        "top_n": None,
        "counts": None,
        "severity_counts": None,
        "items": [],
        "rolled_up": None,
        "numbers": {"status": "UNAVAILABLE"},
        "sources": {},
        "timeout_s": None,
        "unknown": {
            "reason": reason,
            "owner": OWNER,
            "next_action": NEXT_ACTION.get(reason, NEXT_ACTION["default"]),
            "snapshot": {k: meta.get(k) for k in ("as_of", "built_at", "age_s", "code_identity")},
        },
    }

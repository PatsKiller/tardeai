"""OverviewProjection@v1: /api/v2/overview precomputed out of process, read in front of the inline path.

LQ-20261107-1612 (option B, acked by claude-lead 2026-11-09). The lane ``overview-projection``
(scripts/build_overview_projection.py) runs ``api_v2._overview_with_today_move()`` in its own process and
writes the wire form of the body here. portfolio-server serves it only when **all** of these hold, and
otherwise computes inline exactly as before, naming the reason in ``_projection`` (never blank, never silent):

- the file parses as this schema with ``status: ok`` and a dict body;
- it was built by the same code (``code_identity``: the release's BUILD_SHA) the server runs;
- it is at most ``MAX_AGE_S`` old, and not from the future;
- no operator write that can change the overview (stale_serve.WRITE_INVALIDATES) landed after the build
  **started**; with write tracking off (TRADEAI_SWR=0) nothing is tracked, so nothing is served.

One code path: the projection holds the same body the route would compute, serialized the way the server
serializes (``default=str``, NaN/inf as null), so a page cannot tell the sources apart except by
``_projection``. The builder never writes any input store; a failed build leaves the previous file.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "OverviewProjection@v1"
ROUTE = "/api/v2/overview"
MAX_AGE_S = 150.0
#: a projection stamped this far in the future is a clock problem, not a fresh read
FUTURE_TOLERANCE_S = 5.0
PATH_ENV = "TRADEAI_OVERVIEW_PROJECTION_PATH"
FILE_NAME = "overview_projection.json"
#: the inputs whose mtimes are recorded on each build (evidence of what the body read, not a gate)
INPUT_FILES = ("holdings.json", "trade_journal.json", "risk_management.json", "finviz_quote_cache.json")
#: POST-path substrings whose writes can change the overview body: holdings and their sync, approvals and
#: the pending pipeline, notifications, the journal and trades. Over-matching costs one inline compute;
#: under-matching would show the operator a pre-write overview for up to MAX_AGE_S.
WRITE_MARKERS = ("approv", "notification", "holding", "pipeline", "journal", "trade", "position",
                 "account", "reprice", "sync", "cash")
#: sentinel from invalidation_reader(): write tracking is off, so no projection may be served
WRITE_TRACKING_OFF = object()


def projection_path(root: Path | str | None = None) -> Path:
    """The projection file: ``$TRADEAI_OVERVIEW_PROJECTION_PATH``, else ``<state root>/data/runtime/``."""
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
    """The code a body was computed by: the release's BUILD_SHA (or GIT_SHA), else the resolved tree path.

    Builder and server derive it the same way from their own api_v2.PROJECT_ROOT, so a projection built by
    the previous release is never served by the next one."""
    root = Path(project_root)
    for name in ("BUILD_SHA", "GIT_SHA"):
        try:
            sha = (root / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if sha:
            return "sha:" + sha
    return "path:" + str(root.resolve())


def _nan_to_none(obj: Any) -> Any:
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nan_to_none(v) for v in obj]
    return obj


def to_wire(body: Any) -> Any:
    """The body as portfolio-server puts it on the wire (json.dumps default=str, NaN/inf -> null)."""
    try:
        raw = json.dumps(body, default=str, allow_nan=False)
    except ValueError:
        raw = json.dumps(_nan_to_none(json.loads(json.dumps(body, default=str))), default=str, allow_nan=False)
    return json.loads(raw)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"), allow_nan=False)
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
    """Compute one overview and replace the projection. Single flight: a held lock is refused, not queued.

    Returns ``{"status": "ok"|"failed"|"refused", ...}``. A failed build leaves the previous projection in
    place (the reader ages it out at MAX_AGE_S and the API computes inline). ``identity`` and ``state_dir``
    may be callables, read after ``compute()`` (the lane only knows them once api_v2 is imported)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path(path), "a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "refused", "reason": "build_in_flight"}
        started = clock()
        try:
            body = to_wire(compute())
            if not isinstance(body, dict):
                raise TypeError(f"overview body is {type(body).__name__}, not a dict")
            built = clock()
            # ACC-CACHE item 3 (S2 item 2): a build never moves the file backwards. Two producers (a retried run, a
            # second host sharing the state root) can finish out of order; the fresher body is the one to keep.
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
                "inputs": _input_mtimes(state_dir),
                "body": body,
            }
            _atomic_write(path, doc)
        except Exception as exc:  # noqa: BLE001 -- returned typed; the previous projection stays served
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
                    "started_at": _iso(started)}
    return {"status": "ok", "built_at": doc["built_at"], "build_ms": doc["build_ms"],
            "code_identity": identity, "bytes": path.stat().st_size, "path": str(path)}


# (st_ino, st_mtime_ns, st_size) -> parsed document; one entry, so a rebuilt file replaces it
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


def read(path: Path, *, identity: str, invalidated_at: Any, now: float | None = None,
         max_age_s: float = MAX_AGE_S) -> tuple[dict | None, dict]:
    """(body, meta) when the projection may be served, else (None, {"source": "inline", "reason": ...})."""
    if invalidated_at is WRITE_TRACKING_OFF:
        return None, {"source": "inline", "reason": "write_tracking_off"}
    doc, reason = _load(Path(path))
    if doc is None:
        return None, {"source": "inline", "reason": reason}
    if doc.get("code_identity") != identity:
        return None, {"source": "inline", "reason": "code_mismatch"}
    now = time.time() if now is None else now
    age = now - float(doc["built_at_epoch"])
    if age < -FUTURE_TOLERANCE_S:
        return None, {"source": "inline", "reason": "clock_skew"}
    if age > max_age_s:
        return None, {"source": "inline", "reason": "aged"}
    if invalidated_at is not None and float(invalidated_at) >= float(doc["started_at_epoch"]):
        return None, {"source": "inline", "reason": "invalidated"}
    meta = {"source": "projection", "built_at": doc.get("built_at"), "age_s": round(max(age, 0.0), 1)}
    # The served stamp carries built_at, not age_s: the body stays byte-identical for the projection's whole
    # life, so the server's ETag cache answers repeat polls with 304 instead of re-serializing 65 KB.
    return {**doc["body"], "_projection": {"source": "projection", "built_at": doc.get("built_at")}}, meta


def is_fresh(path: Path | None = None, *, now: float | None = None) -> bool:
    """True when a well-formed projection exists that is at most ``MAX_AGE_S`` old (and not from the future).

    LQ-20261107-2130: the request semaphore exempts ``/api/v2/overview`` only while this holds, because only then
    is the request a cheap file read. Code identity and write invalidation are not checked here (a request those
    would send inline is rare and still bounded by the compute's own timeouts). Never raises: unknown is False."""
    try:
        doc, _reason = _load(Path(path) if path is not None else projection_path())
        if doc is None:
            return False
        age = (time.time() if now is None else now) - float(doc["built_at_epoch"])
        return -FUTURE_TOLERANCE_S <= age <= MAX_AGE_S
    except Exception:  # noqa: BLE001
        return False


def invalidation_reader(swr_module: Any = None) -> Callable[[], Any]:
    """A zero-arg reader of when the overview was last invalidated by a write (stale_serve's record).

    Returns WRITE_TRACKING_OFF when stale_serve is disabled, because then no write is recorded at all."""
    def _read() -> Any:
        mod = swr_module
        if mod is None:
            try:
                from lib import stale_serve as mod
            except ImportError:  # pragma: no cover - imported as scripts.lib
                from scripts.lib import stale_serve as mod
        if not mod.enabled():
            return WRITE_TRACKING_OFF
        return mod.default().invalidated_at(ROUTE)
    return _read


def serve(compute: Callable[[], dict], *, path: Path | None = None, identity: str,
          invalidated_at_fn: Callable[[], Any], now: float | None = None) -> dict:
    """The projection when it may be served, else ``compute()`` with ``_projection.reason``. Never blank."""
    try:
        cut = invalidated_at_fn()
    except Exception:  # noqa: BLE001 -- an unknown write record must never serve a pre-write body
        reason: dict = {"source": "inline", "reason": "invalidation_unreadable"}
    else:
        try:
            body, reason = read(path if path is not None else projection_path(), identity=identity,
                                invalidated_at=cut, now=now)
        except Exception as exc:  # noqa: BLE001 -- the reader must never cost the operator the overview
            body, reason = None, {"source": "inline", "reason": f"reader_error:{type(exc).__name__}"}
        if body is not None:
            return body
    out = compute()
    if isinstance(out, dict):
        out["_projection"] = reason
    return out


def register_write_invalidation(swr_module: Any) -> None:
    """Make every operator write that can change the overview invalidate it (idempotent).

    Registered from api_v2 at import, beside the route, rather than in stale_serve's table, so the reader
    and its invalidation ship in one hunk."""
    table = swr_module.WRITE_INVALIDATES
    if ROUTE not in table:
        table[ROUTE] = WRITE_MARKERS

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
#: LAST-GOOD window (S2 item 2, operator 2026-11-14): past MAX_AGE_S the body is served STALE WITH ITS AGE
#: (``_projection.stale`` / ``_projection.age_s``) instead of being recomputed on the request thread. Beyond this it is
#: a different answer, not an old one, and the route answers the named UNKNOWN (``unknown_body``).
LAST_GOOD_MAX_S = 1800.0
OWNER = "lane overview-projection (scripts/build_overview_projection.py, n8n dispatcher)"
NEXT_ACTION = {
    "missing": "Dispatch the lane or check its next tick: n8n dispatcher row `overview-projection` "
               "(scripts/build_overview_projection.py --apply). The projection file has never been written under "
               "this state root.",
    "expired": "The lane has not landed a body inside its last-good window. Check the lane receipt and the n8n "
               "dispatch, then re-dispatch `overview-projection`; do not read the header as zero meanwhile.",
    "corrupt": "Re-dispatch the lane; the build validates the body before replacing the file, so a persistent "
               "corrupt file means something other than the lane is writing it.",
    "unreadable": "Check the file's permissions and the state root, then re-dispatch the lane.",
    "not_ok": "Read the lane receipt: the last build reported a non-ok status. Re-dispatch after fixing it.",
    "clock_skew": "The projection's clock is ahead of this host's; compare the producer host and this one.",
    "default": "Re-dispatch the lane `overview-projection` and read its receipt.",
}
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
         max_age_s: float = MAX_AGE_S, last_good_max_s: float = LAST_GOOD_MAX_S) -> tuple[dict | None, dict]:
    """(body, meta) when a projection may be served, else (None, {"source": "none", "reason": ...}).

    S2 item 2 (operator 2026-11-14): this reader NEVER asks for a build, so every case it can answer is either a
    labelled body or a named reason — there is no third path in which the request computes the overview itself.

    * age <= max_age_s and not invalidated and the same release -> current, ``stale: false``;
    * aged, or invalidated by an operator write, or built by another release -> LAST-KNOWN-GOOD with its age,
      ``stale: true`` and ``reason`` naming which of the three ("aged" / "invalidated" / "code_mismatch"). A deploy
      therefore never blanks the header for the minute before the lane's next tick, and a write does not silently
      show a pre-write body as current — it shows it as stale, with the clock that says so;
    * missing / unreadable / corrupt / not ok / older than last_good_max_s / from the future -> (None, reason).
    """
    doc, reason = _load(Path(path))
    if doc is None:
        return None, {"source": "none", "reason": reason}
    now = time.time() if now is None else now
    age = now - float(doc["built_at_epoch"])
    base: dict[str, Any] = {"built_at": doc.get("built_at"), "age_s": round(max(age, 0.0), 1),
                            "code_identity": doc.get("code_identity")}
    if age < -FUTURE_TOLERANCE_S:
        return None, {"source": "none", "reason": "clock_skew", **base}
    if age > last_good_max_s:
        return None, {"source": "none", "reason": "expired", **base}
    why = None
    if doc.get("code_identity") != identity:
        why = "code_mismatch"
    elif invalidated_at is WRITE_TRACKING_OFF:
        # no write tracking means no way to know this body pre-dates a write: serve it, but never as current
        why = "write_tracking_off"
    elif age > max_age_s:
        why = "aged"
    elif invalidated_at is not None and float(invalidated_at) >= float(doc["started_at_epoch"]):
        why = "invalidated"
    stale = why is not None
    meta = {"source": "projection", "built_at": doc.get("built_at"), "age_s": base["age_s"],
            "stale": stale, "reason": why}
    # The served stamp carries built_at and the reason, not age_s: within one reason the body is byte-identical, so
    # the server's ETag cache answers repeat polls with 304 instead of re-serializing 65 KB. It changes bytes once,
    # when a body crosses from current to stale — one re-serialization per transition, not one per poll.
    return ({**doc["body"], "_projection": {"source": "projection", "built_at": doc.get("built_at"),
                                            "stale": stale, "reason": why}}, meta)


def is_servable(path: Path | None = None, *, now: float | None = None,
                last_good_max_s: float = LAST_GOOD_MAX_S) -> bool:
    """True when a request would be a file read: a well-formed projection inside the LAST-GOOD window.

    S2 item 2: since ``serve`` no longer computes, EVERY window it serves is cheap; this is the predicate the
    request semaphore should exempt on (``is_fresh`` is the narrower "served as current" question). Never raises:
    unknown is False."""
    try:
        doc, _reason = _load(Path(path) if path is not None else projection_path())
        if doc is None:
            return False
        age = (time.time() if now is None else now) - float(doc["built_at_epoch"])
        return -FUTURE_TOLERANCE_S <= age <= last_good_max_s
    except Exception:  # noqa: BLE001
        return False


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


def unknown_body(reason: dict) -> dict:
    """The named UNKNOWN in the route's own body shape: every number null, the gap named with owner and next action.

    Nothing here is a fabricated zero. A surface that renders these nulls as "—" is telling the truth; one that
    renders them as 0 would be showing a portfolio value of zero, which is why ``unavailable`` is set as well."""
    why = str(reason.get("reason") or "missing")
    return {
        "status": "UNKNOWN",
        "unavailable": True,
        "as_of": None,
        "portfolio_value": None,
        "total_value": None,
        "total_cash": None,
        "position_count": None,
        "today_change": None,
        "today_pct": None,
        "gap": {"reason": why, "owner": OWNER, "next_action": NEXT_ACTION.get(why, NEXT_ACTION["default"])},
        "_projection": {"source": "unknown", "reason": why, "age_s": reason.get("age_s"),
                        "built_at": reason.get("built_at")},
    }


def serve(compute: Callable[[], dict] | None = None, *, path: Path | None = None, identity: str,
          invalidated_at_fn: Callable[[], Any], now: float | None = None,
          last_good_max_s: float = LAST_GOOD_MAX_S) -> dict:
    """The servable projection, else the named UNKNOWN. NEVER computes.

    ``compute`` is accepted only so existing call sites keep working; it is not called, ever (S2 item 2, operator
    2026-11-14: a GET never triggers heavy compute). Removing the call here — rather than adding a flag — is what
    makes "no request-path compute" a property of the module instead of a promise at the call site."""
    try:
        cut = invalidated_at_fn()
    except Exception:  # noqa: BLE001 -- an unreadable write record must never be shown as a current body
        cut = float("inf")  # a write is possible: the body is served, labelled stale, never regenerated here
    try:
        body, reason = read(path if path is not None else projection_path(), identity=identity,
                            invalidated_at=cut, now=now, last_good_max_s=last_good_max_s)
    except Exception as exc:  # noqa: BLE001 -- the reader must never cost the operator the overview
        body, reason = None, {"source": "none", "reason": f"reader_error:{type(exc).__name__}"}
    if body is not None:
        return body
    return unknown_body(reason)


def register_write_invalidation(swr_module: Any) -> None:
    """Make every operator write that can change the overview invalidate it (idempotent).

    Registered from api_v2 at import, beside the route, rather than in stale_serve's table, so the reader
    and its invalidation ship in one hunk."""
    table = swr_module.WRITE_INVALIDATES
    if ROUTE not in table:
        table[ROUTE] = WRITE_MARKERS

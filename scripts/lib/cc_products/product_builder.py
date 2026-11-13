"""Generic bounded builder for precomputed products (DSN-20261112-PRECOMPUTE-CACHE §4-§5, operator 13 Nov 2026).

``cio_pages.py`` built one product. This module builds any product in ``CATALOGUE`` with the same guarantees, outside
the web process:

* The build runs in a forked child with ``RLIMIT_AS``, a deadline (SIGKILL), a 2 MB body cap and a read-only DB
  session (``default_transaction_read_only=on``). ``peak_rss_kb`` is the child's own ``ru_maxrss``.
* Concurrency is HOST-WIDE (operator correction 15:07 ET): one ``flock`` per (product, scope) under
  ``LOCK_DIR`` (no duplicate builds of the same product on this host, from any process or lane), plus a fixed pool of
  ``SLOT_COUNT`` slot files (no more than N builds of any product at once). A busy product lock or a full pool is
  SKIPPED_BUSY; nothing queues. Live runs also take the Postgres advisory try-lock (DB-wide single flight).
  ``LOCK_DIR`` is an env-overridable path so the containment agent's shared slot pool can replace it at fold.
* Publish is conditional (``store_pg.write_current``): a build whose source clock (``as_of``) or check time is older
  than the stored row is refused (REFUSED_OLDER) and the newer row stays.
* A failed build writes no body: the last good row stays, ``reason`` on the row names the failure
  (``store_pg.mark_failed``), and the build log has the receipt.
* ``as_of`` is the SOURCE clock the build function reports, never the build time, so a fresh build of stale source
  stays stale on the read path. ``input_version`` (sha256 of the source watermarks) is recorded in the watermarks.

Build functions live in ``builders.py``: ``fn(ctx) -> {"data", "as_of", "source_watermarks", "status", "reason"}``.
This module must never import ``api_v2``.

CLI: ``python3 scripts/cc_products_build.py --product market_risk.latest --dry-run`` prints the receipt JSON.
"""
from __future__ import annotations

import contextlib
import datetime as _dtmod
import decimal
import fcntl
import hashlib
import importlib
import json
import os
import resource
import select
import signal
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.lib.cc_products.cio_pages import (
    _HEADER_SLACK,
    MAX_BODY_BYTES,
    PERSISTENT_STATE_ROOT,
    READ_ONLY_PGOPTIONS,
    BuildFailed,
    BuildRefused,
    BuildTimeout,
    _reap,
    _write_all,
)

ET = ZoneInfo("America/New_York")
CODE_ROOT = Path(__file__).resolve().parents[3]
PURGE_AFTER_S = 604800  # DSN 3.3 + operator Q8
DEFAULT_RLIMIT_MB = 512  # DSN 4.4
#: Off-hours tier (DSN §3: outside 09:30-16:15 ET weekdays every fast product refreshes hourly).
OFF_HOURS = {"cadence_s": 3600, "stale_after_s": 9000, "hard_expiry_s": 14400}
LOCK_DIR = Path(os.environ.get("TRADEAI_CC_PRODUCT_LOCK_DIR")
                or (PERSISTENT_STATE_ROOT / "data" / "ops" / "cc_products_locks"))
SLOT_COUNT = int(os.environ.get("TRADEAI_CC_BUILDER_SLOTS", "2"))
#: Bounded wait for a free builder slot (rework 2026-11-13 item 5). Lanes whose crons fire in the same minute used to
#: lose the slot race and log SKIPPED_BUSY; a waiter now polls for up to this long. The product lock stays
#: non-blocking: a second build of the SAME product/scope is still SKIPPED_BUSY at once. slot wait + builder timeout
#: stays under the lane runner timeout (ProductSpec.runner_timeout_s, asserted in tests).
SLOT_WAIT_S = float(os.environ.get("TRADEAI_CC_BUILDER_SLOT_WAIT_S", "20"))
SLOT_POLL_S = 0.25
#: Publish margin after the child returns (connect, UPSERT, log, commit, hot SET).
PUBLISH_MARGIN_S = 10.0

_OK, _ERR = b"O", b"E"


@dataclass(frozen=True)
class ProductSpec:
    product_id: str
    lane: str
    build: str  # "module:function" under scripts.lib.cc_products
    cadence_s: int
    stale_after_s: int
    hard_expiry_s: int
    timeout_s: float
    scope_key: str = "global"
    schema_version: int = 1
    off_hours: bool = True  # False for nightly tiers whose limits are already longer than the off-hours tier
    rlimit_mb: int = DEFAULT_RLIMIT_MB
    #: n8n allowlist timeout_s for the lane that runs this product (generator: builder timeout + 40).
    runner_timeout_s: float = 0.0


CATALOGUE: dict[str, ProductSpec] = {s.product_id: s for s in (
    # DSN catalogue live.market_risk: 60 s / 3 min / 5 min (operator Q1: 5 min in market hours, 4 h off-hours).
    # One body serves /api/v2/market-risk/latest AND /api/v2/home/cio-card (LQ-1352: one record, two routes).
    ProductSpec("market_risk.latest", "dp-live", "builders:build_market_risk", 60, 180, 300, 50.0,
                runner_timeout_s=90.0),
    # Phase 7 risk tier (cio.pages limits): 2 min / 6 min / 30 min.
    ProductSpec("risk", "dp-fast", "builders:build_risk", 120, 360, 1800, 100.0,
                runner_timeout_s=140.0),
    # shell.static tier: nightly / 36 h / 7 d. The legacy route re-verified files on disk per request; the
    # builder verifies them once per run. Cadence 6 h so a report generated during the day appears the same day.
    ProductSpec("reports.analyst_links", "dp-slow", "builders:build_analyst_links", 21600, 129600, 604800, 240.0,
                off_hours=False, runner_timeout_s=280.0),
    # home.status tier: 1 min / 3 min / 15 min. Slices: since_close, incidents, approvals_summary,
    # priorities_live, status, gates - each with its own source clock.
    ProductSpec("home", "dp-live", "builders:build_home", 60, 180, 900, 50.0,
                runner_timeout_s=90.0),
)}


def is_market_hours(now: datetime) -> bool:
    et = now.astimezone(ET)
    if et.weekday() >= 5:
        return False
    minutes = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= minutes < 16 * 60 + 15


def limits_for(spec: ProductSpec, now: datetime) -> dict:
    """cadence/stale/hard for this moment. Off-hours a fast product moves to the hourly tier (DSN §3)."""
    lim = {"cadence_s": spec.cadence_s, "stale_after_s": spec.stale_after_s, "hard_expiry_s": spec.hard_expiry_s}
    if spec.off_hours and not is_market_hours(now):
        lim = dict(OFF_HOURS)
    lim["purge_after_s"] = PURGE_AFTER_S
    return lim


def json_default(o):
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (datetime, _dtmod.date, _dtmod.time)):
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    return str(o)


def input_version(marks: dict) -> str:
    """sha256 over the source watermarks minus our own bookkeeping keys: the build's input identity."""
    clean = {k: v for k, v in (marks or {}).items() if not str(k).startswith("_")}
    return "sha256:" + hashlib.sha256(json.dumps(clean, sort_keys=True, default=json_default).encode()).hexdigest()[:32]


def parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, _dtmod.date):
        return datetime(value.year, value.month, value.day, tzinfo=ET).astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith(" ET"):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S ET").replace(tzinfo=ET)
        except ValueError:
            return None
    try:
        ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------------------ host-wide locks


class HostLocks:
    """flock per (product, scope) + a SLOT_COUNT pool, released when the context exits or the process dies (the
    kernel drops flocks with the fd), so a crashed builder never leaves a stale lock.

    The product lock is non-blocking. The slot pool waits up to ``slot_wait_s`` (bounded, polling) so lanes that fire
    in the same minute queue briefly instead of skipping."""

    def __init__(self, lock_dir: Path | None = None, slots: int | None = None, slot_wait_s: float | None = None):
        self.lock_dir = Path(lock_dir or LOCK_DIR)
        self.slots = int(SLOT_COUNT if slots is None else slots)
        self.slot_wait_s = max(0.0, float(SLOT_WAIT_S if slot_wait_s is None else slot_wait_s))
        self.slot_waited_s = 0.0

    def _try(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        return fd

    @contextlib.contextmanager
    def acquire(self, product_id: str, scope_key: str):
        """Yields None when acquired, else a reason string (product busy / no free slot)."""
        safe = f"{product_id}__{scope_key}".replace("/", "_")
        held: list[int] = []
        try:
            fd = self._try(self.lock_dir / f"product-{safe}.lock")
            if fd is None:
                yield f"busy: another {product_id}/{scope_key} build holds the host lock"
                return
            held.append(fd)
            t0 = time.monotonic()
            deadline = t0 + self.slot_wait_s
            sfd = None
            while True:
                for i in range(max(1, self.slots)):
                    sfd = self._try(self.lock_dir / f"slot-{i}.lock")
                    if sfd is not None:
                        break
                if sfd is not None or time.monotonic() >= deadline:
                    break
                time.sleep(min(SLOT_POLL_S, max(0.0, deadline - time.monotonic())))
            self.slot_waited_s = round(time.monotonic() - t0, 3)
            if sfd is None:
                yield f"busy: all {self.slots} host builder slots in use after waiting {self.slot_wait_s:g}s"
                return
            held.append(sfd)
            yield None
        finally:
            for fd in held:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)


# ------------------------------------------------------------------------------------------------ the child


class BuildContext:
    """What a build function gets. ``db_query`` returns None on error (api_v2 ``_db_query`` contract);
    ``db_query_raising`` lets errors propagate (``_db_query_raising``); ``get_conn`` is the read-only connection."""

    def __init__(self, *, code_root: Path, state_root: Path, db_query, db_query_raising, get_conn, now: datetime):
        self.code_root = Path(code_root)
        self.state_root = Path(state_root)
        self.db_query = db_query
        self.db_query_raising = db_query_raising
        self.get_conn = get_conn
        self.now = now

    # The server reads PROJECT_ROOT/data/runtime and PROJECT_ROOT/data/portfolios/state; in a release checkout both
    # are symlinks into persistent-state/data, so the builder reads the same files through the state root (and a
    # dry run from a worktree reads production state, not the worktree's empty data/).
    @property
    def data_dir(self) -> Path:
        return self.state_root / "data"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def portfolio_state_dir(self) -> Path:
        return self.data_dir / "portfolios" / "state"


def readonly_db(application_name: str = "cc_products.builder"):
    """(db_query, db_query_raising, get_conn) over ONE read-only psycopg2 connection. Every statement this build
    issues runs with ``default_transaction_read_only=on``; library code that opens its own ``db_adapter`` connection
    inherits the same setting through PGOPTIONS (set in the child before anything connects)."""
    scripts_dir = str(CODE_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import db_adapter  # noqa: F401 - side effect: DB_* env loaded

    if not db_adapter.USE_DB:
        return (lambda sql, params=None, fetch="all": None), (lambda sql, params=None, fetch="all": None), (lambda: None)
    import psycopg2
    import psycopg2.extras

    state: dict[str, Any] = {"conn": None}

    def get_conn():
        conn = state["conn"]
        if conn is None or conn.closed:
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                password=os.getenv("DB_PASSWORD", ""), connect_timeout=10, application_name=application_name,
                options=(READ_ONLY_PGOPTIONS + " -c statement_timeout=30s -c lock_timeout=3s"
                         " -c idle_in_transaction_session_timeout=120s -c jit=off"))
            conn.set_session(readonly=True, autocommit=False)
            state["conn"] = conn
        return conn

    def db_query_raising(sql, params=None, fetch="all"):
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                out = cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else True
            conn.rollback()
            return out
        except Exception:
            try:
                conn.rollback()
            except Exception:
                state["conn"] = None
            raise

    def db_query(sql, params=None, fetch="all"):
        try:
            return db_query_raising(sql, params, fetch)
        except Exception:
            return None

    return db_query, db_query_raising, get_conn


def resolve_build(spec: ProductSpec) -> Callable:
    mod_name, fn_name = spec.build.split(":")
    mod = importlib.import_module(f"scripts.lib.cc_products.{mod_name}")
    return getattr(mod, fn_name)


def _child_main(w: int, spec: ProductSpec, build_fn, ctx_factory, rlimit_as_bytes) -> None:
    code = 1
    try:
        os.dup2(2, 1)
        os.environ["PGOPTIONS"] = (os.environ.get("PGOPTIONS", "") + " " + READ_ONLY_PGOPTIONS).strip()
        if rlimit_as_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (int(rlimit_as_bytes), int(rlimit_as_bytes)))
        ctx = ctx_factory()
        result = build_fn(ctx)
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError("build function returned no data")
        body = json.dumps(result["data"], sort_keys=True, default=json_default).encode("utf-8")
        marks = dict(result.get("source_watermarks") or {})
        header = json.dumps({"as_of": result.get("as_of"), "source_watermarks": marks,
                             "status": result.get("status") or "OK", "reason": result.get("reason")},
                            sort_keys=True, default=json_default).encode("utf-8")
        del result
        _write_all(w, _OK + struct.pack(">I", len(header)) + header + body)
        code = 0
    except MemoryError:
        code = 4
        with contextlib.suppress(BaseException):
            _write_all(w, _ERR + b"MemoryError: build exceeded its address-space limit")
    except BaseException as exc:  # noqa: BLE001
        code = 3
        with contextlib.suppress(BaseException):
            _write_all(w, _ERR + (type(exc).__name__ + ": " + str(exc))[:2000].encode("utf-8", "replace"))
    finally:
        os._exit(code)


def build_in_child(spec: ProductSpec, *, build_fn: Callable | None = None, ctx_factory: Callable | None = None,
                   timeout_s: float | None = None, rlimit_as_bytes: int | None = None) -> dict:
    """Same contract as ``cio_pages.build_in_child``: returns body/as_of/status/reason/build_ms/peak_rss_kb/
    source_watermarks or raises BuildTimeout / BuildRefused / BuildFailed. The child is always reaped."""
    build_fn = build_fn or resolve_build(spec)
    timeout_s = float(spec.timeout_s if timeout_s is None else timeout_s)
    rlimit = spec.rlimit_mb * 1024 * 1024 if rlimit_as_bytes is None else rlimit_as_bytes
    if ctx_factory is None:
        def ctx_factory():
            q, qr, gc = readonly_db("cc_products." + spec.product_id)
            return BuildContext(code_root=CODE_ROOT, state_root=Path(os.environ.get("TRADEAI_STATE_ROOT")
                                                                     or PERSISTENT_STATE_ROOT),
                                db_query=q, db_query_raising=qr, get_conn=gc, now=datetime.now(timezone.utc))
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    r, w = os.pipe()
    started = time.monotonic()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        _child_main(w, spec, build_fn, ctx_factory, rlimit)
    os.close(w)
    deadline = started + timeout_s
    limit = MAX_BODY_BYTES + _HEADER_SLACK
    chunks: list[bytes] = []
    size = 0
    reaped = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.kill(pid, signal.SIGKILL)
                reaped = _reap(pid)
                raise BuildTimeout(f"build exceeded {timeout_s:g}s; child SIGKILLed", pid=pid,
                                   peak_rss_kb=int(reaped[2].ru_maxrss))
            ready, _, _ = select.select([r], [], [], min(remaining, 1.0))
            if not ready:
                continue
            chunk = os.read(r, 1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                os.kill(pid, signal.SIGKILL)
                reaped = _reap(pid)
                raise BuildRefused(f"body over {MAX_BODY_BYTES} bytes", pid=pid,
                                   peak_rss_kb=int(reaped[2].ru_maxrss))
        while reaped is None:
            got = _reap(pid, os.WNOHANG)
            if got[0] == pid:
                reaped = got
                break
            if time.monotonic() >= deadline:
                os.kill(pid, signal.SIGKILL)
                reaped = _reap(pid)
                raise BuildTimeout(f"child did not exit within {timeout_s:g}s; SIGKILLed", pid=pid,
                                   peak_rss_kb=int(reaped[2].ru_maxrss))
            time.sleep(0.01)
    finally:
        os.close(r)
        if reaped is None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                _reap(pid)
    build_ms = int((time.monotonic() - started) * 1000)
    _, status, usage = reaped
    peak = int(usage.ru_maxrss)
    data = b"".join(chunks)
    if os.WIFSIGNALED(status):
        raise BuildFailed(f"child killed by signal {os.WTERMSIG(status)}", pid=pid, peak_rss_kb=peak)
    if data[:1] == _ERR:
        raise BuildFailed(data[1:].decode("utf-8", "replace") or "child build failed", pid=pid, peak_rss_kb=peak)
    if os.WEXITSTATUS(status) != 0 or data[:1] != _OK or len(data) < 5:
        raise BuildFailed(f"child exited {os.WEXITSTATUS(status)} without a result frame", pid=pid, peak_rss_kb=peak)
    (hlen,) = struct.unpack(">I", data[1:5])
    try:
        header = json.loads(data[5:5 + hlen])
    except ValueError as exc:
        raise BuildFailed(f"bad result header: {exc}", pid=pid, peak_rss_kb=peak) from None
    body = data[5 + hlen:]
    if len(body) > MAX_BODY_BYTES:
        raise BuildRefused(f"body {len(body)} bytes over {MAX_BODY_BYTES}", pid=pid, peak_rss_kb=peak)
    marks = header.get("source_watermarks") or {}
    return {"body": body, "as_of": header.get("as_of"), "status": header.get("status") or "OK",
            "reason": header.get("reason"), "build_ms": build_ms, "peak_rss_kb": peak, "source_watermarks": marks,
            "input_version": input_version(marks)}


# ------------------------------------------------------------------------------------------------ run once


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def run_once(spec: ProductSpec, *, connect, hot=None, dry_run: bool, now=None, builder_sha: str = "",
             store=None, codec=None, locks: HostLocks | None = None, **kw) -> dict:
    """One build of ``spec``. Returns the receipt (same shape for a dry run).

    Order: host flock + slot (busy → SKIPPED_BUSY) → [live: PG advisory try-lock] → child build →
    [live: conditional publish + build-log row in one transaction → COMMIT → hot SET]. A dry run takes the host
    locks (so it never doubles a live build) and writes nothing: no ``connect``, no PG row, no hot key.
    """
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    started_at = clock()
    lim = limits_for(spec, started_at)
    scope_key = spec.scope_key
    receipt: dict[str, Any] = {
        "product_id": spec.product_id, "scope_key": scope_key, "lane": spec.lane, "dry_run": bool(dry_run),
        "outcome": None, "started_at": _iso(started_at), "finished_at": None, "build_ms": None, "peak_rss_kb": None,
        "bytes": None, "as_of": None, "input_version": None, "build_status": None, "build_reason": None,
        "source_watermarks": None, "etag": None, "seq": None, "wrote": False, "hot": None, "error": None,
        "builder_sha": builder_sha or None, "limits": lim, "pid": os.getpid(),
    }
    locks = locks or HostLocks()
    with locks.acquire(spec.product_id, scope_key) as busy:
        if busy:
            receipt.update(outcome="SKIPPED_BUSY", error=busy, finished_at=_iso(clock()), build_ms=0)
            if not dry_run and connect is not None:
                _log_only(spec, connect, store, receipt, started_at)
            return receipt
        return _run_locked(spec, connect=connect, hot=hot, dry_run=dry_run, clock=clock, started_at=started_at,
                           lim=lim, builder_sha=builder_sha, store=store, codec=codec, receipt=receipt, **kw)


def _log_only(spec, connect, store, receipt, started_at):
    if store is None:
        from scripts.lib.cc_products import store_pg as store
    conn = connect()
    try:
        cur = conn.cursor()
        store.log_build(cur, spec.product_id, spec.scope_key, receipt["outcome"], started_at=started_at,
                        finished_at=parse_ts(receipt["finished_at"]) or started_at, build_ms=0, lane=spec.lane,
                        error=receipt.get("error"), detail={"host_lock": receipt.get("error")})
        conn.commit()
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _run_locked(spec, *, connect, hot, dry_run, clock, started_at, lim, builder_sha, store, codec, receipt, **kw):
    pid_, scope_key, lane = spec.product_id, spec.scope_key, spec.lane

    def _build():
        try:
            result = build_in_child(spec, **kw)
        except BuildTimeout as exc:
            receipt.update(outcome="TIMEOUT", error=exc.reason, peak_rss_kb=exc.peak_rss_kb)
            return None
        except BuildRefused as exc:
            receipt.update(outcome="REFUSED", error=exc.reason, peak_rss_kb=exc.peak_rss_kb)
            return None
        except BuildFailed as exc:
            receipt.update(outcome="FAILED", error=exc.reason, peak_rss_kb=exc.peak_rss_kb)
            return None
        receipt.update(build_ms=result["build_ms"], peak_rss_kb=result["peak_rss_kb"], bytes=len(result["body"]),
                       as_of=result["as_of"], source_watermarks=result["source_watermarks"],
                       input_version=result["input_version"], build_status=result["status"],
                       build_reason=result["reason"])
        return result

    if dry_run:
        t0 = time.monotonic()
        result = _build()
        if result is None:
            receipt["build_ms"] = int((time.monotonic() - t0) * 1000)
        else:
            receipt["outcome"] = "OK" if parse_ts(result["as_of"]) is not None else "FAILED"
            if receipt["outcome"] == "FAILED":
                receipt["error"] = f"build produced no readable as_of ({result['as_of']!r})"
        receipt["finished_at"] = _iso(clock())
        return receipt

    if store is None:
        from scripts.lib.cc_products import store_pg as store
    if codec is None and hot is not None:
        from scripts.lib.cc_products import hot_tier as codec

    row = None
    as_of_dt = None
    built_at = None
    conn = connect()
    try:
        cur = conn.cursor()
        if not store.try_lock(cur, pid_, scope_key):
            finished = clock()
            store.log_build(cur, pid_, scope_key, "SKIPPED_BUSY", started_at=started_at, finished_at=finished,
                            build_ms=0, lane=lane)
            conn.commit()
            receipt.update(outcome="SKIPPED_BUSY", finished_at=_iso(finished), build_ms=0)
            return receipt
        t0 = time.monotonic()
        result = _build()
        built_at = clock()
        if result is not None:
            as_of_dt = parse_ts(result["as_of"])
            if as_of_dt is None:
                receipt.update(outcome="FAILED", error=f"build produced no readable as_of ({result['as_of']!r})")
                result = None
        if result is None:
            build_ms = receipt.get("build_ms") or int((time.monotonic() - t0) * 1000)
            store.log_build(cur, pid_, scope_key, receipt["outcome"], started_at=started_at, finished_at=built_at,
                            build_ms=build_ms, lane=lane, peak_rss_kb=receipt["peak_rss_kb"], error=receipt["error"])
            store.mark_failed(cur, pid_, scope_key, f"{receipt['outcome']}: {receipt['error']}")
            row = store.read_current(cur, pid_, scope_key) if hot is not None else None
            conn.commit()
            receipt.update(finished_at=_iso(built_at), build_ms=build_ms)
        else:
            marks = dict(result["source_watermarks"])
            marks["_product"] = {**(marks.get("_product") or {}), "input_version": result["input_version"],
                                 "builder": spec.build}
            try:
                written = store.write_current(
                    cur, pid_, scope_key, result["body"], as_of=as_of_dt, built_at=built_at,
                    next_refresh_at=built_at + timedelta(seconds=lim["cadence_s"]),
                    stale_after_s=lim["stale_after_s"], hard_expiry_s=lim["hard_expiry_s"],
                    purge_after_s=lim["purge_after_s"], source_watermarks=marks, builder_sha=builder_sha,
                    build_ms=result["build_ms"], status="DEGRADED" if result["status"] == "DEGRADED" else "OK",
                    reason=result["reason"], schema_version=spec.schema_version)
            except Exception as exc:
                if type(exc).__name__ != "BodyTooLarge":
                    raise
                conn.rollback()
                cur = conn.cursor()
                store.log_build(cur, pid_, scope_key, "REFUSED", started_at=started_at, finished_at=built_at,
                                build_ms=result["build_ms"], lane=lane, peak_rss_kb=result["peak_rss_kb"],
                                bytes_=len(result["body"]), error=str(exc)[:500])
                conn.commit()
                receipt.update(outcome="REFUSED", error=str(exc)[:500], finished_at=_iso(built_at))
                return receipt
            if written.get("refused"):
                outcome = "REFUSED_OLDER"
                receipt["error"] = "stored row is newer (as_of/checked_at); this build was not published"
            else:
                outcome = "OK" if written.get("changed") else "UNCHANGED"
            store.log_build(cur, pid_, scope_key, outcome, started_at=started_at, finished_at=built_at,
                            build_ms=result["build_ms"], lane=lane, peak_rss_kb=result["peak_rss_kb"],
                            bytes_=len(result["body"]), error=receipt["error"],
                            detail={"input_version": result["input_version"], "as_of": _iso(as_of_dt)})
            if outcome != "REFUSED_OLDER" and hot is not None:
                row = store.read_current(cur, pid_, scope_key)
            conn.commit()
            receipt.update(outcome=outcome, wrote=outcome in ("OK", "UNCHANGED"), etag=written.get("etag"),
                           seq=written.get("seq"), finished_at=_iso(built_at))
    except BaseException:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    # Hot tier strictly after the PG commit (DSN §8.3); key expiry = hard expiry minus the row's age.
    if hot is None or row is None:
        receipt["hot"] = "skipped"
        return receipt
    ref = parse_ts(row.get("as_of")) or built_at
    ex_s = int((row.get("hard_expiry_s") or 0) - max(0.0, (built_at - ref).total_seconds()))
    if ex_s < 1:
        receipt["hot"] = "skipped: past hard expiry"
        return receipt
    try:
        hot.set(codec.product_key(pid_, scope_key, int(row.get("schema_version") or 1)), codec.pack(row), ex_s)
        receipt["hot"] = "set"
    except Exception as exc:  # noqa: BLE001 - the PG row is authoritative
        receipt["hot"] = "error: " + type(exc).__name__
    return receipt


# ------------------------------------------------------------------------------------------------ CLI


def _rw_connect():
    scripts_dir = str(CODE_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import db_adapter  # noqa: F401
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""), connect_timeout=10, application_name="cc_products.publish",
        options="-c statement_timeout=30s -c lock_timeout=3s -c idle_in_transaction_session_timeout=300s")


def main(argv=None) -> int:
    """Same as ``scripts/cc_products_build.py`` (the lane entrypoint owns the argv contract)."""
    import importlib.util

    spec_ = importlib.util.spec_from_file_location("cc_products_build", CODE_ROOT / "scripts" / "cc_products_build.py")
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return run_cli(mod.parse(argv))


def run_cli(args) -> int:
    spec = CATALOGUE[args.product]
    kw: dict[str, Any] = {}
    if args.timeout is not None:
        kw["timeout_s"] = args.timeout
    if args.rlimit_mb is not None:
        kw["rlimit_as_bytes"] = args.rlimit_mb * 1024 * 1024
    if args.dry_run:
        receipt = run_once(spec, connect=None, dry_run=True, builder_sha=args.builder_sha, **kw)
    else:
        from scripts.lib.cc_products.hot_tier import HotTier

        receipt = run_once(spec, connect=_rw_connect, hot=HotTier(), dry_run=False, builder_sha=args.builder_sha,
                           **kw)
    print(json.dumps(receipt, sort_keys=True, default=json_default))
    # REFUSED_OLDER exits 0: the conditional publish kept a NEWER stored row (another builder won the race). It is
    # DEGRADED (health contract check refused_older reads cc_product_build_log), never RUN_FAILED.
    return 0 if receipt.get("outcome") in ("OK", "UNCHANGED", "SKIPPED_BUSY", "REFUSED_OLDER") else 1


if __name__ == "__main__":
    sys.exit(main())

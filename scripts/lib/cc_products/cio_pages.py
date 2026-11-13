"""Background builder for the ``cio.pages`` product (LQ-20261107-2595, DSN-20261112-PRECOMPUTE-CACHE).

GET /api/v2/cio/pages used to run ``w7_pages.page_payload`` inside the server (18-30 s; reaped request threads kept
computing and RSS killed the server about every 14 minutes). This module builds the same payload out of process:

* ``build_payload`` is the pure build. It runs only inside a forked child.
* ``build_in_child`` forks, caps the child's address space with ``RLIMIT_AS``, reads the JSON body through a pipe
  against a deadline, SIGKILLs the child on timeout, and always reaps it (``os.wait4``), so no zombie is left.
* ``run_once`` takes the product's advisory try-lock, builds, writes ``cc_product_current`` and the build log in one
  transaction, commits, and only then refreshes the hot tier. A failure or timeout logs FAILED/TIMEOUT and leaves the
  stored row untouched (last good kept). ``dry_run`` builds and measures and writes nothing anywhere.

This module must never import ``api_v2`` (DSN 5.1: a tick lane pays process start, and api_v2 is the server).
``store_pg`` and ``hot_tier`` are imported lazily inside ``run_once`` so tests can inject fakes. No AI call, no broker.

CLI: ``python -m scripts.lib.cc_products.cio_pages --dry-run [--root PATH] [--timeout S]`` prints the receipt JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import select
import signal
import struct
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

PRODUCT_ID = "cio.pages"
SCOPE_KEY = "global"
CADENCE_S = 120
#: Build deadline. Under the cadence so a build never runs into the next tick. The 12 Nov cold dry run took
#: 73.9 s at host load ~29 (receipt in the LQ-2595 READY); p95 above half the cadence is an open finding.
BUILD_TIMEOUT_S = 110.0
STALE_AFTER_S = 360
HARD_EXPIRY_S = 1800
PURGE_AFTER_S = 604800  # DSN 3.3 + operator Q8 (7 days for every tier)

MAX_BODY_BYTES = 2 * 1024 * 1024  # DSN 4.4: one stored body is capped at 2 MB; a bigger build is REFUSED
_HEADER_SLACK = 256 * 1024  # the frame header (watermarks) is small; anything past body cap + slack is refused
DEFAULT_RLIMIT_AS = 512 * 1024 * 1024  # DSN 4.4: one builder run, 512 MB
PERSISTENT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
READ_ONLY_PGOPTIONS = "-c default_transaction_read_only=on"

_OK, _ERR = b"O", b"E"


class BuildFailed(Exception):
    """The child build failed: it raised, ran out of address space, died on a signal or sent a bad frame."""

    def __init__(self, reason: str, *, pid: int | None = None, peak_rss_kb: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.pid = pid
        self.peak_rss_kb = peak_rss_kb


class BuildTimeout(BuildFailed):
    """The child did not finish before the deadline. It was SIGKILLed and reaped."""


class BuildRefused(BuildFailed):
    """The body is over MAX_BODY_BYTES (DSN 4.4). The child was stopped and reaped; the last good is kept."""


# ---------------------------------------------------------------------------------------------------- the build


def build_payload(root, *, db_query, ledger_root=None) -> dict:
    """The ``/api/v2/cio/pages`` payload, exactly as the server computed it: ``w7_pages.page_payload``.

    Everything is injected. This runs only inside the child that ``build_in_child`` forks.
    """
    from scripts.lib.w7_pages import page_payload

    return page_payload(root, db_query=db_query, ledger_root=ledger_root)


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def source_watermarks(payload: dict) -> dict:
    """Per section (a top-level object that carries ``as_of`` or ``gap``): its ``as_of`` and whether it has a gap."""
    marks: dict[str, dict] = {}
    if not isinstance(payload, dict):
        return marks
    for name, section in payload.items():
        if isinstance(section, dict) and ("as_of" in section or "gap" in section):
            raw = section.get("as_of")
            marks[str(name)] = {"as_of": raw if raw is None or isinstance(raw, str) else str(raw),
                                "gap": bool(section.get("gap"))}
    return marks


def oldest_section_as_of(payload: dict) -> str | None:
    """The OLDEST parseable section ``as_of`` (ISO-8601 UTC), or None. Recorded, not used as the product clock.

    Null or unparseable values are skipped; naive timestamps are read as UTC.
    """
    stamps = [ts for ts in (_parse_ts(m["as_of"]) for m in source_watermarks(payload).values()) if ts is not None]
    return min(stamps).astimezone(timezone.utc).isoformat() if stamps else None


def product_clock(payload: dict, sources_read_at: datetime) -> tuple[str, dict]:
    """The product ``as_of`` and the ``source_watermarks`` to store with it.

    LQ-2595 integration rule: ``cio.pages`` is a composite (DSN 3.1/3.2). Every section carries its own ``as_of``
    and the page draws that stamp per section, so one lagging slice greys its own tile, not the whole page. The
    product-level ``as_of`` is therefore the moment this build started reading its sources: it ages when the
    builder stops, which is what the product's stale and hard-expiry limits must catch. The oldest section clock
    would make the whole page UNKNOWN whenever any one input lags (the 12 Nov dry run: ``concentration_policy``
    is a policy publish date, 2026-10-24; ``regime`` is two hours old after the close). That oldest value is kept
    in ``source_watermarks["_product"]`` so nothing is hidden.
    """
    marks = source_watermarks(payload)
    marks["_product"] = {"as_of_rule": "sources_read_at", "oldest_section_as_of": oldest_section_as_of(payload)}
    return sources_read_at.astimezone(timezone.utc).isoformat(), marks


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def _child_main(w: int, root, build_fn, db_query_factory, ledger_root, rlimit_as_bytes) -> None:
    """Runs in the forked child. Never returns: always ``os._exit``."""
    code = 1
    try:
        os.dup2(2, 1)  # keep the parent's stdout (the CLI receipt) clean of anything the build prints
        os.environ["PGOPTIONS"] = (os.environ.get("PGOPTIONS", "") + " " + READ_ONLY_PGOPTIONS).strip()
        if rlimit_as_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (int(rlimit_as_bytes), int(rlimit_as_bytes)))
        db_query = db_query_factory() if db_query_factory is not None else readonly_db_query_factory()
        sources_read_at = datetime.now(timezone.utc)
        payload = build_fn(root, db_query=db_query, ledger_root=ledger_root)
        body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        as_of, marks = product_clock(payload, sources_read_at)
        header = json.dumps({"as_of": as_of, "source_watermarks": marks}, sort_keys=True, default=str).encode("utf-8")
        del payload
        _write_all(w, _OK + struct.pack(">I", len(header)) + header + body)
        code = 0
    except MemoryError:
        code = 4
        try:
            _write_all(w, _ERR + b"MemoryError: build exceeded its address-space limit")
        except BaseException:
            pass
    except BaseException as exc:  # noqa: BLE001 - the child reports every failure and exits
        code = 3
        try:
            _write_all(w, _ERR + (type(exc).__name__ + ": " + str(exc))[:2000].encode("utf-8", "replace"))
        except BaseException:
            pass
    finally:
        os._exit(code)


def _reap(pid: int, flags: int = 0):
    """``os.wait4`` that tolerates EINTR. Returns (pid, status, rusage) or (0, 0, None) on WNOHANG with no exit."""
    while True:
        try:
            return os.wait4(pid, flags)
        except InterruptedError:
            continue


def build_in_child(root, *, timeout_s: float = BUILD_TIMEOUT_S, rlimit_as_bytes: int = DEFAULT_RLIMIT_AS,
                   db_query_factory: Callable | None = None, ledger_root=None,
                   build_fn: Callable | None = None) -> dict:
    """Build in a forked child bounded by ``timeout_s`` and ``RLIMIT_AS``.

    Returns ``{"body", "as_of", "build_ms", "peak_rss_kb", "source_watermarks"}``. Raises ``BuildTimeout`` (child
    SIGKILLed), ``BuildRefused`` (body over 2 MB) or ``BuildFailed`` (raised, MemoryError, nonzero exit, signal).
    The child is reaped on every path, so it never lingers as a zombie.

    ``db_query_factory`` is called in the child; None means ``readonly_db_query_factory`` (production).
    ``build_fn`` defaults to ``build_payload`` and exists so tests can inject a fast build.

    ``peak_rss_kb`` is the child's own ``ru_maxrss`` from ``os.wait4`` (Linux reports KB). It is per child, so it is
    exact where ``getrusage(RUSAGE_CHILDREN)`` deltas are not (that is a max over all reaped children). It includes
    pages inherited from the parent at fork that the child touched.
    """
    build_fn = build_fn or build_payload
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()  # a buffered line must not be written twice (once by the child's copy)
        except Exception:
            pass
    r, w = os.pipe()
    started = time.monotonic()
    pid = os.fork()
    if pid == 0:  # child
        os.close(r)
        _child_main(w, root, build_fn, db_query_factory, ledger_root, rlimit_as_bytes)
    os.close(w)
    deadline = started + float(timeout_s)
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
        # EOF: the child has written and is exiting. Wait for it, still inside the deadline.
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
        if reaped is None:  # an unexpected error in the parent: never leave the child running or unreaped
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                _reap(pid)
            except ChildProcessError:
                pass
    build_ms = int((time.monotonic() - started) * 1000)
    _, status, usage = reaped
    peak_rss_kb = int(usage.ru_maxrss)
    data = b"".join(chunks)
    del chunks
    if os.WIFSIGNALED(status):
        raise BuildFailed(f"child killed by signal {os.WTERMSIG(status)}", pid=pid, peak_rss_kb=peak_rss_kb)
    if data[:1] == _ERR:
        raise BuildFailed(data[1:].decode("utf-8", "replace") or "child build failed", pid=pid,
                          peak_rss_kb=peak_rss_kb)
    exit_code = os.WEXITSTATUS(status)
    if exit_code != 0 or data[:1] != _OK or len(data) < 5:
        raise BuildFailed(f"child exited {exit_code} without a result frame", pid=pid, peak_rss_kb=peak_rss_kb)
    (hlen,) = struct.unpack(">I", data[1:5])
    try:
        header = json.loads(data[5:5 + hlen])
    except ValueError as exc:
        raise BuildFailed(f"bad result header: {exc}", pid=pid, peak_rss_kb=peak_rss_kb) from None
    body = data[5 + hlen:]
    if len(body) > MAX_BODY_BYTES:
        raise BuildRefused(f"body {len(body)} bytes over {MAX_BODY_BYTES}", pid=pid, peak_rss_kb=peak_rss_kb)
    return {"body": body, "as_of": header.get("as_of"), "build_ms": build_ms, "peak_rss_kb": peak_rss_kb,
            "source_watermarks": header.get("source_watermarks") or {}, "pid": pid}


# ------------------------------------------------------------------------------------------- production wiring


def readonly_db_query_factory() -> Callable:
    """A ``db_query(sql, params=None, fetch="all")`` over ONE read-only psycopg2 connection (builder reads only).

    Mirrors the server's ``api_v2._db_query`` contract (rows as dicts; None when the DB is off or a query fails)
    and ``db_adapter._get_conn``'s credentials and safety nets, plus ``default_transaction_read_only=on``, so no
    statement this build issues can write. Importing ``db_adapter`` loads the DB env (env_bootstrap / .env).
    """
    scripts_dir = str(Path(__file__).resolve().parents[2])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import db_adapter  # noqa: F401 - side effect: DB_* env loaded

    if not db_adapter.USE_DB:
        return lambda sql, params=None, fetch="all": None
    import psycopg2
    import psycopg2.extras

    state: dict[str, Any] = {"conn": None}

    def _conn():
        conn = state["conn"]
        if conn is None or conn.closed:
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                password=os.getenv("DB_PASSWORD", ""), connect_timeout=10,
                application_name="cc_products.cio_pages",
                options=(READ_ONLY_PGOPTIONS + " -c statement_timeout=60s -c lock_timeout=3s"
                         " -c idle_in_transaction_session_timeout=120s -c jit=off"),
            )
            conn.set_session(readonly=True, autocommit=False)
            state["conn"] = conn
        return conn

    def db_query(sql, params=None, fetch="all"):
        try:
            conn = _conn()
        except Exception:
            return None
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                result = cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else True
            conn.rollback()  # read-only: end the transaction without committing anything
            return result
        except Exception:
            try:
                conn.rollback()
            except Exception:
                state["conn"] = None
            return None

    return db_query


def default_ledger_root() -> Path:
    """The durable root that holds data/conflicts/, as ``scripts.lib.conflicts.api._root`` resolves it."""
    from scripts.lib.persistent_state_root import resolve_durable_dir

    return Path(resolve_durable_dir("data/conflicts")).parent.parent


def default_state_root() -> Path:
    """The directory that contains data/ (the server passes ``STATE_DIR.parents[2]``)."""
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or PERSISTENT_STATE_ROOT)


# ------------------------------------------------------------------------------------------------------ run once


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def run_once(*, connect, root, hot=None, dry_run: bool, now=None, builder_sha="", timeout_s=BUILD_TIMEOUT_S,
             store=None, codec=None, scope_key: str = SCOPE_KEY, lane: str | None = None, **kw) -> dict:
    """One build of ``cio.pages``. Returns the receipt dict (same shape for a dry run).

    Live: try-lock (busy → log SKIPPED_BUSY, no build) → ``build_in_child`` → ``write_current`` + log OK|UNCHANGED in
    the lock's transaction → COMMIT → hot SET (only after the commit; a hot-tier failure is recorded, never fatal).
    Timeout/failure → log TIMEOUT|FAILED (REFUSED for an over-cap body) and commit; ``cc_product_current`` is not
    touched, so the last good stays.

    ``dry_run=True`` builds and measures and writes NOTHING: it does not call ``connect`` at all (no lock, no store
    write, no build-log row) and never touches the hot tier. The build's own DB reads are read-only regardless.

    ``store`` / ``codec`` default to ``store_pg`` / ``hot_tier`` (imported lazily); tests inject fakes. ``kw`` goes
    to ``build_in_child`` (``rlimit_as_bytes``, ``db_query_factory``, ``ledger_root``, ``build_fn``).
    """
    clock = (lambda: now) if now is not None else (lambda: datetime.now(timezone.utc))
    started_at = clock()
    receipt: dict[str, Any] = {
        "product_id": PRODUCT_ID, "scope_key": scope_key, "dry_run": bool(dry_run), "outcome": None,
        "started_at": _iso(started_at), "finished_at": None, "build_ms": None, "peak_rss_kb": None, "bytes": None,
        "as_of": None, "source_watermarks": None, "etag": None, "seq": None, "wrote": False, "hot": None,
        "error": None, "builder_sha": builder_sha or None,
    }

    def _build():
        try:
            result = build_in_child(root, timeout_s=timeout_s, **kw)
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
                       as_of=result["as_of"], source_watermarks=result["source_watermarks"])
        return result

    if dry_run:
        t0 = time.monotonic()
        result = _build()
        if result is None:
            receipt["build_ms"] = int((time.monotonic() - t0) * 1000)
        else:
            receipt["outcome"] = "OK"
        receipt["finished_at"] = _iso(clock())
        return receipt

    if store is None:
        from scripts.lib.cc_products import store_pg as store
    if codec is None and hot is not None:
        from scripts.lib.cc_products import hot_tier as codec

    conn = connect()
    try:
        cur = conn.cursor()
        if not store.try_lock(cur, PRODUCT_ID, scope_key):
            finished = clock()
            store.log_build(cur, PRODUCT_ID, scope_key, "SKIPPED_BUSY", started_at=started_at, finished_at=finished,
                            build_ms=0, lane=lane)
            conn.commit()
            receipt.update(outcome="SKIPPED_BUSY", finished_at=_iso(finished), build_ms=0)
            return receipt
        t0 = time.monotonic()
        result = _build()
        if result is None:
            finished = clock()
            build_ms = int((time.monotonic() - t0) * 1000)
            store.log_build(cur, PRODUCT_ID, scope_key, receipt["outcome"], started_at=started_at,
                            finished_at=finished, build_ms=build_ms, lane=lane, peak_rss_kb=receipt["peak_rss_kb"],
                            error=receipt["error"])
            conn.commit()
            receipt.update(finished_at=_iso(finished), build_ms=build_ms)
            return receipt
        built_at = clock()
        as_of_dt = _parse_ts(result["as_of"])
        try:
            written = store.write_current(
                cur, PRODUCT_ID, scope_key, result["body"], as_of=as_of_dt, built_at=built_at,
                next_refresh_at=built_at + timedelta(seconds=CADENCE_S), stale_after_s=STALE_AFTER_S,
                hard_expiry_s=HARD_EXPIRY_S, purge_after_s=PURGE_AFTER_S,
                source_watermarks=result["source_watermarks"], builder_sha=builder_sha,
                build_ms=result["build_ms"])
        except Exception as exc:
            if type(exc).__name__ != "BodyTooLarge":
                raise
            conn.rollback()
            cur = conn.cursor()
            store.log_build(cur, PRODUCT_ID, scope_key, "REFUSED", started_at=started_at, finished_at=built_at,
                            build_ms=result["build_ms"], lane=lane, peak_rss_kb=result["peak_rss_kb"],
                            bytes_=len(result["body"]), error=str(exc)[:500])
            conn.commit()
            receipt.update(outcome="REFUSED", error=str(exc)[:500], finished_at=_iso(built_at))
            return receipt
        outcome = "OK" if written.get("changed") else "UNCHANGED"
        store.log_build(cur, PRODUCT_ID, scope_key, outcome, started_at=started_at, finished_at=built_at,
                        build_ms=result["build_ms"], lane=lane, peak_rss_kb=result["peak_rss_kb"],
                        bytes_=len(result["body"]))
        row = store.read_current(cur, PRODUCT_ID, scope_key) if hot is not None else None
        conn.commit()
        receipt.update(outcome=outcome, wrote=True, etag=written.get("etag"), seq=written.get("seq"),
                       finished_at=_iso(built_at))
    except BaseException:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Hot tier strictly after the PG commit: a reader can never see a body the store does not hold.
    if hot is None or row is None:
        receipt["hot"] = "skipped"
        return receipt
    clock_from = as_of_dt or built_at
    # age never below 0 (clock skew, or a test that pins built_at): the key may not outlive the hard expiry
    ex_s = int(HARD_EXPIRY_S - max(0.0, (built_at - clock_from).total_seconds()))
    if ex_s < 1:
        receipt["hot"] = "skipped: past hard expiry"
        return receipt
    try:
        hot.set(codec.product_key(PRODUCT_ID, scope_key), codec.pack(row), ex_s)
        receipt["hot"] = "set"
    except Exception as exc:  # HotTierDown or anything else: the PG row is authoritative
        receipt["hot"] = "error: " + type(exc).__name__
    return receipt


# ----------------------------------------------------------------------------------------------------------- CLI


def _rw_connect():
    """A read-write connection for a live run (the store write); the build itself reads with a read-only one."""
    scripts_dir = str(Path(__file__).resolve().parents[2])
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import db_adapter  # noqa: F401 - loads the DB env
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""), connect_timeout=10, application_name="cc_products.cio_pages",
        options="-c statement_timeout=30s -c lock_timeout=3s -c idle_in_transaction_session_timeout=300s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.lib.cc_products.cio_pages", description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="build and measure; write nothing (no PG, no hot tier)")
    ap.add_argument("--root", default=None, help="state root that contains data/ (default TRADEAI_STATE_ROOT or "
                                                 "the persistent-state root)")
    ap.add_argument("--timeout", type=float, default=BUILD_TIMEOUT_S, help="build deadline in seconds (default %(default)s)")
    ap.add_argument("--rlimit-mb", type=int, default=DEFAULT_RLIMIT_AS // (1024 * 1024))
    ap.add_argument("--builder-sha", default=os.environ.get("TRADEAI_BUILDER_SHA", ""))
    ap.add_argument("--lane", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else default_state_root()
    common = dict(root=root, dry_run=args.dry_run, builder_sha=args.builder_sha, timeout_s=args.timeout,
                  rlimit_as_bytes=args.rlimit_mb * 1024 * 1024, ledger_root=default_ledger_root(), lane=args.lane)
    if args.dry_run:
        receipt = run_once(connect=None, **common)
    else:
        from scripts.lib.cc_products.hot_tier import HotTier

        receipt = run_once(connect=_rw_connect, hot=HotTier(), **common)
    print(json.dumps(receipt, sort_keys=True, default=str))
    return 0 if receipt.get("outcome") in ("OK", "UNCHANGED", "SKIPPED_BUSY") else 1


if __name__ == "__main__":
    sys.exit(main())

"""LQ-20261107-2595 (d)/(e): /api/v2/cio/pages is served from the stored product and never builds on a request.

Four layers of proof:

1. Module: ``serve_cio_pages`` returns a page for OK, STALE, UNKNOWN (last good, greyed), BUILDING and
   store-unavailable while ``page_payload``, ``project_pages`` and ``cio_truth.resolve`` raise.
2. Postgres: the production ``fetch_row`` raises (never returns None) when the store fails, and a read
   blocked behind a lock is cancelled by its 250 ms statement timeout. Uses an isolated initdb cluster.
3. Load: 30 threads x 10 calls against a ~700 KB stored body. Peak traced memory stays within the decoded
   size per concurrent caller, threads return to baseline, the build is never entered and nobody parks on a
   build lock. The same driver against the c238eec68 ``_w7_cio_pages`` logic (copied below) enters the
   build and parks callers on the single-flight lock: that is the fail-before.
4. api_v2 (opt-in): imports the PATCHED api_v2 from a scratch tree under bwrap --unshare-net and calls
   ``_w7_cio_pages()``. Runs only when CC_APIV2_PATCHED_TREE names that tree.

No test touches the production DB, the real Valkey, the live server or the canonical checkout.
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from scripts.lib.cc_products import cio_pages_route as route  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 0, 0, tzinfo=timezone.utc)
PANELS = ("portfolio", "positions", "stops", "regime", "approvals", "cio_status", "capital", "do_now",
          "companies", "sectors")


# ── helpers ──────────────────────────────────────────────────────────────────

class BuildCounter:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError("build on request")


@pytest.fixture
def no_build(monkeypatch):
    """Every entry into the build path raises and is counted."""
    from scripts.lib import cio_truth, w7_pages

    counter = BuildCounter()
    monkeypatch.setattr(w7_pages, "page_payload", counter)
    monkeypatch.setattr(w7_pages, "project_pages", counter)
    monkeypatch.setattr(cio_truth, "resolve", counter)
    return counter


def small_payload() -> dict:
    return {name: {"source": "CIO", "as_of": "2026-11-12T14:58:00+00:00", "value": i} for i, name in enumerate(PANELS)}


def big_payload(target_bytes: int = 700_000) -> dict:
    """A synthetic page payload shaped like the real one (10 panels, row lists), ~target_bytes as JSON."""
    out = small_payload()
    rows, i = [], 0
    while True:
        rows.append({"symbol": f"S{i:05d}", "account_label": f"Account {i % 7}", "market_value": 1000.0 + i,
                     "weight_pct": round(i * 0.013, 4), "stop": {"price": 10.5 + i, "working": bool(i % 2)},
                     "stance": "HOLD", "reason": "synthetic row for the no-request-build load test"})
        i += 1
        if i % 200 == 0 and len(json.dumps(rows)) >= target_bytes:
            break
    out["positions"] = {"source": "CIO", "as_of": "2026-11-12T14:58:00+00:00", "rows": rows}
    return out


def row_for(body: bytes, *, age_s: float, as_of_null: bool = False) -> dict:
    as_of = NOW - timedelta(seconds=age_s)
    return {"product_id": "cio.pages", "scope_key": "global", "body": body, "etag": "sha256:test", "seq": 42,
            "as_of": None if as_of_null else as_of, "built_at": as_of, "next_refresh_at": NOW + timedelta(seconds=60),
            "stale_after_s": 360, "hard_expiry_s": 1800, "purge_after_s": 604800, "status": "OK",
            "source_watermarks": {}, "builder_sha": "test", "bytes": len(body), "build_ms": 5}


def envelope(status, *, data=None, last_good=None, reason=None):
    return {"product": "cio.pages", "scope": "global", "status": status, "as_of": "2026-11-12T14:58:00+00:00",
            "built_at": "2026-11-12T14:58:30+00:00", "next_refresh_at": None, "stale_after_s": 360,
            "hard_expiry_s": 1800, "age_s": 120, "seq": 9, "etag": "sha256:e", "reason": reason, "data": data,
            "last_good": last_good, "served_from": "pg"}


def fake_reader(env):
    def read_product(product_id, scope_key="global", *, fetch_row, hot=None, now=None, budget_ms=250):
        assert product_id == "cio.pages" and scope_key == "global"
        return env
    return read_product


# ── 1. module level: every status answers, the build path is never entered ─

@pytest.mark.parametrize("status", ["OK", "STALE"])
def test_ok_and_stale_return_stored_payload_with_clocks(no_build, status):
    out = route.serve_cio_pages(read_product=fake_reader(envelope(status, data=small_payload())))
    assert out["portfolio"]["value"] == 0 and set(PANELS) <= set(out)
    assert out["_product"]["status"] == status and out["_product"]["greyed"] is False
    assert out["_product"]["seq"] == 9 and out["_product"]["served_from"] == "pg"
    assert "data" not in out  # the front end's unwrap() keys on a top-level "data"; it must stay absent
    assert no_build.calls == 0


def test_unknown_past_hard_expiry_serves_last_good_greyed(no_build):
    env = envelope("UNKNOWN", last_good=small_payload(), reason="past hard expiry; last good 2026-11-12T14:00:00")
    out = route.serve_cio_pages(read_product=fake_reader(env))
    assert out["sectors"]["value"] == 9
    assert out["_product"] == {**out["_product"], "status": "UNKNOWN", "greyed": True}
    assert out["_product"]["reason"].startswith("past hard expiry")
    assert no_build.calls == 0


def test_building_returns_unavailable_gaps(no_build):
    out = route.serve_cio_pages(read_product=fake_reader(envelope("BUILDING", reason="not built yet")))
    assert out["_product"]["status"] == "BUILDING" and out["_product"]["greyed"] is False
    assert all("being built" in out[p]["gap"] for p in PANELS)
    assert no_build.calls == 0


def test_store_unavailable_returns_unknown_gaps(no_build):
    out = route.serve_cio_pages(read_product=fake_reader(envelope("UNKNOWN", reason="product store unavailable")))
    assert out["_product"]["status"] == "UNKNOWN" and out["_product"]["greyed"] is False
    assert all("product store unavailable" in out[p]["gap"] for p in PANELS)
    assert no_build.calls == 0


def test_reader_crash_is_unknown_not_a_build(no_build):
    def boom(*a, **k):
        raise RuntimeError("reader defect")
    out = route.serve_cio_pages(read_product=boom)
    assert out["_product"]["status"] == "UNKNOWN" and "RuntimeError" in out["_product"]["reason"]
    assert no_build.calls == 0


def test_real_read_path_every_status(no_build):
    """The same five answers through the real read_path, with fake stored rows."""
    pytest.importorskip("scripts.lib.cc_products.read_path")
    body = json.dumps(small_payload()).encode()

    def fetch(row):
        return lambda pid, scope="global": row

    cases = {"OK": row_for(body, age_s=30), "STALE": row_for(body, age_s=600), "UNKNOWN": row_for(body, age_s=4000)}
    for want, row in cases.items():
        out = route.serve_cio_pages(fetch_row=fetch(row), now=NOW)
        assert out["_product"]["status"] == want, want
        assert out["portfolio"]["value"] == 0
        assert out["_product"]["greyed"] is (want == "UNKNOWN")
    out = route.serve_cio_pages(fetch_row=fetch(None), now=NOW)
    assert out["_product"]["status"] == "BUILDING"

    def down(pid, scope="global"):
        raise route.StoreUnavailable("no database connection")
    out = route.serve_cio_pages(fetch_row=down, now=NOW)
    assert out["_product"]["status"] == "UNKNOWN" and out["_product"]["reason"] == "product store unavailable"
    out = route.serve_cio_pages(now=NOW)  # nothing wired at all: unavailable, never a build
    assert out["_product"]["status"] == "UNKNOWN"
    assert no_build.calls == 0


# ── 2. the production fetch_row ─────────────────────────────────────────────

def test_fetch_row_sql_sets_a_local_statement_timeout_first():
    seen = []

    def q(sql, params=None, fetch="all"):
        seen.append((sql, params, fetch))
        return []
    assert route.make_pg_fetch_row(q)("cio.pages", "global") is None
    sql, params, fetch = seen[0]
    assert sql.startswith("SET LOCAL statement_timeout = '250ms'; SELECT ")
    assert params == ("cio.pages", "global") and fetch == "all"


def test_fetch_row_never_turns_a_failure_into_no_row():
    def raising(sql, params=None, fetch="all"):
        raise RuntimeError("canceling statement due to statement timeout")
    with pytest.raises(RuntimeError):
        route.make_pg_fetch_row(raising)("cio.pages")
    with pytest.raises(route.StoreUnavailable):  # _db_query_raising returns None when there is no DB/connection
        route.make_pg_fetch_row(lambda *a, **k: None)("cio.pages")
    row = route.make_pg_fetch_row(lambda *a, **k: [{"body": memoryview(b"{}"), "seq": 1}])("cio.pages")
    assert row == {"body": b"{}", "seq": 1} and type(row["body"]) is bytes


try:
    from support.isolated_pg import IsolatedPostgres, pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False


@pytest.fixture(scope="module")
def iso_pg():
    if not HAVE_PG:
        pytest.skip("no PostgreSQL server binaries on this host")
    psycopg2 = pytest.importorskip("psycopg2")
    from scripts.lib.cc_products import store_pg

    pg = IsolatedPostgres()
    try:
        pg.start()
        pg.verify_isolated()
        conn = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.dbname, user=pg.user, password=pg.password)
        with conn.cursor() as cur:
            cur.execute(store_pg.TEST_DDL)
            body = json.dumps(small_payload()).encode()
            cur.execute(
                "INSERT INTO cc_product_current (product_id, scope_key, body, etag, seq, as_of, built_at, "
                "next_refresh_at, stale_after_s, hard_expiry_s, purge_after_s, status) "
                "VALUES ('cio.pages','global',%s,'sha256:x',3,now(),now(),now(),360,1800,604800,'OK')",
                (psycopg2.Binary(body),))
        conn.commit()
        yield pg, conn
        conn.close()
    finally:
        pg.stop()


def _raising_query(conn):
    """The _db_query_raising contract (api_v2.py ~31604) over a test connection."""
    import psycopg2.extras

    def q(sql, params=None, fetch="all"):
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                out = cur.fetchone() if fetch == "one" else cur.fetchall()
            conn.commit()
            return out
        except Exception:
            conn.rollback()
            raise
    return q


def test_fetch_row_against_isolated_postgres(iso_pg):
    _, conn = iso_pg
    fetch = route.make_pg_fetch_row(_raising_query(conn))
    row = fetch("cio.pages", "global")
    assert type(row["body"]) is bytes and json.loads(row["body"])["portfolio"]["value"] == 0
    assert row["seq"] == 3 and row["as_of"].tzinfo is not None
    assert fetch("cio.pages", "nope") is None
    with conn.cursor() as cur:  # SET LOCAL ended with the transaction; the session timeout is untouched
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone()[0] == "0"
    conn.rollback()


def test_blocked_store_read_is_cancelled_and_served_unknown(iso_pg, no_build):
    """A read stuck behind a lock gives up at 250 ms; the page is UNKNOWN, never a wait and never a build."""
    import psycopg2

    pg, conn = iso_pg
    holder = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.dbname, user=pg.user, password=pg.password)
    release = None
    try:
        with holder.cursor() as cur:
            cur.execute("LOCK TABLE cc_product_current IN ACCESS EXCLUSIVE MODE")
        release = threading.Timer(3.0, holder.rollback)  # a mutant without the timeout waits here, then fails
        release.start()
        fetch = route.make_pg_fetch_row(_raising_query(conn))
        t0 = time.monotonic()
        with pytest.raises(psycopg2.errors.QueryCanceled):
            fetch("cio.pages", "global")
        assert time.monotonic() - t0 < 1.5
        pytest.importorskip("scripts.lib.cc_products.read_path")
        t0 = time.monotonic()
        out = route.serve_cio_pages(fetch_row=fetch, now=NOW)
        assert time.monotonic() - t0 < 1.5
        assert out["_product"]["status"] == "UNKNOWN" and out["_product"]["reason"] == "product store unavailable"
    finally:
        if release is not None:  # never leave the timer thread behind for the thread-count test below
            release.cancel()
            release.join()
        holder.rollback()
        holder.close()
    assert no_build.calls == 0


# ── 3. load: 30 threads x 10 calls, after and before ────────────────────────

THREADS, PER_THREAD = 30, 10


class CountingLock:
    """A Lock that counts callers who had to wait for it (parked on a build)."""
    parked = 0
    _guard = threading.Lock()

    def __init__(self):
        self._l = threading.Lock()

    def __enter__(self):
        if not self._l.acquire(blocking=False):
            with CountingLock._guard:
                CountingLock.parked += 1
            self._l.acquire()
        return self

    def __exit__(self, *exc):
        self._l.release()


def _drive(call) -> dict:
    gc.collect()
    baseline = threading.active_count()
    barrier = threading.Barrier(THREADS)
    errors, walls, wl = [], [], threading.Lock()

    def worker():
        barrier.wait()
        for _ in range(PER_THREAD):
            t = time.perf_counter()
            try:
                out = call()
                assert "positions" in out
            except BaseException as e:  # noqa: BLE001
                errors.append(repr(e))
                return
            w = time.perf_counter() - t
            del out
            with wl:
                walls.append(w)

    tracemalloc.start()
    tracemalloc.reset_peak()
    ts = [threading.Thread(target=worker) for _ in range(THREADS)]
    t0 = time.perf_counter()
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=120)
    total = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    time.sleep(0.05)
    walls.sort()
    return {"peak": peak, "baseline_threads": baseline, "after_threads": threading.active_count(),
            "errors": errors, "calls": len(walls), "total_s": round(total, 3),
            "p50_ms": round(walls[len(walls) // 2] * 1000, 1) if walls else None,
            "max_ms": round(walls[-1] * 1000, 1) if walls else None}


def _one_call_peak(call) -> int:
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()
    out = call()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del out
    return peak


def _assert_no_request_build(m: dict, *, bound: int, build_calls: int, parked: int):
    assert not m["errors"], m["errors"][:3]
    assert m["calls"] == THREADS * PER_THREAD
    assert m["after_threads"] == m["baseline_threads"], "threads left parked"
    assert build_calls == 0, f"build entered {build_calls}x on a request"
    assert parked == 0, f"{parked} callers parked on a build lock"
    assert m["peak"] < bound, f"peak {m['peak']} >= bound {bound}"


@pytest.fixture(scope="module")
def big():
    payload = big_payload()
    body = json.dumps(payload, sort_keys=True).encode()
    assert 650_000 <= len(body) <= 800_000
    return payload, body


def _record(name: str, data: dict):
    sink = os.environ.get("CC_NO_REQUEST_BUILD_RECORD")
    print(f"\n[{name}] " + json.dumps(data, sort_keys=True))
    if sink:
        with open(sink, "a") as fh:
            fh.write(json.dumps({"case": name, **data}, sort_keys=True) + "\n")


def test_after_concurrent_reads_never_build_and_stay_bounded(no_build, big):
    """Bound: one call's traced peak (one decoded payload + its shallow copy) times the number of callers that
    can hold a decoded payload at the same moment (THREADS), plus 25 % headroom for interleaving. A build would
    add a full projection per caller on top of that; this bound is per-request decode only."""
    from scripts.lib.cc_products import read_path

    _, body = big
    row = row_for(body, age_s=30)
    fetch = lambda pid, scope="global": row  # noqa: E731
    call = lambda: route.serve_cio_pages(read_product=read_path.read_product, fetch_row=fetch, now=NOW)  # noqa: E731
    assert call()["_product"]["status"] == "OK"
    one = _one_call_peak(call)
    bound = int(THREADS * one * 1.25)
    CountingLock.parked = 0
    m = _drive(call)
    _record("after", {**m, "one_call_peak": one, "bound": bound, "body_bytes": len(body),
                      "bound_over_body": round(bound / len(body), 1), "build_calls": no_build.calls, "parked": 0})
    _assert_no_request_build(m, bound=bound, build_calls=no_build.calls, parked=0)


def _before_logic(page_payload_ref):
    """The c238eec68 _w7_cio_pages and _shared_get_cached (api_v2.py 48254-48297), copied verbatim except that
    the per-key lock is a CountingLock and the module globals are local. Not imported from api_v2."""
    import time as _t

    _SHARED_GET_CACHE: dict = {}
    _SHARED_GET_LOCKS: dict = {}
    _SHARED_GET_LOCKS_GUARD = threading.Lock()

    def _shared_get_cached(key: str, ttl_s: float, build):
        hit = _SHARED_GET_CACHE.get(key)
        if hit and _t.monotonic() - hit[0] < ttl_s:
            return hit[1]
        with _SHARED_GET_LOCKS_GUARD:
            lock = _SHARED_GET_LOCKS.setdefault(key, CountingLock())
        with lock:
            hit = _SHARED_GET_CACHE.get(key)
            if hit and _t.monotonic() - hit[0] < ttl_s:
                return hit[1]
            payload = build()
            _SHARED_GET_CACHE[key] = (_t.monotonic(), payload)
            return payload

    STATE_DIR = Path("/nonexistent/data/portfolios/state")

    def _db_query(*a, **k):
        return None

    def _conflict_ledger_root():
        return Path("/nonexistent")

    def _w7_cio_pages():
        page_payload = page_payload_ref()
        return _shared_get_cached(
            "cio_pages", 60.0,
            lambda: page_payload(STATE_DIR.parents[2], db_query=_db_query, ledger_root=_conflict_ledger_root()))

    return _w7_cio_pages


def test_before_logic_builds_on_request_and_parks_callers(big, monkeypatch):
    """Fail-before: the same driver and the same assertions against the old route logic."""
    from scripts.lib import w7_pages

    payload, body = big
    calls = {"n": 0}

    def slow_build(*a, **k):
        calls["n"] += 1
        scratch = bytearray(5 * 1024 * 1024)  # a build's working set
        time.sleep(0.2)
        scratch[0] = 1
        return json.loads(body)

    monkeypatch.setattr(w7_pages, "page_payload", slow_build)
    old = _before_logic(lambda: w7_pages.page_payload)
    CountingLock.parked = 0
    m = _drive(old)
    parked = CountingLock.parked
    _record("before", {**m, "build_calls": calls["n"], "parked": parked, "body_bytes": len(body)})
    assert calls["n"] >= 1, "the old logic builds on the request thread"
    assert parked >= 1, "concurrent callers park on the single-flight lock"
    with pytest.raises(AssertionError):
        _assert_no_request_build(m, bound=10**12, build_calls=calls["n"], parked=parked)


# ── 4. the api_v2 patch, imported for real (opt-in) ─────────────────────────

_APIV2_PROBE = r'''
import json, os, sys, threading
from datetime import datetime, timedelta, timezone
ROOT = sys.argv[1]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import api_v2 as api
from scripts.lib import w7_pages, cio_truth
from scripts.lib.cc_products import cio_pages_route as cpr
calls = {"n": 0}
BUILD_THREADS = []
def boom(*a, **k):
    calls["n"] += 1
    BUILD_THREADS.append(threading.current_thread())
    raise AssertionError("build on request")
w7_pages.page_payload = boom; w7_pages.project_pages = boom; cio_truth.resolve = boom
now = datetime.now(timezone.utc)
row = {"product_id": "cio.pages", "scope_key": "global", "body": memoryview(json.dumps({"portfolio": {"v": 1}}).encode()),
       "etag": "e", "seq": 7, "as_of": now - timedelta(seconds=30), "built_at": now, "next_refresh_at": None,
       "stale_after_s": 360, "hard_expiry_s": 1800, "purge_after_s": 604800, "status": "OK"}
mode = {"m": "ok"}; sqls = []
def fake_raising(sql, params=None, fetch="all"):
    sqls.append(sql)
    return {"ok": [dict(row)], "none": [], "nodb": None}.get(mode["m"]) if mode["m"] != "raise" else (_ for _ in ()).throw(RuntimeError("timeout"))
api._db_query_raising = fake_raising
cpr._HOT[:] = [None]
out = {"route_is_w7": api.ROUTES["/api/v2/cio/pages"] is api._w7_cio_pages}
for m in ("ok", "none", "nodb", "raise"):
    mode["m"] = m
    try:
        r = api._w7_cio_pages()
        out[m] = r["_product"]["status"]
    except BaseException as e:
        out[m] = "ERROR " + repr(e)[:120]
    if m == "ok":
        out["build_calls_while_fresh"] = calls["n"]
# LQ-2743: a miss (none/nodb/raise) starts the computed page on the SWR thread; the request itself never builds,
# so it still returns the stored status at once (the first poll has nothing computed yet).
out["request_built"] = any(t.name == "MainThread" for t in BUILD_THREADS)
out["timeout_sql"] = bool(sqls) and all("SET LOCAL statement_timeout = '250ms'" in s for s in sqls)
print("PROBE " + json.dumps(out, sort_keys=True)); sys.stdout.flush(); os._exit(0)
'''


@pytest.mark.skipif(not os.environ.get("CC_APIV2_PATCHED_TREE"), reason="set CC_APIV2_PATCHED_TREE to a scratch tree")
def test_patched_api_v2_route_never_builds(tmp_path):
    tree = Path(os.environ["CC_APIV2_PATCHED_TREE"]).resolve()
    canon = Path(sys.prefix).parent  # the checkout whose .venv runs this test (no hardcoded home path)
    releases = canon.parent.parent / "trade-ai-releases"
    if shutil.which("bwrap") is None or not (canon / ".venv/bin/python").exists():
        pytest.skip("needs bwrap and the project venv")
    assert canon not in tree.parents and tree != canon
    probe = tmp_path / "probe.py"
    probe.write_text(_APIV2_PROBE)
    state = tmp_path / "state"
    state.mkdir()
    # No network, no Postgres socket, no checkout .env, no /run/user secrets render, read-only everything else.
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-net", "--die-with-parent",
            "--tmpfs", str(canon.parent), "--ro-bind", str(canon / ".venv"), str(canon / ".venv"),
            "--tmpfs", str(releases), "--tmpfs", "/run/user", "--tmpfs", "/run/postgresql",
            "--tmpfs", "/tmp", "--bind", str(tree), str(tree), "--bind", str(tmp_path), str(tmp_path),
            "--setenv", "TRADEAI_STATE_ROOT", str(state), "--setenv", "DB_HOST", "127.0.0.1", "--setenv", "DB_PORT",
            "1", "--setenv", "DB_NAME", "none", "--setenv", "DB_USER", "none", "--setenv", "DB_PASSWORD", "none",
            "--setenv", "TRADEAI_ENV_BOOTSTRAP_FILES", "", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--chdir", str(tree), str(canon / ".venv/bin/python"), "-I", str(probe), str(tree)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("PROBE ")), None)
    assert line, (r.returncode, r.stderr[-2000:])
    out = json.loads(line[6:])
    _record("api_v2", out)
    assert out == {"route_is_w7": True, "ok": "OK", "none": "BUILDING", "nodb": "UNKNOWN", "raise": "UNKNOWN",
                   "build_calls_while_fresh": 0, "request_built": False, "timeout_sql": True}

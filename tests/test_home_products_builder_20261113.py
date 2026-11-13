"""home-products builder (operator 13 Nov 2026): single-flight, conditional publish, last-good, scope isolation,
stale sources stay stale, timed-out builds leave nothing running.

Synthetic build functions only. The PG cases run against a disposable initdb cluster built from the operator
migration (same harness as test_cc_products_store_pg.py); they never touch the production database.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from scripts.lib.cc_products import product_builder as pb  # noqa: E402
from scripts.lib.cc_products import product_route as pr  # noqa: E402

T0 = datetime(2026, 11, 13, 20, 0, 0, tzinfo=timezone.utc)  # Friday 15:00 ET, market hours


def spec(product_id="syn.product", scope_key="global", **kw):
    base = dict(product_id=product_id, lane="dp-test", build="builders:build_risk", cadence_s=60, stale_after_s=180,
                hard_expiry_s=300, timeout_s=20, scope_key=scope_key)
    base.update(kw)
    return pb.ProductSpec(**base)


def fake_build(as_of, payload=None, marks=None, status="OK"):
    def _b(ctx):
        return {"data": payload or {"v": as_of}, "as_of": as_of, "source_watermarks": marks or {"src": as_of},
                "status": status, "reason": None}
    return _b


def _ctx():
    return None


# ------------------------------------------------------------------------------------- host locks (no DB)


def test_held_product_lock_skips_and_never_builds(tmp_path):
    locks = pb.HostLocks(tmp_path, slots=2)

    def must_not_build(ctx):
        raise AssertionError("built while another build held the host lock")

    with locks.acquire("syn.product", "global") as busy:
        assert busy is None
        r = pb.run_once(spec(), connect=None, dry_run=True, locks=pb.HostLocks(tmp_path, slots=2),
                        build_fn=must_not_build, ctx_factory=_ctx)
    assert r["outcome"] == "SKIPPED_BUSY" and "host lock" in r["error"]


def test_full_slot_pool_skips(tmp_path):
    a, b = pb.HostLocks(tmp_path, slots=1), pb.HostLocks(tmp_path, slots=1)
    with a.acquire("syn.one", "global") as busy:
        assert busy is None
        with b.acquire("syn.two", "global") as busy2:
            assert busy2 and "slots in use" in busy2
    with b.acquire("syn.two", "global") as busy3:  # released on exit
        assert busy3 is None


def test_scopes_do_not_share_a_product_lock(tmp_path):
    locks = pb.HostLocks(tmp_path, slots=2)
    with locks.acquire("syn.product", "acct:A") as x, pb.HostLocks(tmp_path, slots=2).acquire("syn.product",
                                                                                              "acct:B") as y:
        assert x is None and y is None


def test_concurrent_runs_build_once(tmp_path):
    """Threads stand in for two lane runs on the host: the flock is per open file description, so one wins."""
    calls = []
    marker = tmp_path / "builds.log"

    def slow_build(ctx):
        with open(marker, "a") as f:
            f.write("x\n")
        time.sleep(1.0)
        return {"data": {"v": 1}, "as_of": T0.isoformat(), "source_watermarks": {}}

    out = []

    def go():
        out.append(pb.run_once(spec(), connect=None, dry_run=True, locks=pb.HostLocks(tmp_path / "l", slots=4),
                               build_fn=slow_build, ctx_factory=_ctx))

    ts = [threading.Thread(target=go) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    outcomes = sorted(r["outcome"] for r in out)
    assert outcomes.count("OK") == 1 and outcomes.count("SKIPPED_BUSY") == 3, outcomes
    assert marker.read_text().count("x") == 1
    del calls


def test_timed_out_build_leaves_nothing_running(tmp_path):
    pidfile = tmp_path / "child.pid"

    def hang(ctx):
        pidfile.write_text(str(os.getpid()))
        time.sleep(60)

    t0 = time.monotonic()
    with pytest.raises(pb.BuildTimeout):
        pb.build_in_child(spec(), build_fn=hang, ctx_factory=_ctx, timeout_s=1.0)
    assert time.monotonic() - t0 < 10
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # reaped: no zombie, no orphan still computing


def test_failed_child_build_is_reported_not_raised_into_the_lane(tmp_path):
    def boom(ctx):
        raise RuntimeError("synthetic source missing")

    r = pb.run_once(spec(), connect=None, dry_run=True, locks=pb.HostLocks(tmp_path), build_fn=boom,
                    ctx_factory=_ctx)
    assert r["outcome"] == "FAILED" and "synthetic source missing" in r["error"]


def test_input_version_ignores_private_marks():
    assert pb.input_version({"a": 1, "_product": {"x": 1}}) == pb.input_version({"a": 1})
    assert pb.input_version({"a": 1}) != pb.input_version({"a": 2})


def test_off_hours_limits():
    sat = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
    s = spec()
    assert pb.limits_for(s, T0)["hard_expiry_s"] == 300
    assert pb.limits_for(s, sat)["hard_expiry_s"] == pb.OFF_HOURS["hard_expiry_s"]
    assert pb.limits_for(spec(off_hours=False, hard_expiry_s=604800), sat)["hard_expiry_s"] == 604800


def test_builders_module_never_imports_the_web_process():
    src = (ROOT / "scripts" / "lib" / "cc_products" / "builders.py").read_text()
    route = (ROOT / "scripts" / "lib" / "cc_products" / "product_route.py").read_text()
    assert "import api_v2" not in src and "from scripts import api_v2" not in src
    for banned in ("builders", "product_builder", "cio_truth", "home_incidents", "market_risk_projection"):
        assert f"import {banned}" not in route and f"cc_products.{banned}" not in route, banned


# ------------------------------------------------------------------------------------------ PG-backed

try:
    from support.isolated_pg import IsolatedPostgres, pg_bin_dir

    pg_bin_dir()
    HAVE_PG = True
except Exception:  # noqa: BLE001
    HAVE_PG = False

needs_pg = pytest.mark.skipif(not HAVE_PG, reason="no PostgreSQL server binaries on this host")


@pytest.fixture(scope="module")
def cluster():
    if not HAVE_PG:
        pytest.skip("no PostgreSQL server binaries on this host")
    psycopg2 = pytest.importorskip("psycopg2")
    from scripts.lib.cc_products.store_pg import MIGRATION_PATH

    pg = IsolatedPostgres()
    try:
        pg.start()
        assert pg.verify_isolated()["verdict"] == "ISOLATED"
        c = psycopg2.connect(host=pg.host, port=pg.port, dbname=pg.dbname, user=pg.user, password=pg.password)
        c.autocommit = True
        with c.cursor() as cur:
            cur.execute("CREATE ROLE trade_ai NOLOGIN")
            cur.execute("GRANT CREATE, USAGE ON SCHEMA public TO trade_ai")
            cur.execute("SET ROLE trade_ai")
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute("RESET ROLE")
        c.close()
        yield pg
    finally:
        pg.stop()


@pytest.fixture
def connect(cluster):
    import psycopg2

    def _c():
        return psycopg2.connect(host=cluster.host, port=cluster.port, dbname=cluster.dbname, user=cluster.user,
                                password=cluster.password)

    c = _c()
    with c.cursor() as cur:
        cur.execute("TRUNCATE cc_product_current, cc_product_build_log")
    c.commit()
    c.close()
    return _c


def _row(connect, pid="syn.product", scope="global"):
    from scripts.lib.cc_products import store_pg

    c = connect()
    try:
        return store_pg.read_current(c.cursor(), pid, scope)
    finally:
        c.close()


def _log(connect, pid="syn.product"):
    c = connect()
    try:
        cur = c.cursor()
        cur.execute("SELECT outcome, detail, scope_key FROM cc_product_build_log WHERE product_id=%s ORDER BY id",
                    (pid,))
        return cur.fetchall()
    finally:
        c.close()


def _run(connect, tmp_path, as_of, *, now, s=None, **kw):
    return pb.run_once(s or spec(), connect=connect, dry_run=False, now=now, locks=pb.HostLocks(tmp_path / "l"),
                       build_fn=kw.pop("build_fn", None) or fake_build(as_of.isoformat(), **kw), ctx_factory=_ctx)


@needs_pg
def test_older_build_is_refused_and_newer_row_stays(connect, tmp_path):
    new = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10))
    assert new["outcome"] == "OK"
    old = _run(connect, tmp_path, T0 - timedelta(minutes=5), now=T0 + timedelta(seconds=5))
    assert old["outcome"] == "REFUSED_OLDER" and old["wrote"] is False
    row = _row(connect)
    assert row["as_of"] == T0 and row["seq"] == new["seq"]
    outcomes = [(o, (d or {}).get("receipt_outcome")) for o, d, _ in _log(connect)]
    assert outcomes[-1] == ("FAILED", "REFUSED_OLDER")


@needs_pg
def test_same_input_rebuild_is_unchanged_not_a_new_version(connect, tmp_path):
    a = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10))
    b = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=70))
    assert a["outcome"] == "OK" and b["outcome"] == "UNCHANGED" and a["seq"] == b["seq"]
    assert a["input_version"] == b["input_version"]


@needs_pg
def test_failed_build_keeps_last_good_and_says_why(connect, tmp_path):
    ok = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10))

    def boom(ctx):
        raise RuntimeError("synthetic upstream down")

    bad = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=70), build_fn=boom)
    assert bad["outcome"] == "FAILED"
    row = _row(connect)
    assert row["seq"] == ok["seq"] and row["as_of"] == T0 and bytes(row["body"]) == json.dumps(
        {"v": T0.isoformat()}, sort_keys=True).encode()
    assert "last build failed" in row["reason"] and "synthetic upstream down" in row["reason"]
    # served: the last good keeps aging from its own as_of, and the failure reason rides along
    env = pr.read_envelope("syn.product", fetch_row=lambda p, s="global": _row(connect, p, s), hot=None,
                           now=T0 + timedelta(seconds=100))
    assert env["status"] == "OK" and env.get("build_failure", "").startswith("last build failed")
    late = pr.read_envelope("syn.product", fetch_row=lambda p, s="global": _row(connect, p, s), hot=None,
                            now=T0 + timedelta(seconds=400))
    assert late["status"] == "UNKNOWN" and late.get("last_good") is not None
    # the next success clears the reason
    _run(connect, tmp_path, T0 + timedelta(seconds=60), now=T0 + timedelta(seconds=130))
    assert _row(connect)["reason"] is None


@needs_pg
def test_scope_isolation(connect, tmp_path):
    _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10), s=spec(scope_key="acct:A"), payload={"who": "A"})

    def boom(ctx):
        raise RuntimeError("B failed")

    _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10), s=spec(scope_key="acct:B"), build_fn=boom)
    a, b = _row(connect, scope="acct:A"), _row(connect, scope="acct:B")
    assert json.loads(bytes(a["body"])) == {"who": "A"} and a["reason"] is None
    assert b is None  # B's failure never wrote, never borrowed A
    assert _row(connect, scope="global") is None
    assert {s for _, _, s in _log(connect)} == {"acct:A", "acct:B"}


@needs_pg
def test_stale_source_stays_stale_after_a_fresh_build(connect, tmp_path):
    """The build ran just now, but its source is 10 minutes old: as_of is the SOURCE clock, so the product is past
    hard expiry (300 s) the moment it lands, and it is served UNKNOWN with last good greyed - never OK."""
    old_src = T0 - timedelta(minutes=10)
    r = _run(connect, tmp_path, old_src, now=T0)
    assert r["outcome"] == "OK"
    row = _row(connect)
    assert row["as_of"] == old_src and row["built_at"] == T0
    env = pr.read_envelope("syn.product", fetch_row=lambda p, s="global": _row(connect, p, s), hot=None, now=T0)
    assert env["status"] == "UNKNOWN" and env.get("last_good") is not None
    # 4 minutes old: STALE, not OK
    r2 = _run(connect, tmp_path, T0 - timedelta(minutes=4), now=T0 + timedelta(seconds=1))
    env2 = pr.read_envelope("syn.product", fetch_row=lambda p, s="global": _row(connect, p, s), hot=None,
                            now=T0 + timedelta(seconds=1))
    assert r2["outcome"] == "OK" and env2["status"] == "STALE"


@needs_pg
def test_host_busy_is_receipted(connect, tmp_path):
    locks = pb.HostLocks(tmp_path / "l")
    with locks.acquire("syn.product", "global"):
        r = pb.run_once(spec(), connect=connect, dry_run=False, now=T0, locks=pb.HostLocks(tmp_path / "l"),
                        build_fn=fake_build(T0.isoformat()), ctx_factory=_ctx)
    assert r["outcome"] == "SKIPPED_BUSY"
    assert _row(connect) is None
    assert [o for o, _, _ in _log(connect)] == ["SKIPPED_BUSY"]


def test_lane_entrypoint_owns_the_argv_contract():
    import importlib.util

    s = importlib.util.spec_from_file_location("cc_products_build", ROOT / "scripts" / "cc_products_build.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    a = m.parse(["--product", "home", "--dry-run"])
    assert a.product == "home" and a.dry_run is True
    assert m.parse(["--product", "risk"]).dry_run is False
    with pytest.raises(SystemExit):
        m.parse(["--product", "not.a.product"])
    assert set(pb.CATALOGUE) == {"market_risk.latest", "risk", "reports.analyst_links", "home"}

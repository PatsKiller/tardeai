"""home-products rework (2026-11-13): hot-tier race, schema compatibility, reader migration flag, risk display,
bounded slot wait, and the mutants the first review left alive (SF3, OW2, EX4, EX6, EX8).

Synthetic rows only. PG cases use the disposable initdb cluster from test_home_products_builder_20261113.py; nothing
here touches the production database, Valkey, the server or the network.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))

from scripts.lib.cc_products import hot_tier, product_builder as pb, product_route as pr, read_path, reader_flag  # noqa: E402
from scripts.lib.cc_products.hot_tier import pack, product_key  # noqa: E402

from test_home_products_builder_20261113 import (  # noqa: E402,F401 - PG fixtures reused
    T0, _ctx, _row, _run, cluster, connect, fake_build, needs_pg, spec)

NOW = datetime(2026, 11, 13, 20, 0, 0, tzinfo=timezone.utc)


def mkrow(age_s, *, schema=1, data=None, pid="syn.p", hard=300, stale=180, seq=5):
    body = json.dumps(data if data is not None else {"v": seq}).encode()
    return {"product_id": pid, "scope_key": "global", "body": body, "etag": f"e{seq}", "seq": seq,
            "as_of": NOW - timedelta(seconds=age_s), "built_at": NOW - timedelta(seconds=age_s),
            "next_refresh_at": None, "stale_after_s": stale, "hard_expiry_s": hard, "purge_after_s": 604800,
            "status": "OK", "reason": None, "schema_version": schema, "source_watermarks": {}}


class Hot:
    def __init__(self):
        self.store, self.sets = {}, []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex_s):
        self.sets.append((key, ex_s))
        self.store[key] = value


# ------------------------------------------------------------------------------------- blocker 3: hot-tier race


def test_slow_reader_never_overwrites_a_newer_hot_row():
    """Reader misses hot, reads v1 from PG; meanwhile the builder commits v2 and sets hot. The reader must leave v2
    in place (it never writes the hot tier at all)."""
    hot = Hot()
    key = product_key("syn.p")
    v2 = mkrow(1, seq=6)

    def slow_fetch(pid, scope):
        old = mkrow(30, seq=5)
        hot.store[key] = pack(v2)  # the builder publishes v2 while the reader is still in its PG read
        hot.sets.append(("builder", 299))
        return old

    env = read_path.read_product("syn.p", fetch_row=slow_fetch, hot=hot, now=NOW)
    assert env["seq"] == 5 and env["served_from"] == "pg"
    assert hot_tier.unpack(hot.store[key])["seq"] == 6, "the reader overwrote a newer hot row"
    assert hot.sets == [("builder", 299)], "the read path must never call hot.set"


def test_read_path_source_has_no_hot_set():
    import ast

    tree = ast.parse(inspect.getsource(read_path))
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "set" not in calls and "pack" not in names


# ----------------------------------------------------------------------------------- blocker 4: schema version


@pytest.mark.parametrize("reader,row_schema,ok", [(1, 1, True), (1, 2, False), (2, 1, False), (2, 2, True)])
def test_schema_version_is_checked_on_read(reader, row_schema, ok):
    env = read_path.read_product("syn.p", fetch_row=lambda p, s: mkrow(10, schema=row_schema), hot=None, now=NOW,
                                 schema_version=reader)
    if ok:
        assert env["status"] == "OK" and env["data"] == {"v": 5}
    else:  # old reader + new row, or new reader + old row: UNKNOWN, no data, no last good, no fallback
        assert env["status"] == "UNKNOWN" and env["data"] is None and env["last_good"] is None
        assert "incompatible schema_version" in env["reason"]


def test_incompatible_row_in_hot_is_rejected_too():
    hot = Hot()
    hot.store[product_key("syn.p", "global", 1)] = pack(mkrow(10, schema=2))  # mis-keyed entry
    env = read_path.read_product("syn.p", fetch_row=lambda p, s: None, hot=hot, now=NOW)
    assert env["status"] == "UNKNOWN" and env["served_from"] == "hot" and env["data"] is None


def test_hot_key_carries_the_schema_version():
    assert product_key("p", "s", 1) != product_key("p", "s", 2)
    hot = Hot()
    hot.store[product_key("syn.p", "global", 2)] = pack(mkrow(10, schema=2))
    calls = []
    env = read_path.read_product("syn.p", fetch_row=lambda p, s: calls.append(p) or mkrow(10, schema=1), hot=hot,
                                 now=NOW, schema_version=1)
    assert calls == ["syn.p"] and env["status"] == "OK"  # a v1 reader never sees the v2 cache entry


def test_unversioned_row_is_v1():
    row = mkrow(10)
    del row["schema_version"]
    assert read_path.read_product("syn.p", fetch_row=lambda p, s: row, now=NOW)["status"] == "OK"
    assert read_path.read_product("syn.p", fetch_row=lambda p, s: row, now=NOW, schema_version=2)["status"] == "UNKNOWN"


@needs_pg
def test_rollout_then_rollback_keeps_reader_and_row_compatible(connect, tmp_path):
    """v2 builder lands first (reader still v1: UNKNOWN, never a v2 body parsed as v1); reader moves to v2 (OK);
    rollback: builder back to v1 publishes a newer as_of over the v2 row and the v1 reader serves it."""
    def env(schema, now):
        return read_path.read_product("syn.product", fetch_row=lambda p, s: _row(connect, p, s), now=now,
                                      schema_version=schema)

    r = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=5), s=spec(schema_version=2))
    assert r["outcome"] == "OK" and _row(connect)["schema_version"] == 2
    assert env(1, T0 + timedelta(seconds=10))["status"] == "UNKNOWN"
    assert env(2, T0 + timedelta(seconds=10))["status"] == "OK"
    back = _run(connect, tmp_path, T0 + timedelta(seconds=60), now=T0 + timedelta(seconds=65),
                s=spec(schema_version=1))
    assert back["outcome"] == "OK" and _row(connect)["schema_version"] == 1
    assert env(1, T0 + timedelta(seconds=70))["status"] == "OK"
    assert env(2, T0 + timedelta(seconds=70))["status"] == "UNKNOWN"


def test_reader_and_catalogue_schema_versions_agree():
    """Flag flips in either direction never change the schema: every catalogue spec writes what the routes read."""
    reader_default = inspect.signature(read_path.read_product).parameters["schema_version"].default
    for s in pb.CATALOGUE.values():
        assert s.schema_version == reader_default, s.product_id


# ------------------------------------------------------------------------------------- mutant killers


@needs_pg
def test_sf3_pg_advisory_lock_held_elsewhere_is_skipped_busy(connect, tmp_path):
    other = connect()
    try:
        cur = other.cursor()
        cur.execute("BEGIN")
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s || '|' || %s, 0))",
                    ("syn.product", "global"))
        assert cur.fetchone()[0] is True
        built = []

        def b(ctx):
            built.append(1)
            return fake_build(T0.isoformat())(ctx)

        r = pb.run_once(spec(), connect=connect, dry_run=False, now=T0, locks=pb.HostLocks(tmp_path / "l"),
                        build_fn=b, ctx_factory=_ctx)
        assert r["outcome"] == "SKIPPED_BUSY" and built == []
        assert _row(connect) is None
    finally:
        other.rollback()
        other.close()


@needs_pg
def test_ow2_same_as_of_with_an_older_checked_at_is_refused(connect, tmp_path):
    a = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=20), payload={"v": "newer-check"})
    b = _run(connect, tmp_path, T0, now=T0 + timedelta(seconds=10), payload={"v": "older-check"})
    assert a["outcome"] == "OK" and b["outcome"] == "REFUSED_OLDER"
    assert json.loads(bytes(_row(connect)["body"])) == {"v": "newer-check"}


def test_ex4_market_risk_as_of_is_the_snapshot_clock(monkeypatch):
    from scripts.lib.cc_products import builders

    snap = "2026-11-13T19:45:00+00:00"
    monkeypatch.setattr(builders, "market_risk_projection", lambda ctx: {"state": "evaluated", "tier": "RED",
                                                                         "as_of": snap})
    monkeypatch.setattr(builders, "home_cio_card", lambda ctx, mr: ({"schema": "HomeCioCard@v1"}, {}))
    out = builders.build_market_risk(None)
    assert out["as_of"] == snap and out["status"] == "OK"


@needs_pg
def test_ex6_builder_hot_ttl_is_hard_expiry_minus_row_age(connect, tmp_path):
    hot = Hot()
    r = pb.run_once(spec(), connect=connect, dry_run=False, now=T0, hot=hot, locks=pb.HostLocks(tmp_path / "l"),
                    build_fn=fake_build((T0 - timedelta(seconds=200)).isoformat()), ctx_factory=_ctx)
    assert r["outcome"] == "OK" and r["hot"] == "set"
    (key, ex_s), = hot.sets
    assert key == product_key("syn.product", "global", 1) and 99 <= ex_s <= 100


def test_ex8_catalogue_limits_are_pinned():
    want = {"market_risk.latest": (60, 180, 300, 50.0, 90.0), "risk": (120, 360, 1800, 100.0, 140.0),
            "reports.analyst_links": (21600, 129600, 604800, 240.0, 280.0), "home": (60, 180, 900, 50.0, 90.0)}
    got = {k: (s.cadence_s, s.stale_after_s, s.hard_expiry_s, s.timeout_s, s.runner_timeout_s)
           for k, s in pb.CATALOGUE.items()}
    assert got == want
    assert pb.CATALOGUE["reports.analyst_links"].off_hours is False


# ----------------------------------------------------------------------------- item 5: bounded slot wait


def test_slot_wait_acquires_when_a_slot_frees(tmp_path):
    a = pb.HostLocks(tmp_path, slots=1, slot_wait_s=0)
    b = pb.HostLocks(tmp_path, slots=1, slot_wait_s=5)
    got = []
    with a.acquire("syn.one", "global") as busy:
        assert busy is None

        def waiter():
            with b.acquire("syn.two", "global") as busy2:
                got.append((busy2, b.slot_waited_s))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.6)
    t.join(10)
    assert got and got[0][0] is None and 0.3 <= got[0][1] < 5


def test_slot_wait_is_bounded(tmp_path):
    a = pb.HostLocks(tmp_path, slots=1, slot_wait_s=0)
    b = pb.HostLocks(tmp_path, slots=1, slot_wait_s=0.5)
    with a.acquire("syn.one", "global"):
        t0 = time.monotonic()
        with b.acquire("syn.two", "global") as busy:
            assert busy and "slots in use" in busy
        assert 0.4 <= time.monotonic() - t0 < 2.0


def test_same_product_never_waits(tmp_path):
    a = pb.HostLocks(tmp_path, slots=2, slot_wait_s=30)
    with a.acquire("syn.one", "global"):
        t0 = time.monotonic()
        with pb.HostLocks(tmp_path, slots=2, slot_wait_s=30).acquire("syn.one", "global") as busy:
            assert busy and "host lock" in busy
        assert time.monotonic() - t0 < 0.5


def test_slot_wait_plus_build_fits_the_runner_timeout():
    for s in pb.CATALOGUE.values():
        assert pb.SLOT_WAIT_S + s.timeout_s + pb.PUBLISH_MARGIN_S < s.runner_timeout_s, s.product_id


# --------------------------------------------------------------------------- item 6: reader migration flag


def test_flag_parse():
    modes, err = reader_flag.parse("risk=stored, home=STORED")
    assert err is None and modes["risk"] == "stored" and modes["home"] == "stored"
    assert modes["market_risk.latest"] == "legacy" and modes["cio.pages"] == "legacy"
    assert reader_flag.parse(None)[0] == {p: "legacy" for p in reader_flag.PRODUCTS}
    for bad in ("risk=on", "riks=stored", "risk", "risk=stored,home=maybe"):
        modes, err = reader_flag.parse(bad)
        assert err and set(modes.values()) == {"legacy"}, bad  # a typo never half-cuts a product over


LEGACY_FNS = {"/api/v2/risk": ("risk", "_risk_payload_cached", None),
              "/api/v2/home/since-close": ("home", "_home_since_close", None),
              "/api/v2/home/gates": ("home", "_home_gates", None),
              "/api/v2/home/cio-card": ("market_risk.latest", "_home_cio_card", None),
              "/api/v2/home/incidents": ("home", "_home_incidents", None),
              "/api/v2/home/priorities-live": ("home", "_home_priorities_live", None),
              "/api/v2/home/status": ("home", "_home_status", None),
              "/api/v2/reports/analyst/links": ("reports.analyst_links", "_reports_analyst_links", {}),
              "/api/v2/cio/pages": ("cio.pages", "_w7_cio_pages_legacy", None)}


@pytest.fixture
def api():
    import scripts.api_v2 as api

    yield api
    reader_flag.reload("")


def _legacy_name(api, fn):
    """On the mem-contain fold the legacy side of analyst links is the bounded SWR wrapper (``*_swr``)."""
    return fn + "_swr" if hasattr(api, fn + "_swr") else fn


def _call(api, path, query):
    h = api.ROUTES[path]
    return h(query) if query is not None else h()


def _trip(name):
    def _f(*a, **k):
        raise AssertionError(f"{name} must not be called")
    return _f


@pytest.mark.parametrize("path", sorted(LEGACY_FNS))
def test_flag_legacy_serves_exactly_the_legacy_path(api, monkeypatch, path):
    product, fn, query = LEGACY_FNS[path]
    fn = _legacy_name(api, fn)
    reader_flag.reload("")
    sentinel = {"legacy": fn}
    monkeypatch.setattr(api, fn, lambda *a, **k: sentinel)
    monkeypatch.setattr(api, "_product_io", _trip("_product_io (stored read under flag legacy)"))
    assert _call(api, path, query) is sentinel


@pytest.mark.parametrize("path", sorted(LEGACY_FNS))
def test_flag_flips_both_ways(api, monkeypatch, path):
    product, fn, query = LEGACY_FNS[path]
    fn = _legacy_name(api, fn)
    sentinel = {"legacy": fn}
    monkeypatch.setattr(api, fn, lambda *a, **k: sentinel)
    monkeypatch.setattr(api, "_db_query_raising", lambda *a, **k: [])  # missing product
    from scripts.lib.cc_products import cio_pages_route as cpr
    monkeypatch.setattr(cpr, "_HOT", [None])
    reader_flag.reload(f"{product}=stored")
    stored = _call(api, path, query)
    assert stored is not sentinel and (stored.get("_product") or {}).get("status") == "BUILDING"
    reader_flag.reload(f"{product}=legacy")  # rollback
    assert _call(api, path, query) is sentinel
    reader_flag.reload(f"{product}=stored")
    assert _call(api, path, query) is not sentinel


def test_inline_market_risk_get_follows_the_flag(api, monkeypatch):
    monkeypatch.setattr(api, "_market_risk_latest_projection", lambda: {"state": "evaluated", "tier": "LEGACY"})
    if hasattr(api, "_market_risk_latest_swr"):  # mem-contain fold: legacy = the bounded SWR path
        monkeypatch.setattr(api, "_market_risk_latest_swr", lambda: {"state": "evaluated", "tier": "LEGACY"})
    monkeypatch.setattr(api, "_db_query_raising", lambda *a, **k: [])
    reader_flag.reload("")
    assert api.handle("/api/v2/market-risk/latest", "GET", None, {})[1]["data"]["tier"] == "LEGACY"
    reader_flag.reload("market_risk.latest=stored")
    monkeypatch.setattr(api, "_market_risk_latest_projection", _trip("_market_risk_latest_projection"))
    if hasattr(api, "_market_risk_latest_swr"):
        monkeypatch.setattr(api, "_market_risk_latest_swr", _trip("_market_risk_latest_swr"))
    assert api.handle("/api/v2/market-risk/latest", "GET", None, {})[1]["data"]["tier"] == "UNKNOWN"


_SUBPROC = textwrap.dedent('''
    import json, sys
    sys.path[:0] = [ROOT, ROOT + "/scripts"]
    import scripts.api_v2 as api
    from scripts.lib.cc_products import cio_pages_route as cpr, reader_flag
    assert reader_flag.status()["error"] is None and set(reader_flag.status()["modes"].values()) == {"stored"}
    def trip(n):
        def f(*a, **k):
            raise SystemExit("LEGACY CALLED " + n)
        return f
    for n in ("_market_risk_latest_projection", "_home_cio_card", "_risk_payload_cached", "_reports_analyst_links",
              "_market_risk_latest_swr", "_reports_analyst_links_swr",
              "_home_since_close", "_home_incidents", "_home_priorities_live", "_home_status", "_home_gates",
              "_w7_cio_pages_legacy", "_cio_pages_build", "_shared_get_cached"):
        setattr(api, n, trip(n))
    # cio_pages_route imports w7_pages for its pure unavailable() gap shape (by design, LQ-2595); the page compute
    # functions in it are tripwired instead of import-checked.
    import scripts.lib.w7_pages as w7
    w7.page_payload = trip("w7_pages.page_payload")
    w7.project_pages = trip("w7_pages.project_pages")
    cpr._HOT[:] = [None]
    CASE = sys.argv[1]
    def row(pid):
        import datetime as d
        now = d.datetime.now(d.timezone.utc)
        age = 999999 if CASE == "expired" else 5
        body = json.dumps({"projection": {"state": "evaluated", "tier": "RED"}, "home_cio_card": {},
                           "slices": {}, "links": {}, "positions": []}).encode()
        return {"product_id": pid, "scope_key": "global", "body": body, "etag": "e", "seq": 1,
                "as_of": now - d.timedelta(seconds=age), "built_at": now, "next_refresh_at": None,
                "stale_after_s": 180, "hard_expiry_s": 300, "purge_after_s": 1, "status": "OK", "reason": None,
                "schema_version": 2 if CASE == "incompatible" else 1, "source_watermarks": {}}
    api._db_query_raising = lambda sql, params=None, fetch="all": [] if CASE == "missing" else [row(params[0])]
    before = set(sys.modules)
    for path, q in (("/api/v2/risk", None), ("/api/v2/home/since-close", None), ("/api/v2/home/gates", None),
                    ("/api/v2/home/cio-card", None), ("/api/v2/home/incidents", None),
                    ("/api/v2/home/priorities-live", None), ("/api/v2/home/status", None),
                    ("/api/v2/reports/analyst/links", {}), ("/api/v2/cio/pages", None)):
        h = api.ROUTES[path]
        out = h(q) if q is not None else h()
        assert isinstance(out, dict), path
    st, body = api.handle("/api/v2/market-risk/latest", "GET", None, {})
    assert st == 200, body
    new = sorted(m for m in set(sys.modules) - before
                 if any(k in m for k in ("builders", "product_builder", "w7_pages", "market_risk_projection",
                                         "home_cio_card", "cio_truth", "home_incidents", "home_priorities_live",
                                         "home_status_live", "reporting_engine")))
    print(json.dumps({"new_builder_modules": new}))
''')


@pytest.mark.parametrize("case", ["missing", "expired", "incompatible"])
def test_flag_stored_never_imports_or_calls_legacy_or_builders(case, tmp_path):
    env = {**os.environ, "TRADEAI_CC_PRODUCT_READERS": ",".join(f"{p}=stored" for p in reader_flag.PRODUCTS),
           "TMPDIR": os.environ.get("TMPDIR", str(tmp_path))}
    script = tmp_path / "probe.py"
    script.write_text(f"ROOT = {str(ROOT)!r}\n" + _SUBPROC)
    r = subprocess.run([sys.executable, str(script), case], cwd=str(tmp_path), env=env, capture_output=True,
                       text=True, timeout=300)
    assert r.returncode == 0, (r.stdout[-2000:], r.stderr[-3000:])
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["new_builder_modules"] == [], out


# ------------------------------------------------------------------------------- risk display (API side)


def _mr_fetch(age_s, tier="RED"):
    def f(pid, scope="global"):
        return mkrow(age_s, pid=pid, data={"projection": {"state": "evaluated", "tier": tier, "score": 83},
                                           "home_cio_card": {"schema": "HomeCioCard@v1", "state": "OK",
                                                             "market_risk": {"tier": tier}}})
    return f


def test_red_risk_fresh_is_red_and_not_stale():
    out = pr.serve_market_risk_latest(fetch_row=_mr_fetch(10), hot=None, now=NOW)
    assert out["tier"] == "RED" and out["state"] == "evaluated" and not out.get("stale")


@pytest.mark.parametrize("age_s,status,greyed", [(200, "STALE", False), (400, "UNKNOWN", True)])
def test_red_risk_going_stale_stays_red_and_is_marked_stale(age_s, status, greyed):
    out = pr.serve_market_risk_latest(fetch_row=_mr_fetch(age_s), hot=None, now=NOW)
    assert out["tier"] == "RED" and out["score"] == 83, "a stale RED must never be downgraded or cleared"
    assert out["stale"] is True and out["state"] == "stale"
    assert out["product_stale"]["status"] == status and out["product_stale"]["greyed"] is greyed
    card = pr.serve_home_cio_card(fetch_row=_mr_fetch(age_s), hot=None, now=NOW)
    assert card["market_risk"]["tier"] == "RED" and card["stale"] is True


@pytest.mark.parametrize("fetch", [lambda p, s="global": None, "down", "incompatible"])
def test_missing_risk_is_unknown(fetch):
    if fetch == "down":
        def fetch(p, s="global"):
            raise RuntimeError("synthetic store down")
    elif fetch == "incompatible":
        def fetch(p, s="global"):
            return {**_mr_fetch(10)(p), "schema_version": 9}
    out = pr.serve_market_risk_latest(fetch_row=fetch, hot=None, now=NOW)
    assert out["tier"] == "UNKNOWN" and out["state"] == "not_evaluated" and out["unknown"] is True
    assert out["score"] is None


# ---------------------------------------------------------------- CLI exit codes (health contract alignment)
@pytest.mark.parametrize("outcome,rc", [("OK", 0), ("UNCHANGED", 0), ("SKIPPED_BUSY", 0), ("REFUSED_OLDER", 0),
                                        ("TIMEOUT", 1), ("FAILED", 1), ("REFUSED", 1)])
def test_cli_exit_code_matches_contract(outcome, rc, monkeypatch, capsys):
    """Healthy outcomes and the DEGRADED REFUSED_OLDER exit 0; only run_failed outcomes exit non-zero."""
    import types
    from scripts.lib.cc_products import product_builder as pb
    monkeypatch.setattr(pb, "run_once", lambda *a, **k: {"outcome": outcome})
    args = types.SimpleNamespace(product="home", timeout=None, rlimit_mb=None, dry_run=True, builder_sha=None)
    assert pb.run_cli(args) == rc


# ------------------------------------------------------------------------------------- mutant killers (SC2, SW1)


def test_run_once_locks_and_reports_its_own_scope(tmp_path):
    """A scoped build takes the lock for ITS scope (a held global lock does not block acct:B) and its receipt names
    that scope; writing every scope as global would serialize accounts and mislabel receipts (mutant SC2)."""
    with pb.HostLocks(tmp_path, slots=4).acquire("syn.product", "global") as busy:
        assert busy is None
        r = pb.run_once(spec(scope_key="acct:B"), connect=None, dry_run=True, locks=pb.HostLocks(tmp_path, slots=4),
                        build_fn=fake_build(T0), ctx_factory=_ctx)
    assert r["outcome"] != "SKIPPED_BUSY", r
    assert r["scope_key"] == "acct:B"


def test_slot_wait_default_is_bounded_twenty_seconds(tmp_path):
    """The bounded slot wait (cron-collision fix) defaults to 20 s; 0 would turn every same-minute collision back
    into SKIPPED_BUSY (mutant SW1). The catalogue runner timeouts budget tmo + 20 + 10."""
    if "TRADEAI_CC_BUILDER_SLOT_WAIT_S" in os.environ:
        pytest.skip("slot wait overridden in this environment")
    assert pb.SLOT_WAIT_S == 20.0
    assert pb.HostLocks(tmp_path).slot_wait_s == 20.0

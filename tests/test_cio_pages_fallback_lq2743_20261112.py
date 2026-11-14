"""LQ-20261113-3095 (supersedes the LQ-20261107-2743 compute fallback): GET /api/v2/cio/pages NEVER computes.

Under EITHER value of the cio.pages reader flag the route serves the stored ``cio.pages`` product only: OK/STALE as
stored, past hard expiry the greyed last good (UNKNOWN), no row / store down the UNKNOWN gap shape. The in-server
compute (``_cio_pages_build``, the SWR thread, ``w7_pages.page_payload``) is removed; any call to it fails the test.
Real ``api_v2._w7_cio_pages`` -> ``cio_pages_route.serve_cio_pages`` -> ``read_path`` chain over a fake RAISING query,
hot tier off. No DB, no Valkey, no server, no network.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PANELS = ("portfolio", "positions", "stops", "regime", "approvals", "cio_status", "capital", "do_now",
          "companies", "sectors")
BUILDING_GAP = "The CIO page record is being built; no stored copy yet"


def computed_page() -> dict:
    return {name: {"source": "CIO", "as_of": "2026-11-12T21:30:00+00:00", "computed": True, "value": i}
            for i, name in enumerate(PANELS)}


def stored_page() -> dict:
    return {name: {"source": "CIO", "as_of": "2026-11-12T21:30:00+00:00", "stored": True, "value": i}
            for i, name in enumerate(PANELS)}


def row(*, age_s: float) -> dict:
    now = datetime.now(timezone.utc)
    as_of = now - timedelta(seconds=age_s)
    body = json.dumps(stored_page()).encode()
    return {"product_id": "cio.pages", "scope_key": "global", "body": memoryview(body), "etag": "sha256:t",
            "seq": 7, "as_of": as_of, "built_at": as_of, "next_refresh_at": None, "stale_after_s": 360,
            "hard_expiry_s": 1800, "purge_after_s": 604800, "status": "OK", "source_watermarks": {},
            "builder_sha": "t", "bytes": len(body), "build_ms": 5}


@pytest.fixture
def env(monkeypatch):
    import scripts.api_v2 as api
    from scripts.lib import shared_get_swr as swr
    from scripts.lib import w7_pages
    from scripts.lib.cc_products import cio_pages_route as cpr

    state = {"rows": [], "raise": None, "builds": 0, "build": computed_page, "sql": []}

    def fake_raising(sql, params=None, fetch="all"):
        state["sql"].append(sql)
        if state["raise"] is not None:
            raise state["raise"]
        return state["rows"]

    def fake_build(root, *, db_query=None, ledger_root=None, **kw):
        state["builds"] += 1
        raise AssertionError("a GET must never compute the CIO page (w7_pages.page_payload was called)")

    swr.clear()
    monkeypatch.setattr(api, "_db_query_raising", fake_raising)
    monkeypatch.setattr(cpr, "_HOT", [None])
    monkeypatch.setattr(w7_pages, "page_payload", fake_build)
    state["api"], state["swr"] = api, swr
    yield state
    wait_builds(swr)
    swr.clear()


def wait_builds(swr, timeout=10.0):
    deadline = time.monotonic() + timeout
    while swr.inflight() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not swr.inflight(), "the background build did not finish"


def call(env):
    out = env["api"]._w7_cio_pages()
    assert isinstance(out, dict) and "data" not in out  # the front end's unwrap() keys on a top-level "data"
    assert set(PANELS) <= set(out), sorted(out)
    return out


@pytest.fixture(params=["legacy", "stored"])
def flag(request, monkeypatch, env):
    from scripts.lib.cc_products import reader_flag
    monkeypatch.setattr(reader_flag, "mode", lambda product_id: request.param)
    return request.param


def test_the_compute_path_is_gone_from_api_v2():
    import scripts.api_v2 as api
    for name in ("_cio_pages_build", "_CIO_PAGES_COMPUTED_TTL_S", "_CIO_PAGES_FRESH"):
        assert not hasattr(api, name), name


@pytest.mark.parametrize("age_s,status", [(30, "OK"), (600, "STALE")])
def test_fresh_stored_row_is_served_as_stored_and_nothing_is_computed(env, flag, age_s, status):
    env["rows"] = [row(age_s=age_s)]
    out = call(env)
    assert out["portfolio"]["stored"] is True and "computed" not in out["portfolio"]
    assert out["_product"]["status"] == status and out["_product"]["served_from"] == "pg"
    assert env["builds"] == 0 and not env["swr"].inflight()
    assert all("statement_timeout = '250ms'" in s for s in env["sql"])


def test_empty_store_is_the_building_gap_and_never_computes(env, flag):
    out = call(env)
    assert out["portfolio"].get("gap") == BUILDING_GAP and out["_product"]["status"] == "BUILDING"
    assert env["builds"] == 0 and not env["swr"].inflight()


def test_store_unreadable_is_unknown_and_never_computes(env, flag):
    env["raise"] = RuntimeError("canceling statement due to statement timeout")
    out = call(env)
    assert out["_product"]["status"] == "UNKNOWN" and out["_product"].get("served_from") != "computed"
    assert env["builds"] == 0 and not env["swr"].inflight()


def test_past_hard_expiry_serves_greyed_last_good_and_never_computes(env, flag):
    env["rows"] = [row(age_s=4000)]  # past hard_expiry_s 1800
    out = call(env)
    assert out["portfolio"]["stored"] is True
    assert out["_product"]["status"] == "UNKNOWN" and out["_product"]["greyed"] is True
    assert env["builds"] == 0 and not env["swr"].inflight()


def test_repeated_polls_never_start_a_build(env, flag):
    for _ in range(5):
        call(env)
    assert env["builds"] == 0 and not env["swr"].inflight()


def test_the_route_table_points_at_the_flagged_reader(env):
    assert env["api"].ROUTES["/api/v2/cio/pages"] is env["api"]._w7_cio_pages


def test_both_flag_values_return_the_same_body(env, monkeypatch):
    from scripts.lib.cc_products import reader_flag
    env["rows"] = [row(age_s=30)]
    outs = []
    for v in ("legacy", "stored"):
        monkeypatch.setattr(reader_flag, "mode", lambda product_id, v=v: v)
        outs.append(call(env))
    assert outs[0] == outs[1]

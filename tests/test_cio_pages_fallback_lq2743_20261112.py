"""LQ-20261107-2743 (P0): GET /api/v2/cio/pages is stored-first, computed on a miss, never a blank page.

Release 2 (d014c75d5) was rolled back 2026-11-12 21:39 ET: ``_w7_cio_pages`` served only the stored ``cio.pages``
product, nothing schedules its builder, ``cc_product_current`` had 0 rows, so every section read "The CIO page record
is being built; no stored copy yet" (lead/scratch/release2-20261112/after0-cio-pages-BUILDING.json).

These tests drive the real ``api_v2._w7_cio_pages`` -> ``cio_pages_route.serve_cio_pages`` -> ``read_path`` chain
over a fake RAISING query (the production ``fetch_row`` is built from ``api_v2._db_query_raising``), with the hot tier
off and ``w7_pages.page_payload`` replaced by a synthetic builder. No DB, no Valkey, no server, no network.
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
        return state["build"]()

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


def computed_now(env):
    """First poll starts the one background build; once it lands, the next poll is the computed page."""
    call(env)
    wait_builds(env["swr"])
    return call(env)


def test_empty_store_serves_the_computed_page_with_real_sections(env):
    first = call(env)
    # The first poll never waits on the build: it is the stored BUILDING response with the compute state named.
    assert first["portfolio"].get("gap") == BUILDING_GAP
    assert first["_product"]["status"] == "BUILDING"
    assert first["_product"]["computed"]["reason"] == "building"
    wait_builds(env["swr"])
    out = call(env)
    assert env["builds"] == 1
    for i, name in enumerate(PANELS):
        assert out[name] == {"source": "CIO", "as_of": "2026-11-12T21:30:00+00:00", "computed": True, "value": i}
        assert "gap" not in out[name]
    p = out["_product"]
    assert (p["status"], p["served_from"], p["stored_status"], p["greyed"]) == ("OK", "computed", "BUILDING", False)
    assert p["as_of"] and p["age_s"] is not None and p["age_s"] >= 0
    assert "not built yet" in p["reason"]


@pytest.mark.parametrize("age_s,status", [(30, "OK"), (600, "STALE")])
def test_fresh_stored_row_is_served_as_stored_and_nothing_is_computed(env, age_s, status):
    env["rows"] = [row(age_s=age_s)]
    out = call(env)
    assert out["portfolio"]["stored"] is True and "computed" not in out["portfolio"]
    assert out["_product"]["status"] == status and out["_product"]["served_from"] == "pg"
    assert "computed" not in out["_product"]
    assert env["builds"] == 0 and not env["swr"].inflight()
    assert all("statement_timeout = '250ms'" in s for s in env["sql"])


def test_store_unreadable_falls_back_to_the_computed_page(env):
    env["raise"] = RuntimeError("canceling statement due to statement timeout")
    out = computed_now(env)
    assert out["portfolio"]["computed"] is True
    assert out["_product"]["served_from"] == "computed" and out["_product"]["stored_status"] == "UNKNOWN"


def test_past_hard_expiry_serves_greyed_last_good_until_the_compute_lands(env):
    env["rows"] = [row(age_s=4000)]  # past hard_expiry_s 1800
    first = call(env)
    assert first["portfolio"]["stored"] is True
    assert first["_product"]["status"] == "UNKNOWN" and first["_product"]["greyed"] is True
    assert first["_product"]["computed"]["reason"] == "building"
    wait_builds(env["swr"])
    out = call(env)
    assert out["portfolio"]["computed"] is True and out["_product"]["stored_status"] == "UNKNOWN"


def test_a_failing_build_keeps_the_stored_response_and_names_the_failure(env):
    def boom():
        raise RuntimeError("cio truth unreadable")

    env["build"] = boom
    call(env)
    wait_builds(env["swr"])
    out = call(env)
    assert out["portfolio"].get("gap") == BUILDING_GAP and out["_product"]["status"] == "BUILDING"
    c = out["_product"]["computed"]
    assert c["reason"] == "build_failed" and "cio truth unreadable" in c["last_build_error"]


def test_the_computed_page_is_reused_within_its_ttl_and_requests_never_wait(env):
    gate = threading.Event()

    def slow():
        gate.wait(10)
        return computed_page()

    env["build"] = slow
    t0 = time.monotonic()
    for _ in range(20):
        assert call(env)["_product"]["status"] == "BUILDING"
    assert time.monotonic() - t0 < 2.0, "a request waited on the build"
    gate.set()
    wait_builds(env["swr"])
    for _ in range(5):
        assert call(env)["_product"]["served_from"] == "computed"
    assert env["builds"] == 1


def test_a_computed_page_past_its_ttl_reads_stale_with_its_age(env, monkeypatch):
    monkeypatch.setattr(env["api"], "_CIO_PAGES_COMPUTED_TTL_S", 0.0)
    out = computed_now(env)
    p = out["_product"]
    assert p["served_from"] == "computed" and p["status"] == "STALE" and p["computed"]["stale"] is True
    assert p["age_s"] is not None and p["age_s"] >= 0


def test_the_route_table_still_points_at_the_fallback(env):
    assert env["api"].ROUTES["/api/v2/cio/pages"] is env["api"]._w7_cio_pages

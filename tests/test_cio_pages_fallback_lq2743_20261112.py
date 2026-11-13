"""LQ-20261107-2743 (P0): GET /api/v2/cio/pages is stored-ONLY; part 1 (the in-server compute fallback) is REMOVED.

Operator 13 Nov 2026 (DECISION-20261113-CORRECTIONS-1507): a GET never triggers heavy compute - not on cold start, a
missing product, an expired product or a Valkey outage. The fallback these tests used to pin (``_cio_pages_build`` on
the SWR thread) is gone; each case now serves the stored/last-good product with its age, or UNKNOWN/BUILDING, and
``w7_pages.page_payload`` is patched to RAISE so any compute in the web process fails the test.

History:
Release 2 (d014c75d5) was rolled back 2026-11-12 21:39 ET: ``_w7_cio_pages`` served only the stored ``cio.pages``
product, nothing schedules its builder, ``cc_product_current`` had 0 rows, so every section read "The CIO page record
is being built; no stored copy yet" (lead/scratch/release2-20261112/after0-cio-pages-BUILDING.json).

These tests drive the real ``api_v2._w7_cio_pages`` -> ``cio_pages_route.serve_cio_pages`` -> ``read_path`` chain
over a fake RAISING query (the production ``fetch_row`` is built from ``api_v2._db_query_raising``), with the hot tier
off and ``w7_pages.page_payload`` replaced by a tripwire. No DB, no Valkey, no server, no network.
"""
from __future__ import annotations

import json
import sys
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
    from scripts.lib import w7_pages
    from scripts.lib.cc_products import cio_pages_route as cpr

    state = {"rows": [], "raise": None, "sql": []}

    def fake_raising(sql, params=None, fetch="all"):
        state["sql"].append(sql)
        if state["raise"] is not None:
            raise state["raise"]
        return state["rows"]

    def tripwire(*a, **k):
        raise AssertionError("w7_pages.page_payload called inside the web process")

    monkeypatch.setattr(api, "_db_query_raising", fake_raising)
    monkeypatch.setattr(cpr, "_HOT", [None])
    monkeypatch.setattr(w7_pages, "page_payload", tripwire)
    state["api"] = api
    yield state


def call(env):
    out = env["api"]._w7_cio_pages()
    assert isinstance(out, dict) and "data" not in out  # the front end's unwrap() keys on a top-level "data"
    assert set(PANELS) <= set(out), sorted(out)
    assert "computed" not in (out.get("_product") or {}), "a compute state on the response means compute ran"
    return out


def test_empty_store_serves_building_and_never_computes(env):
    t0 = time.monotonic()
    out = call(env)
    assert time.monotonic() - t0 < 2.0
    assert out["portfolio"].get("gap") == BUILDING_GAP
    assert out["_product"]["status"] == "BUILDING"


@pytest.mark.parametrize("age_s,status", [(30, "OK"), (600, "STALE")])
def test_fresh_stored_row_is_served_as_stored_and_nothing_is_computed(env, age_s, status):
    env["rows"] = [row(age_s=age_s)]
    out = call(env)
    assert out["portfolio"]["stored"] is True
    assert out["_product"]["status"] == status and out["_product"]["served_from"] == "pg"
    assert all("statement_timeout = '250ms'" in s for s in env["sql"])


def test_store_unreadable_is_unknown_and_never_computes(env):
    env["raise"] = RuntimeError("canceling statement due to statement timeout")
    out = call(env)
    assert out["_product"]["status"] == "UNKNOWN"


def test_past_hard_expiry_serves_greyed_last_good_and_never_computes(env):
    env["rows"] = [row(age_s=4000)]  # past hard_expiry_s 1800
    for _ in range(3):
        out = call(env)
        assert out["portfolio"]["stored"] is True
        assert out["_product"]["status"] == "UNKNOWN" and out["_product"]["greyed"] is True


def test_the_fallback_code_is_gone():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "def _cio_pages_build" not in src and "_CIO_PAGES_COMPUTED_TTL_S" not in src
    assert "_CIO_PAGES_FRESH" not in src


def test_the_route_table_points_at_the_stored_read(env):
    assert env["api"].ROUTES["/api/v2/cio/pages"] is env["api"]._w7_cio_pages

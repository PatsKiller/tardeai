"""LQ-20261107-2600 (REVIEW-2606 F2): /api/v2/cio/pages surfaces the oldest section's age.

``cio.pages`` stamps its product ``as_of`` when the build read its sources (READY-2595 deviation 1), so a page whose
one section is a week old reads OK on the product clock. The builder records that section's clock in
``source_watermarks._product.oldest_section_as_of``; the read path now carries it and the route serves
``_product.oldest_section_as_of`` / ``oldest_section_age_s`` / ``oldest_section`` beside the status, so a week-old
section is never silently called fresh. Unknown stays unknown (None), never an age of 0.

Hermetic: in-memory rows and a fake hot tier; no DB, no Valkey.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cc_products import cio_pages, cio_pages_route as route, read_path
from scripts.lib.cc_products.hot_tier import pack

NOW = datetime(2026, 11, 12, 15, 0, 0, tzinfo=timezone.utc)
WEEK_OLD = NOW - timedelta(days=7, hours=3)


def _payload() -> dict:
    return {
        "portfolio": {"as_of": (NOW - timedelta(minutes=2)).isoformat(), "value": 1},
        "concentration_policy": {"as_of": WEEK_OLD.isoformat(), "value": 2},
        "conflicts": {"as_of": None, "gap": {"reason": "not yet"}},
    }


def _row(*, age_s: float = 30, marks=None) -> dict:
    body = json.dumps(_payload()).encode()
    as_of = NOW - timedelta(seconds=age_s)
    if marks is None:
        _, marks = cio_pages.product_clock(_payload(), as_of)  # the builder's own watermarks
    return {"product_id": "cio.pages", "scope_key": "global", "body": body, "etag": "sha256:t", "seq": 3,
            "as_of": as_of, "built_at": as_of, "next_refresh_at": None, "stale_after_s": 360, "hard_expiry_s": 1800,
            "purge_after_s": 604800, "status": "OK", "source_watermarks": marks, "builder_sha": "t",
            "bytes": len(body), "build_ms": 5}


def _fetch(row):
    return lambda pid, scope="global": row


WEEK_S = int((NOW - WEEK_OLD).total_seconds())


def test_ok_page_with_a_week_old_section_serves_that_sections_age():
    out = route.serve_cio_pages(fetch_row=_fetch(_row()), now=NOW)
    meta = out["_product"]
    assert meta["status"] == "OK"  # the product clock is fresh ...
    assert meta["oldest_section_age_s"] == WEEK_S  # ... and the week-old section is not hidden behind it
    assert meta["oldest_section_as_of"] == WEEK_OLD.isoformat()
    assert meta["oldest_section"] == "concentration_policy"


def test_the_age_is_taken_at_serve_time_not_build_time():
    later = NOW + timedelta(seconds=90)
    out = route.serve_cio_pages(fetch_row=_fetch(_row(age_s=0)), now=later)
    assert out["_product"]["oldest_section_age_s"] == WEEK_S + 90


def test_unknown_last_good_greyed_also_carries_the_oldest_section():
    out = route.serve_cio_pages(fetch_row=_fetch(_row(age_s=4000)), now=NOW)
    meta = out["_product"]
    assert meta["status"] == "UNKNOWN" and meta["greyed"] is True
    assert meta["oldest_section_age_s"] == WEEK_S and meta["oldest_section"] == "concentration_policy"


class FakeHot:
    def __init__(self, raw):
        self.raw = raw

    def get(self, key):
        return self.raw

    def set(self, key, value, ex_s):  # pragma: no cover - a hot hit never writes back
        raise AssertionError("unexpected set")


def test_a_hot_tier_hit_carries_the_watermarks_too():
    out = route.serve_cio_pages(fetch_row=_fetch(None), hot=FakeHot(pack(_row())), now=NOW)
    meta = out["_product"]
    assert meta["served_from"] == "hot" and meta["status"] == "OK"
    assert meta["oldest_section_age_s"] == WEEK_S


def test_watermarks_stored_as_json_text_are_read():
    row = _row()
    row["source_watermarks"] = json.dumps(row["source_watermarks"])
    assert route.serve_cio_pages(fetch_row=_fetch(row), now=NOW)["_product"]["oldest_section_age_s"] == WEEK_S


@pytest.mark.parametrize("marks", [
    {},  # no _product entry
    {"_product": {"as_of_rule": "sources_read_at", "oldest_section_as_of": None}},  # no section had a clock
    {"_product": {"oldest_section_as_of": "not a time"}},
    {"_product": "garbage"},
    "{not json",
    ["list"],
])
def test_missing_or_unreadable_watermarks_are_unknown_never_zero(marks):
    meta = route.serve_cio_pages(fetch_row=_fetch(_row(marks=marks)), now=NOW)["_product"]
    assert meta["status"] == "OK"
    assert meta["oldest_section_age_s"] is None and meta["oldest_section_as_of"] is None
    assert meta["oldest_section"] is None


def test_building_and_store_down_have_no_section_age():
    assert route.serve_cio_pages(fetch_row=_fetch(None), now=NOW)["_product"]["oldest_section_age_s"] is None

    def down(pid, scope="global"):
        raise route.StoreUnavailable("no database connection")

    assert route.serve_cio_pages(fetch_row=down, now=NOW)["_product"]["oldest_section_age_s"] is None


def test_a_future_section_clock_is_clamped_to_zero_age():
    marks = {"_product": {"oldest_section_as_of": (NOW + timedelta(minutes=5)).isoformat()}}
    assert route.serve_cio_pages(fetch_row=_fetch(_row(marks=marks)), now=NOW)["_product"]["oldest_section_age_s"] == 0


def test_read_path_envelope_carries_the_stored_watermarks():
    row = _row()
    env = read_path.read_product("cio.pages", fetch_row=_fetch(row), now=NOW)
    assert env["status"] == "OK" and env["source_watermarks"] == row["source_watermarks"]
    assert read_path.read_product("cio.pages", fetch_row=_fetch(None), now=NOW)["source_watermarks"] is None


def test_a_naive_section_clock_is_read_as_utc():
    naive = (NOW - timedelta(days=2)).replace(tzinfo=None).isoformat()
    meta = route.serve_cio_pages(fetch_row=_fetch(_row(marks={"_product": {"oldest_section_as_of": naive}})),
                                 now=NOW)["_product"]
    assert meta["oldest_section_age_s"] == 2 * 86400
    assert meta["oldest_section_as_of"] == (NOW - timedelta(days=2)).isoformat()

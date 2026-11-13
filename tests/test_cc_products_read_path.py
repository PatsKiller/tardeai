"""read_path: hot tier → PG stored copy → envelope (LQ-20261107-2595, DSN §6.1). No real Valkey, no real DB."""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cc_products import read_path
from scripts.lib.cc_products.hot_tier import HotTier, HotTierDown, pack, product_key, unpack
from scripts.lib.cc_products.read_path import READ_COUNTERS, read_product

NOW = datetime(2026, 11, 12, 15, 0, 0, tzinfo=timezone.utc)
STALE, HARD = 360, 1800

ENVELOPE_KEYS = {
    "product", "scope", "status", "as_of", "built_at", "next_refresh_at", "stale_after_s", "hard_expiry_s",
    "age_s", "seq", "etag", "reason", "data", "last_good", "served_from",
    "source_watermarks",  # LQ-2600 (REVIEW-2606 F2): the stored per-section clocks travel with the envelope
    "build_status", "build_failure", "schema_version",  # home-products 13 Nov 2026: row status + last-build failure
}


def make_row(age_s: float, *, built_age_s: float | None = None, as_of_null=False, data=None):
    data = {"pages": [1, 2, 3]} if data is None else data
    as_of = NOW - timedelta(seconds=age_s)
    built_at = NOW - timedelta(seconds=age_s if built_age_s is None else built_age_s)
    return {
        "product_id": "cio.pages",
        "scope_key": "global",
        "body": json.dumps(data).encode(),
        "etag": "sha256:e1",
        "seq": 5,
        "as_of": None if as_of_null else as_of,
        "built_at": built_at,
        "next_refresh_at": NOW + timedelta(seconds=60),
        "stale_after_s": STALE,
        "hard_expiry_s": HARD,
        "purge_after_s": 604800,
        "status": "OK",
        "source_watermarks": {},
        "builder_sha": "abc",
        "bytes": 10,
        "build_ms": 3,
    }


class FakeHot:
    def __init__(self, store=None, down=False):
        self.store = dict(store or {})
        self.down = down
        self.sets: list[tuple[str, bytes, int]] = []

    def get(self, key):
        if self.down:
            raise HotTierDown("down")
        return self.store.get(key)

    def set(self, key, value, ex_s):
        if self.down:
            raise HotTierDown("down")
        self.sets.append((key, value, ex_s))
        self.store[key] = value


class PG:
    def __init__(self, row=None, exc=None, delay_s=0.0):
        self.row, self.exc, self.delay_s, self.calls = row, exc, delay_s, 0

    def __call__(self, product_id, scope_key):
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.exc:
            raise self.exc
        return self.row


def closed_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


KEY = product_key("cio.pages", "global")


def test_fresh_from_hot():
    hot = FakeHot({KEY: pack(make_row(10))})
    pg = PG(exc=AssertionError("PG must not be read on a hot hit"))
    env = read_product("cio.pages", fetch_row=pg, hot=hot, now=NOW)
    assert set(env) == ENVELOPE_KEYS
    assert env["status"] == "OK" and env["served_from"] == "hot"
    assert env["data"] == {"pages": [1, 2, 3]}
    assert env["age_s"] == 10 and env["seq"] == 5 and env["etag"] == "sha256:e1"
    assert env["reason"] is None and env["last_good"] is None
    assert pg.calls == 0 and hot.sets == []


def test_hot_miss_pg_hit_sets_hot_with_remaining_ttl():
    hot = FakeHot()
    row = make_row(100)
    env = read_product("cio.pages", fetch_row=PG(row), hot=hot, now=NOW)
    assert env["status"] == "OK" and env["served_from"] == "pg"
    assert env["data"] == {"pages": [1, 2, 3]}
    assert len(hot.sets) == 1
    key, value, ex = hot.sets[0]
    assert key == KEY and ex == HARD - 100
    assert unpack(value) == row


def test_hot_down_closed_port_falls_back_to_pg():
    """Operator requirement: fall back to the PG stored copy when Valkey is down, tested with an unreachable port."""
    hot = HotTier(port=closed_port(), timeout_s=0.2)
    before = READ_COUNTERS["hot_down"]
    t0 = time.monotonic()
    env = read_product("cio.pages", fetch_row=PG(make_row(30)), hot=hot, now=NOW)
    assert time.monotonic() - t0 < 1.0
    assert env["status"] == "OK" and env["served_from"] == "pg"
    assert env["data"] == {"pages": [1, 2, 3]}
    assert READ_COUNTERS["hot_down"] == before + 1


def test_no_hot_configured_reads_pg():
    env = read_product("cio.pages", fetch_row=PG(make_row(5)), hot=None, now=NOW)
    assert env["status"] == "OK" and env["served_from"] == "pg"


def test_stale_has_data():
    env = read_product("cio.pages", fetch_row=PG(make_row(STALE + 1)), now=NOW)
    assert env["status"] == "STALE" and env["data"] == {"pages": [1, 2, 3]}
    assert env["reason"]


def test_boundaries_are_strictly_greater_than():
    assert read_product("cio.pages", fetch_row=PG(make_row(STALE)), now=NOW)["status"] == "OK"
    assert read_product("cio.pages", fetch_row=PG(make_row(HARD)), now=NOW)["status"] == "STALE"
    assert read_product("cio.pages", fetch_row=PG(make_row(HARD + 1)), now=NOW)["status"] == "UNKNOWN"


def test_past_hard_expiry_is_unknown_with_last_good():
    row = make_row(HARD + 60)
    env = read_product("cio.pages", fetch_row=PG(row), hot=FakeHot(), now=NOW)
    assert env["status"] == "UNKNOWN"
    assert env["data"] is None
    assert env["last_good"] == {"pages": [1, 2, 3]}
    assert env["reason"] == f"past hard expiry; last good {row['built_at'].isoformat()}"
    assert env["served_from"] == "pg"


def test_no_row_is_building():
    env = read_product("cio.pages", fetch_row=PG(None), hot=FakeHot(), now=NOW)
    assert set(env) == ENVELOPE_KEYS
    assert env["status"] == "BUILDING" and env["data"] is None and env["served_from"] is None


def test_fetch_row_raises_is_store_unavailable():
    env = read_product("cio.pages", fetch_row=PG(exc=RuntimeError("pg down")), hot=FakeHot(), now=NOW)
    assert set(env) == ENVELOPE_KEYS
    assert env["status"] == "UNKNOWN" and env["reason"] == "product store unavailable"
    assert env["data"] is None and env["last_good"] is None


def test_slow_fetch_beyond_budget_is_unknown():
    hot = FakeHot()
    env = read_product("cio.pages", fetch_row=PG(make_row(5), delay_s=0.15), hot=hot, now=NOW, budget_ms=50)
    assert env["status"] == "UNKNOWN" and env["reason"] == "product store unavailable"
    assert env["data"] is None
    # the same slow fetch inside a generous budget answers OK, so the budget is what flipped it
    assert read_product("cio.pages", fetch_row=PG(make_row(5), delay_s=0.15), now=NOW,
                        budget_ms=2000)["status"] == "OK"


def test_age_is_measured_from_as_of_not_built_at():
    # data true 1 h ago, rebuilt (unchanged) 5 s ago: the age is the hour, so UNKNOWN
    row = make_row(3600, built_age_s=5)
    env = read_product("cio.pages", fetch_row=PG(row), now=NOW)
    assert env["age_s"] == 3600 and env["status"] == "UNKNOWN"
    # and the reverse: as_of fresh, built_at old → OK
    row = make_row(5, built_age_s=3600)
    env = read_product("cio.pages", fetch_row=PG(row), now=NOW)
    assert env["age_s"] == 5 and env["status"] == "OK"


def test_age_falls_back_to_built_at_when_as_of_null():
    env = read_product("cio.pages", fetch_row=PG(make_row(0, built_age_s=STALE + 10, as_of_null=True)), now=NOW)
    assert env["age_s"] == STALE + 10 and env["status"] == "STALE" and env["as_of"] is None


def test_never_sets_hot_when_remaining_ttl_not_positive():
    hot = FakeHot()
    read_product("cio.pages", fetch_row=PG(make_row(HARD)), hot=hot, now=NOW)  # remaining exactly 0
    read_product("cio.pages", fetch_row=PG(make_row(HARD + 500)), hot=hot, now=NOW)
    read_product("cio.pages", fetch_row=PG(make_row(HARD - 0.5)), hot=hot, now=NOW)  # floor(0.5) = 0
    assert hot.sets == []
    read_product("cio.pages", fetch_row=PG(make_row(HARD - 1)), hot=hot, now=NOW)
    assert [s[2] for s in hot.sets] == [1]


def test_hot_set_failure_still_answers():
    class SetDown(FakeHot):
        def set(self, key, value, ex_s):
            raise HotTierDown("down on set")

    env = read_product("cio.pages", fetch_row=PG(make_row(5)), hot=SetDown(), now=NOW)
    assert env["status"] == "OK" and env["served_from"] == "pg"


def test_corrupt_hot_entry_is_a_miss():
    hot = FakeHot({KEY: b"\x00\x00\x00\x09not json!garbage"})
    env = read_product("cio.pages", fetch_row=PG(make_row(5)), hot=hot, now=NOW)
    assert env["status"] == "OK" and env["served_from"] == "pg"


def test_counters_count_outcomes():
    before = dict(READ_COUNTERS)
    read_product("cio.pages", fetch_row=PG(None), now=NOW)
    read_product("cio.pages", fetch_row=PG(exc=OSError("x")), now=NOW)
    assert READ_COUNTERS["BUILDING"] == before["BUILDING"] + 1
    assert READ_COUNTERS["store_unavailable"] == before["store_unavailable"] + 1
    assert READ_COUNTERS["UNKNOWN"] == before["UNKNOWN"] + 1


def test_read_path_imports_no_builder():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(read_path))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    assert not any("w7_pages" in m or "cio_pages" in m or "cio_truth" in m or "hermes" in m for m in mods), mods

"""LQ-20261107-2595 phase 2: the cio.pages background builder (scripts/lib/cc_products/cio_pages.py).

Hermetic: the store, the connection and the hot tier are in-memory fakes; builds are injected (``build_fn``) and
run in a real forked child, so the timeout, rlimit and reaping paths are exercised for real. No DB, no Valkey.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone

import pytest

from scripts.lib.cc_products import cio_pages

NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------------------------- fakes


class BodyTooLarge(ValueError):
    pass


class FakeStore:
    """The store_pg API over one in-memory row and a recorded build log. Every write lands in ``events``."""

    def __init__(self, events, *, lock_free=True, row=None):
        self.events = events
        self.lock_free = lock_free
        self.row = dict(row) if row else None
        self.log = []
        self.BodyTooLarge = BodyTooLarge

    def try_lock(self, cur, product_id, scope_key="global"):
        self.events.append("try_lock")
        return self.lock_free

    def read_current(self, cur, product_id, scope_key="global"):
        return dict(self.row) if self.row else None

    def write_current(self, cur, product_id, scope_key, body, *, as_of, built_at, next_refresh_at, stale_after_s,
                      hard_expiry_s, purge_after_s, source_watermarks, builder_sha, build_ms, status="OK"):
        self.events.append("write")
        if len(body) > 2 * 1024 * 1024:
            raise BodyTooLarge("too big")
        etag = "sha256:" + hashlib.sha256(body).hexdigest()
        if self.row and self.row["etag"] == etag:
            self.row.update(built_at=built_at, next_refresh_at=next_refresh_at)
            return {"changed": False, "seq": self.row["seq"], "etag": etag}
        seq = (self.row["seq"] + 1) if self.row else 1
        self.row = {"product_id": product_id, "scope_key": scope_key, "body": body, "etag": etag, "seq": seq,
                    "as_of": as_of, "built_at": built_at, "next_refresh_at": next_refresh_at,
                    "stale_after_s": stale_after_s, "hard_expiry_s": hard_expiry_s, "purge_after_s": purge_after_s,
                    "status": status, "source_watermarks": source_watermarks, "builder_sha": builder_sha,
                    "bytes": len(body), "build_ms": build_ms}
        return {"changed": True, "seq": seq, "etag": etag}

    def log_build(self, cur, product_id, scope_key, outcome, *, started_at, finished_at, build_ms, lane=None,
                  peak_rss_kb=None, bytes_=None, error=None):
        self.events.append("log:" + outcome)
        self.log.append({"outcome": outcome, "build_ms": build_ms, "peak_rss_kb": peak_rss_kb, "bytes": bytes_,
                         "error": error})


class FakeConn:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def cursor(self):
        return object()

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.closed = True


class FakeHot:
    def __init__(self, events):
        self.events = events
        self.sets = []

    def set(self, key, value, ex_s):
        self.events.append("hot_set")
        self.sets.append((key, value, ex_s))


class FakeCodec:
    @staticmethod
    def product_key(product_id, scope_key="global"):
        return f"cc:product:{product_id}:{scope_key}"

    @staticmethod
    def pack(row):
        return json.dumps({k: (v.hex() if isinstance(v, bytes) else v) for k, v in row.items()}, default=str).encode()


def _payload(stamp="2026-11-12T17:55:00+00:00"):
    return {"portfolio": {"as_of": stamp, "total_usd": 1.0},
            "regime": {"as_of": "2026-11-12T17:50:00+00:00"},
            "conflicts": {"as_of": None, "gap": {"reason": "not yet"}, "findings": []}}


def build_ok(root, *, db_query, ledger_root=None):
    return _payload()


def build_sleeps(root, *, db_query, ledger_root=None):
    (root / "child.pid").write_text(str(os.getpid()))
    time.sleep(30)
    return _payload()


def build_raises(root, *, db_query, ledger_root=None):
    (root / "child.pid").write_text(str(os.getpid()))
    raise RuntimeError("source exploded")


def build_allocates(root, *, db_query, ledger_root=None):
    (root / "child.pid").write_text(str(os.getpid()))
    hog = bytearray(1024 * 1024 * 1024)  # 1 GB, far past the cap the test sets
    return {"n": len(hog)}


def build_marks(root, *, db_query, ledger_root=None):
    (root / "built.marker").write_text("built")
    return _payload()


def _vm_size_bytes():
    for line in open("/proc/self/status"):
        if line.startswith("VmSize:"):
            return int(line.split()[1]) * 1024
    return 0


def _assert_reaped(pid):
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    assert not os.path.exists(f"/proc/{pid}") or "Z (zombie)" not in open(f"/proc/{pid}/status").read()


GOOD_BODY = b'{"last": "good"}'
GOOD_ROW = {"product_id": "cio.pages", "scope_key": "global", "body": GOOD_BODY,
            "etag": "sha256:" + hashlib.sha256(GOOD_BODY).hexdigest(), "seq": 7, "as_of": NOW, "built_at": NOW}


def _run(tmp_path, build_fn, *, events=None, store=None, hot=None, dry_run=False, **kw):
    events = events if events is not None else []
    store = store or FakeStore(events)
    conns = []

    def connect():
        conn = FakeConn(events)
        conns.append(conn)
        return conn

    receipt = cio_pages.run_once(connect=connect, root=tmp_path, hot=hot, dry_run=dry_run, now=NOW,
                                 builder_sha="abc", store=store, codec=FakeCodec,
                                 db_query_factory=lambda: None, build_fn=build_fn, **kw)
    return receipt, store, conns


# ------------------------------------------------------------------------------------------------------- tests


def test_success_writes_then_sets_hot_after_the_commit(tmp_path):
    events = []
    hot = FakeHot(events)
    receipt, store, conns = _run(tmp_path, build_ok, events=events, hot=hot)
    assert receipt["outcome"] == "OK" and receipt["wrote"] is True and receipt["hot"] == "set"
    assert json.loads(store.row["body"]) == _payload()
    # product clock = when the build read its sources (composite rule); the oldest section is recorded, not used
    assert abs((store.row["as_of"] - datetime.now(timezone.utc)).total_seconds()) < 60
    assert store.row["source_watermarks"]["_product"] == {"as_of_rule": "sources_read_at",
                                                          "oldest_section_as_of": "2026-11-12T17:50:00+00:00"}
    assert store.row["source_watermarks"]["conflicts"] == {"as_of": None, "gap": True}
    assert [entry["outcome"] for entry in store.log] == ["OK"]
    assert events.index("write") < events.index("commit") < events.index("hot_set")
    key, value, ex_s = hot.sets[0]
    assert key == "cc:product:cio.pages:global" and 0 < ex_s <= cio_pages.HARD_EXPIRY_S
    assert receipt["bytes"] == len(store.row["body"]) and receipt["peak_rss_kb"] > 0
    assert conns[0].closed


def test_timeout_logs_timeout_keeps_last_good_and_reaps_the_child(tmp_path):
    events = []
    store = FakeStore(events, row=GOOD_ROW)
    hot = FakeHot(events)
    t0 = time.monotonic()
    receipt, store, _ = _run(tmp_path, build_sleeps, events=events, store=store, hot=hot, timeout_s=1.0)
    assert time.monotonic() - t0 < 10
    assert receipt["outcome"] == "TIMEOUT" and receipt["wrote"] is False
    assert store.row == GOOD_ROW and "write" not in events and hot.sets == []
    assert [entry["outcome"] for entry in store.log] == ["TIMEOUT"]
    _assert_reaped(int((tmp_path / "child.pid").read_text()))


def test_build_in_child_timeout_raises_and_leaves_no_zombie(tmp_path):
    with pytest.raises(cio_pages.BuildTimeout) as info:
        cio_pages.build_in_child(tmp_path, timeout_s=0.5, db_query_factory=lambda: None, build_fn=build_sleeps)
    assert info.value.pid == int((tmp_path / "child.pid").read_text())
    _assert_reaped(info.value.pid)


def test_child_that_raises_is_failed_and_last_good_kept(tmp_path):
    events = []
    store = FakeStore(events, row=GOOD_ROW)
    hot = FakeHot(events)
    receipt, store, _ = _run(tmp_path, build_raises, events=events, store=store, hot=hot)
    assert receipt["outcome"] == "FAILED" and "source exploded" in receipt["error"]
    assert store.row == GOOD_ROW and "write" not in events and hot.sets == []
    assert store.log[0]["outcome"] == "FAILED" and "source exploded" in store.log[0]["error"]
    _assert_reaped(int((tmp_path / "child.pid").read_text()))


def test_child_past_rlimit_as_is_failed_not_a_parent_crash(tmp_path):
    events = []
    store = FakeStore(events, row=GOOD_ROW)
    cap = _vm_size_bytes() + 128 * 1024 * 1024
    receipt, store, _ = _run(tmp_path, build_allocates, events=events, store=store, rlimit_as_bytes=cap)
    assert receipt["outcome"] == "FAILED" and "MemoryError" in receipt["error"]
    assert store.row == GOOD_ROW and "write" not in events
    _assert_reaped(int((tmp_path / "child.pid").read_text()))


def test_lock_busy_is_skipped_busy_and_no_build_runs(tmp_path):
    events = []
    store = FakeStore(events, lock_free=False, row=GOOD_ROW)
    hot = FakeHot(events)
    receipt, store, _ = _run(tmp_path, build_marks, events=events, store=store, hot=hot)
    assert receipt["outcome"] == "SKIPPED_BUSY"
    assert not (tmp_path / "built.marker").exists()
    assert [entry["outcome"] for entry in store.log] == ["SKIPPED_BUSY"]
    assert store.row == GOOD_ROW and "write" not in events and hot.sets == []


def test_dry_run_writes_nothing_but_measures(tmp_path):
    events = []
    store = FakeStore(events, row=GOOD_ROW)
    hot = FakeHot(events)
    receipt, store, conns = _run(tmp_path, build_ok, events=events, store=store, hot=hot, dry_run=True)
    assert receipt["outcome"] == "OK" and receipt["dry_run"] is True and receipt["wrote"] is False
    assert isinstance(receipt["build_ms"], int) and receipt["build_ms"] >= 0
    assert receipt["bytes"] == len(json.dumps(_payload(), sort_keys=True).encode())
    assert abs((datetime.fromisoformat(receipt["as_of"]) - datetime.now(timezone.utc)).total_seconds()) < 60
    assert conns == [] and events == [] and hot.sets == [] and store.log == [] and store.row == GOOD_ROW


def test_unchanged_body_is_unchanged(tmp_path):
    events = []
    store = FakeStore(events)
    first, store, _ = _run(tmp_path, build_ok, events=events, store=store)
    second, store, _ = _run(tmp_path, build_ok, events=events, store=store)
    assert first["outcome"] == "OK" and second["outcome"] == "UNCHANGED"
    assert first["seq"] == second["seq"] == 1
    assert [entry["outcome"] for entry in store.log] == ["OK", "UNCHANGED"]


def test_over_cap_body_is_refused_and_last_good_kept(tmp_path):
    def build_big(root, *, db_query, ledger_root=None):
        return {"x": "a" * (3 * 1024 * 1024)}

    events = []
    store = FakeStore(events, row=GOOD_ROW)
    receipt, store, _ = _run(tmp_path, build_big, events=events, store=store)
    assert receipt["outcome"] == "REFUSED" and store.row == GOOD_ROW
    assert store.log[0]["outcome"] == "REFUSED"


def test_product_clock_is_sources_read_at_and_records_the_oldest_section():
    read_at = datetime(2026, 11, 12, 18, 0, 5, tzinfo=timezone.utc)
    as_of, marks = cio_pages.product_clock(_payload(), read_at)
    assert as_of == "2026-11-12T18:00:05+00:00"  # not the oldest section (17:50): one lagging slice must not blank the page
    assert marks["_product"]["oldest_section_as_of"] == "2026-11-12T17:50:00+00:00"
    assert marks["regime"] == {"as_of": "2026-11-12T17:50:00+00:00", "gap": False}


def test_oldest_section_as_of_and_none_without_clocks():
    assert cio_pages.oldest_section_as_of(_payload()) == "2026-11-12T17:50:00+00:00"
    assert cio_pages.oldest_section_as_of({"a": {"as_of": None, "gap": "x"}, "b": {"rows": []}}) is None
    assert cio_pages.oldest_section_as_of({"a": {"as_of": "2026-11-12T10:00:00Z"},
                                    "b": {"as_of": "2026-11-12T09:00:00"}}) == "2026-11-12T09:00:00+00:00"
    assert cio_pages.source_watermarks({"a": {"as_of": "t", "gap": None}, "b": {"rows": []}}) == \
        {"a": {"as_of": "t", "gap": False}}


def test_builder_never_imports_api_v2():
    source = open(cio_pages.__file__, encoding="utf-8").read()
    assert "import api_v2" not in source and "from scripts import api_v2" not in source


class RaisingHot:
    """A hot tier whose SET fails (LQ-2600, REVIEW-2606 N1)."""

    def __init__(self, events, exc):
        self.events, self.exc = events, exc

    def set(self, key, value, ex_s):
        self.events.append("hot_set_attempt")
        raise self.exc


@pytest.mark.parametrize("exc_name", ["HotTierDown", "RuntimeError"])
def test_hot_set_failure_after_commit_is_recorded_and_the_pg_result_stands(tmp_path, exc_name):
    """REVIEW-2606 N1: a hot-tier SET that raises (HotTierDown, or any other error) after the PG commit is recorded
    as ``hot: error:<name>``; the run still returns the committed PG result and never raises."""
    from scripts.lib.cc_products.hot_tier import HotTierDown

    exc = HotTierDown("connection refused") if exc_name == "HotTierDown" else RuntimeError("bad reply")
    events = []
    receipt, store, conns = _run(tmp_path, build_ok, events=events, hot=RaisingHot(events, exc))
    assert receipt["hot"] == f"error: {exc_name}"
    assert receipt["outcome"] == "OK" and receipt["wrote"] is True and receipt["seq"] == 1
    assert json.loads(store.row["body"]) == _payload()
    assert [entry["outcome"] for entry in store.log] == ["OK"]
    assert events.index("commit") < events.index("hot_set_attempt") and "rollback" not in events
    assert conns[0].closed

"""Bounded Finviz refreshes resume unfinished screeners; all work is mocked/private.

COVERS = ["scripts/momentum_scalp_early_lane_runner.py", "scripts/finviz_screener_runner.py",
          "scripts/finviz_throttle.py"]
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import finviz_screener_runner as screener
import finviz_throttle as throttle
import momentum_scalp_early_lane_runner as lane

COVERS = [
    "scripts/momentum_scalp_early_lane_runner.py",
    "scripts/finviz_screener_runner.py",
    "scripts/finviz_throttle.py",
]


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def time(self):
        return 1000.0 + self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(lane.REFRESH_RECEIPT_ENV, str(tmp_path / "refresh.json"))
    monkeypatch.setattr(throttle, "_STATE", tmp_path / "throttle.json")
    monkeypatch.setattr(throttle, "_LOCK", tmp_path / "throttle.lock")
    # Any missing mock fails before a child, credential read, DB or HTTP call.
    monkeypatch.setattr(lane, "_run", lambda *a, **k: pytest.fail("unmocked child"))
    monkeypatch.setattr(screener, "_get_conn", lambda: pytest.fail("unmocked DB"))
    monkeypatch.setattr(screener, "_get_finviz_cookie", lambda: pytest.fail("credential read"))
    monkeypatch.setattr(screener, "_get_finviz_token", lambda: pytest.fail("credential read"))
    monkeypatch.setattr(screener.urllib.request, "urlopen", lambda *a, **k: pytest.fail("unmocked HTTP"))
    return tmp_path


def result(rc=0, ms=1):
    return {"rc": rc, "latency_ms": ms, "stdout_tail": "wrote 7 rows", "stderr_tail": ""}


def test_interrupted_child_is_durable_and_first_on_next_refresh(isolated, monkeypatch):
    calls = []

    def crash(cmd, timeout):
        sid = cmd[-1]
        calls.append(sid)
        assert sid in lane._read_pending_screeners(), "cursor must precede child launch"
        with lane.refresh_lock_path().open("a+") as peer:
            with pytest.raises(BlockingIOError):
                fcntl.flock(peer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sid == "b":
            raise subprocess.TimeoutExpired(cmd, timeout)
        return result()

    monkeypatch.setattr(lane, "_run", crash)
    with pytest.raises(subprocess.TimeoutExpired):
        lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a", "b", "c", "d"])
    assert lane._read_pending_screeners() == ["b", "c", "d"]
    assert json.loads(lane.refresh_receipt_path().read_text())["state"] == "STARTED"
    calls.clear()
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout: calls.append(cmd[-1]) or result())
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a", "b", "c", "d"])
    assert calls == ["b", "c", "d", "a"]
    assert out["ok"] and lane._read_pending_screeners() == []
    assert json.loads(lane.refresh_receipt_path().read_text())["state"] == "DONE"


def test_deadline_deferral_is_partial_and_preserves_tail(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout: calls.append(cmd) or result(124))
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a", "b", "c", "d"])
    assert len(calls) == 1 and out["rc"] == 124 and out["ok"] is False
    assert out["pending_screener_ids"] == ["a", "b", "c", "d"]
    assert lane.refresh_age_min() is None
    assert json.loads(lane.refresh_receipt_path().read_text())["state"] == "FAILED"


def test_narrow_caller_cannot_clear_another_subsets_pending_work(isolated, monkeypatch):
    # Establish a stopped four-screener batch under the real shared lock.
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout: result(124))
    lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a", "b", "c", "d"])
    calls = []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout: calls.append(cmd[-1]) or result())
    out = lane.stage_finviz_scan(False, deadline_s=260, screener_ids=["a", "b"])
    assert calls == ["a", "b"]
    assert lane._read_pending_screeners() == ["c", "d"]
    assert out["ok"] is False and out["rc"] == 124
    assert lane.refresh_age_min() is None, "a narrower success cannot hide the unfinished hot list"


def test_busy_shared_lock_does_not_mutate_owner_state(isolated):
    receipt = lane.refresh_receipt_path()
    receipt.write_text('{"state":"STARTED","pid":123}')
    with lane.refresh_lock_path().open("a+") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    assert out["rc"] == 124 and out["reason"] == "refresh_locked_deferred"
    assert json.loads(receipt.read_text()) == {"state": "STARTED", "pid": 123}
    assert not lane.refresh_resume_path().exists()


def test_child_budget_is_below_unchanged_hard_cap(isolated, monkeypatch):
    seen = []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout: seen.append((cmd, timeout)) or result())
    lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    cmd, hard = seen[0]
    cooperative = float(cmd[cmd.index("--deadline-seconds") + 1])
    assert lane.FINVIZ_TIMEOUT == 240
    assert cooperative == hard - lane.TERM_GRACE_S
    assert 0 < cooperative < hard <= 170 - lane.DEADLINE_HEADROOM_S


def test_exhausted_budget_starts_no_child_and_keeps_cursor(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lane, "time", clock)
    out = lane.stage_finviz_scan(False, deadline_s=20, started_monotonic=96, screener_ids=["a"])
    assert out["rc"] == 124 and out["calls"][0]["skipped"] == "outer_deadline_exhausted"
    assert not lane.refresh_resume_path().exists()


@pytest.mark.parametrize("bad", ["{", "[]", '{"schema":"wrong","pending_screener_ids":[]}'])
def test_corrupt_cursor_is_preserved_and_refuses_new_work(isolated, bad):
    lane.refresh_resume_path().write_text(bad)
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    assert out["ok"] is False and out["reason"] == "resume_state_unavailable"
    assert lane.refresh_resume_path().read_text() == bad


def test_failed_cursor_publication_starts_no_child(isolated, monkeypatch):
    monkeypatch.setattr(lane.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("fixture disk full")))
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    assert out["ok"] is False and out["reason"] == "resume_state_unavailable"


def test_dry_run_writes_no_cursor_or_lock(isolated):
    assert lane.stage_finviz_scan(True, deadline_s=170, screener_ids=["a"])["ok"]
    assert list(isolated.iterdir()) == []


def test_throttle_cooldown_defers_without_fail_open(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(throttle, "time", clock)
    throttle._STATE.write_text(json.dumps({"cooldown_until": clock.time() + 60}))
    with pytest.raises(TimeoutError, match="cooldown"):
        throttle.acquire(timeout=5, deadline_monotonic=clock.monotonic() + 5)
    assert clock.sleeps == []
    assert "last_request" not in json.loads(throttle._STATE.read_text())


def test_throttle_lock_wait_is_inside_deadline(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(throttle, "time", clock)
    with throttle._LOCK.open("a+") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TimeoutError):
            throttle.acquire(deadline_monotonic=clock.monotonic() + 0.12)
    assert sum(clock.sleeps) == pytest.approx(0.12)
    assert not throttle._STATE.exists()


def test_throttle_slot_within_budget_still_obeys_global_spacing(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(throttle, "time", clock)
    throttle._STATE.write_text(json.dumps({"last_request": clock.time()}))
    waited = throttle.acquire(deadline_monotonic=clock.monotonic() + 10)
    assert waited == throttle.MIN_INTERVAL
    assert json.loads(throttle._STATE.read_text())["last_request"] == clock.time()


def test_http_timeout_uses_budget_remaining_after_throttle(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(screener, "time", clock)
    seen = {}

    def acquire(**kw):
        seen.update(kw)
        clock.now += 6

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b"fixture"

    def request(*a, **kw):
        seen["http_timeout"] = kw["timeout"]
        return Response()

    monkeypatch.setattr(screener, "_fv_acquire", acquire)
    monkeypatch.setattr(screener.urllib.request, "urlopen", request)
    assert screener._http_get("https://finviz.invalid/export", {}, deadline_monotonic=110) == "fixture"
    assert seen == {"timeout": 10, "deadline_monotonic": 110, "http_timeout": 4}


def test_throttle_deadline_never_falls_back_to_token_or_html(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(screener, "time", clock)
    calls = []

    def acquire(**kw):
        calls.append(kw)
        raise TimeoutError("fixture cooldown")

    monkeypatch.setattr(screener, "_fv_acquire", acquire)
    with pytest.raises(screener._DeadlineExpired):
        screener._fetch_screener_tickers(
            "https://finviz.invalid/screener.ashx?v=1", "fixture-cookie", "fixture-token", deadline_monotonic=110
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure,expected_calls",
    [
        ("login", 3),
        ("http", 3),
        ("rate_limit", 1),
        ("malformed", 3),
        ("empty_body", 3),
    ],
)
def test_failed_fetch_is_not_a_verified_empty_export(isolated, monkeypatch, failure, expected_calls):
    calls = []

    def fetch(*a, **kw):
        calls.append(a)
        if failure == "http":
            raise OSError("synthetic HTTP failure")
        if failure == "rate_limit":
            raise screener._RateLimited()
        return {
            "login": "<html>Please sign in</html>",
            "malformed": "No.,Ticker,Price\n1,not-a-ticker,2\n",
            "empty_body": "",
        }[failure]

    monkeypatch.setattr(screener, "_http_get", fetch)
    with pytest.raises(screener._ScreenerFetchFailed):
        screener._fetch_screener_tickers(
            "https://finviz.invalid/screener.ashx?v=1", "fixture-cookie", "fixture-token", deadline_monotonic=110
        )
    assert len(calls) == expected_calls


@pytest.mark.parametrize("cookie,token", [("fixture-cookie", "fixture-token"), ("", "fixture-token")])
def test_verified_header_only_csv_is_valid_empty_without_extra_request(isolated, monkeypatch, cookie, token):
    calls = []
    monkeypatch.setattr(screener, "_http_get", lambda *a, **k: calls.append(a) or "No.,Ticker,Company,Price\n")
    assert (
        screener._fetch_screener_tickers(
            "https://finviz.invalid/screener.ashx?v=1", cookie, token, deadline_monotonic=110
        )
        == []
    )
    assert len(calls) == 1


def test_verified_html_tickers_remain_an_available_fallback(isolated, monkeypatch):
    bodies = iter(["<html>login</html>", "<html>login</html>", '<a href="quote.ashx?t=FAKE">FAKE</a>'])
    monkeypatch.setattr(screener, "_http_get", lambda *a, **k: next(bodies))
    assert screener._fetch_screener_tickers(
        "https://finviz.invalid/screener.ashx?v=1", "fixture-cookie", "fixture-token", deadline_monotonic=110
    ) == ["FAKE"]


def test_unbounded_legacy_fetch_retains_empty_failure_compatibility(isolated, monkeypatch):
    monkeypatch.setattr(screener, "_http_get", lambda *a, **k: "<html>login</html>")
    assert screener._fetch_screener_tickers("https://finviz.invalid/screener.ashx?v=1", "fixture-cookie") == []


def test_budget_exhausted_after_throttle_starts_no_http(isolated, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(screener, "time", clock)
    monkeypatch.setattr(screener, "_fv_acquire", lambda **kw: setattr(clock, "now", 111))
    with pytest.raises(screener._DeadlineExpired):
        screener._http_get("https://finviz.invalid/export", {}, deadline_monotonic=110)


def test_expired_fetch_rolls_back_without_starting_membership_writes(isolated, monkeypatch):
    from types import ModuleType

    # The real function imports the cursor type even when its connection is
    # mocked. Keep that import local to this case and independent of DB extras.
    driver, extras = ModuleType("psycopg2"), ModuleType("psycopg2.extras")
    driver.__path__ = []
    driver.extras = extras
    driver.connect = lambda **_kw: pytest.fail("unmocked database connection")
    extras.RealDictCursor = object
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
    clock = Clock()
    monkeypatch.setattr(screener, "time", clock)
    queries = []

    class Cursor:
        def execute(self, sql, params=None):
            queries.append(sql)

        def fetchall(self):
            if len(queries) == 1:
                return [{"screener_id": "a", "strategy_type": "fixture", "finviz_url": "fixture", "display_name": "A"}]
            return []

    class Connection:
        def cursor(self, **kw):
            return Cursor()

        def rollback(self):
            queries.append("ROLLBACK")

    def fetch(*a, **kw):
        assert kw["deadline_monotonic"] == 110
        clock.now = 111
        return ["FAKE"]

    monkeypatch.setattr(screener, "_get_conn", Connection)
    monkeypatch.setattr(screener, "_get_finviz_cookie", lambda: "")
    monkeypatch.setattr(screener, "_get_finviz_token", lambda: "")
    monkeypatch.setattr(screener, "_fetch_screener_tickers", fetch)
    with pytest.raises(screener._DeadlineExpired):
        screener.run_screener("a", deadline_monotonic=110)
    assert len(queries) == 3 and queries[-1] == "ROLLBACK"
    assert all(q.startswith("SELECT") for q in queries[:-1])


def test_deadline_deferral_emits_failed_receipt_and_nonzero_exit(isolated, monkeypatch):
    receipts, failed, completed = [], [], []
    monkeypatch.setitem(
        sys.modules,
        "pipeline_registry",
        SimpleNamespace(run_complete=lambda *a, **k: completed.append(a), run_fail=lambda *a, **k: failed.append(a)),
    )
    import lib.lane_last_receipt as receipt

    monkeypatch.setattr(receipt, "write_lane_receipt", lambda *a, **kw: receipts.append(kw))
    monkeypatch.setattr(screener, "run_screener", lambda **kw: (_ for _ in ()).throw(screener._DeadlineExpired()))
    args = SimpleNamespace(screener="a", json=False, deadline_monotonic=110)
    assert screener._run_tracked(args, "fixture-start", 123) == 124
    assert failed and not completed
    assert receipts[0]["ok"] is False and receipts[0]["error"] == "deadline_deferred"
    assert receipts[0]["output"]["produced_count"] == 0


@pytest.mark.parametrize("failures", [0, 1])
def test_incomplete_or_unconfigured_bounded_child_cannot_clear_resume_cursor(isolated, monkeypatch, failures):
    receipts, completed = [], []
    monkeypatch.setitem(
        sys.modules,
        "pipeline_registry",
        SimpleNamespace(run_complete=lambda *a, **k: completed.append(a), run_fail=lambda *a, **k: None),
    )
    import lib.lane_last_receipt as receipt

    monkeypatch.setattr(receipt, "write_lane_receipt", lambda *a, **kw: receipts.append(kw))
    monkeypatch.setattr(
        screener, "run_screener", lambda **kw: {"membership_failures": failures, "db_write_failures": 0, "results": []}
    )
    args = SimpleNamespace(screener="a", json=False, deadline_monotonic=110)
    child_rc = screener._run_tracked(args, "fixture-start", 123)
    monkeypatch.setattr(lane, "_run", lambda *a, **kw: result(child_rc))
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    assert child_rc == 1 and not completed and receipts[0]["ok"] is False
    assert out["ok"] is False and lane._read_pending_screeners() == ["a"]


def test_fetch_failure_emits_nonzero_and_cannot_clear_resume_cursor(isolated, monkeypatch):
    receipts, completed = [], []
    monkeypatch.setitem(
        sys.modules,
        "pipeline_registry",
        SimpleNamespace(run_complete=lambda *a, **k: completed.append(a), run_fail=lambda *a, **k: None),
    )
    import lib.lane_last_receipt as receipt

    monkeypatch.setattr(receipt, "write_lane_receipt", lambda *a, **kw: receipts.append(kw))
    monkeypatch.setattr(screener, "run_screener", lambda **kw: (_ for _ in ()).throw(screener._ScreenerFetchFailed()))
    args = SimpleNamespace(screener="a", json=False, deadline_monotonic=110)
    child_rc = screener._run_tracked(args, "fixture-start", 123)
    monkeypatch.setattr(lane, "_run", lambda *a, **kw: result(child_rc))
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    assert child_rc == 1 and not completed
    assert receipts[0]["error"] == "fetch_failed" and receipts[0]["ok"] is False
    assert out["ok"] is False and lane._read_pending_screeners() == ["a"]


def test_verified_empty_screener_can_complete_without_inventing_rows(isolated, monkeypatch):
    receipts, completed = [], []
    monkeypatch.setitem(
        sys.modules,
        "pipeline_registry",
        SimpleNamespace(
            run_complete=lambda *a, **k: completed.append(a), run_fail=lambda *a, **k: pytest.fail("false failure")
        ),
    )
    import lib.lane_last_receipt as receipt

    monkeypatch.setattr(receipt, "write_lane_receipt", lambda *a, **kw: receipts.append(kw))
    monkeypatch.setattr(
        screener,
        "run_screener",
        lambda **kw: {
            "screeners_run": 1,
            "membership_failures": 0,
            "db_write_failures": 0,
            "results": [{"screener_id": "a", "total_found": 0, "new_tickers": 0}],
        },
    )
    args = SimpleNamespace(screener="a", json=False, deadline_monotonic=110)
    child_rc = screener._run_tracked(args, "fixture-start", 123)
    monkeypatch.setattr(lane, "_run", lambda *a, **kw: result(child_rc))
    out = lane.stage_finviz_scan(False, deadline_s=170, screener_ids=["a"])
    assert child_rc == 0 and completed and out["ok"]
    assert receipts[0]["output"]["produced_count"] == 0
    assert lane._read_pending_screeners() == []


@pytest.mark.parametrize("invalid", ["0", "-1", "nan", "inf"])
def test_invalid_child_budget_refused_before_runtime_work(isolated, invalid):
    with pytest.raises(SystemExit) as exc:
        screener.main(["--deadline-seconds", invalid])
    assert exc.value.code == 2

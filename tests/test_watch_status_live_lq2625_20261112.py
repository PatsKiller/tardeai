"""GET /api/v2/watch/status (LQ-20261107-2625, Watch v003 D1). Synthetic data only, no database, no network.

Pins: the verdict is computed over exactly four required inputs (My List, Prospects, Alerts, Regime); an unread input is
UNKNOWN and never OK; UNKNOWN beats STALE beats OK; session-dependent limits; alerts is UNKNOWN until the evaluator has a
run record; every statement is a SELECT; 30 s cache with a double-checked lock; the body goes out in the real api_v2
``{"ok": true, "data": ...}`` envelope (the route tests need the api_v2 hunk of PATCH-LQ-20261107-2625 and skip without it).
"""

from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import watch_status_live as wsl  # noqa: E402

NOW = datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)
RTH = lambda _n: True  # noqa: E731
OFF = lambda _n: False  # noqa: E731
UNK = lambda _n: None  # noqa: E731


def ago(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


class FakeQ:
    """q(sql, params) answering from per-input as_of values; records every statement."""

    def __init__(self, **as_of):
        self.as_of = {"my_list": ago(60), "prospects": ago(60), "alerts": ago(60), "regime": ago(3600)}
        self.as_of.update(as_of)
        self.alerts_table = True
        self.errors: dict = {}
        self.sql: list = []

    def __call__(self, sql, params=None):
        self.sql.append(sql)
        key = ("alerts_present" if "to_regclass" in sql else
               "alerts" if "watch_alerts_eval_runs" in sql else
               "my_list" if "watchlist_items" in sql else
               "prospects" if "cio_prospect" in sql else "regime")
        if key in self.errors:
            raise self.errors[key]
        if key == "alerts_present":
            return [{"present": self.alerts_table}]
        return [{"as_of": self.as_of[key]}]


def by_id(out):
    return {i["id"]: i for i in out["inputs"]}


# ── the four inputs and the verdict ─────────────────────────────────────────────────────────────


def test_exactly_four_required_inputs_in_order():
    out = wsl.compute(FakeQ(), NOW, session_fn=RTH)
    assert [i["id"] for i in out["inputs"]] == ["my_list", "prospects", "alerts", "regime"]
    assert out["required_inputs"] == ["my_list", "prospects", "alerts", "regime"]
    assert all(i["required"] for i in out["inputs"])
    assert out["schema"] == "WatchStatus@v1"


def test_all_four_fresh_is_ok_with_per_input_fields():
    out = wsl.compute(FakeQ(), NOW, session_fn=RTH)
    assert out["verdict"] == "OK" and out["session"] == "rth"
    for i in out["inputs"]:
        assert i["state"] == "OK" and i["as_of"] and i["age_s"] is not None and i["threshold_s"]
        assert set(i) >= {"id", "label", "state", "source_id", "owner", "as_of", "age_s", "threshold_s", "reason",
                          "needs_backend", "timed_out"}


def test_my_list_30_min_in_rth_26_h_off_session():
    q = FakeQ(my_list=ago(40 * 60))
    assert by_id(wsl.compute(q, NOW, session_fn=RTH))["my_list"]["state"] == "STALE"
    assert by_id(wsl.compute(q, NOW, session_fn=OFF))["my_list"]["state"] == "OK"
    assert by_id(wsl.compute(FakeQ(my_list=ago(27 * 3600)), NOW, session_fn=OFF))["my_list"]["state"] == "STALE"


def test_prospects_30_min_in_rth_26_h_off_session():
    q = FakeQ(prospects=ago(31 * 60))
    assert by_id(wsl.compute(q, NOW, session_fn=RTH))["prospects"]["state"] == "STALE"
    assert by_id(wsl.compute(q, NOW, session_fn=OFF))["prospects"]["state"] == "OK"


def test_regime_limit_is_26_h_in_every_session():
    for fn in (RTH, OFF):
        assert by_id(wsl.compute(FakeQ(regime=ago(25 * 3600)), NOW, session_fn=fn))["regime"]["state"] == "OK"
        assert by_id(wsl.compute(FakeQ(regime=ago(27 * 3600)), NOW, session_fn=fn))["regime"]["state"] == "STALE"


def test_alerts_20_min_in_rth_once_the_run_record_exists():
    out = wsl.compute(FakeQ(alerts=ago(21 * 60)), NOW, session_fn=RTH)
    assert by_id(out)["alerts"]["state"] == "STALE" and out["verdict"] == "STALE"
    out = wsl.compute(FakeQ(alerts=ago(21 * 60)), NOW, session_fn=OFF)
    assert by_id(out)["alerts"]["state"] == "OK"


def test_alerts_without_a_run_record_is_unknown_needs_backend_and_turns_the_chip():
    q = FakeQ()
    q.alerts_table = False
    out = wsl.compute(q, NOW, session_fn=RTH)
    a = by_id(out)["alerts"]
    assert a["state"] == "UNKNOWN" and a["needs_backend"] is True and "run record" in a["reason"]
    assert out["verdict"] == "UNKNOWN"          # the other three are OK; one unread input is enough


def test_empty_store_is_unknown_never_ok():
    for iid in ("my_list", "prospects", "regime"):
        out = wsl.compute(FakeQ(**{iid: None}), NOW, session_fn=RTH)
        assert by_id(out)[iid]["state"] == "UNKNOWN" and by_id(out)[iid]["reason"]
        assert out["verdict"] == "UNKNOWN"


def test_a_read_error_is_unknown_and_names_the_failure():
    for iid in ("my_list", "prospects", "regime", "alerts"):
        q = FakeQ()
        q.errors[iid] = RuntimeError("boom")
        out = wsl.compute(q, NOW, session_fn=RTH)
        r = by_id(out)[iid]
        assert r["state"] == "UNKNOWN" and "RuntimeError" in r["reason"] and out["verdict"] == "UNKNOWN"


def test_statement_timeout_is_unknown_and_flagged():
    q = FakeQ()
    q.errors["prospects"] = wsl.Timeout()
    out = wsl.compute(q, NOW, session_fn=RTH)
    r = by_id(out)["prospects"]
    assert r["state"] == "UNKNOWN" and r["timed_out"] is True and "2000 ms" in r["reason"]


def test_a_future_as_of_is_unknown_not_ok():
    out = wsl.compute(FakeQ(regime=NOW + timedelta(hours=2)), NOW, session_fn=RTH)
    assert by_id(out)["regime"]["state"] == "UNKNOWN" and "future" in by_id(out)["regime"]["reason"]
    # a small forward skew (< 5 min) is tolerated
    assert by_id(wsl.compute(FakeQ(regime=NOW + timedelta(seconds=60)), NOW, session_fn=RTH))["regime"]["state"] == "OK"


def test_unknown_beats_stale_and_the_cause_names_both_sides():
    q = FakeQ(my_list=ago(3 * 3600), regime=None)
    out = wsl.compute(q, NOW, session_fn=RTH)
    assert out["verdict"] == "UNKNOWN" and "Regime" in out["cause"]
    assert by_id(out)["my_list"]["state"] == "STALE"          # still reported per input


def test_stale_only_names_the_stale_inputs():
    out = wsl.compute(FakeQ(my_list=ago(3 * 3600), prospects=ago(3 * 3600)), NOW, session_fn=RTH)
    assert out["verdict"] == "STALE" and "My List" in out["cause"] and "Prospects" in out["cause"]
    assert "Regime" not in out["cause"]


def test_unknown_session_uses_the_stricter_limits_and_says_so():
    out = wsl.compute(FakeQ(my_list=ago(40 * 60)), NOW, session_fn=UNK)
    assert out["session"] == "unknown" and by_id(out)["my_list"]["state"] == "STALE"


def test_verdict_is_ok_only_for_four_ok_inputs():
    rows = wsl.compute(FakeQ(), NOW, session_fn=RTH)["inputs"]
    assert wsl.verdict_of(rows)[0] == "OK"
    assert wsl.verdict_of(rows[:3])[0] == "UNKNOWN"                      # a missing input is never OK
    assert wsl.verdict_of(rows + rows[:1])[0] == "UNKNOWN"               # nor is a duplicated one


def test_every_statement_is_a_select():
    q = FakeQ()
    wsl.compute(q, NOW, session_fn=RTH)
    assert len(q.sql) == 5
    for s in q.sql:
        low = s.strip().lower()
        assert low.startswith("select") and not re.search(r"\b(insert|update|delete|copy|alter|drop|truncate)\b", low)


# ── serve(): connection, cache, storm ───────────────────────────────────────────────────────────


def test_no_connection_is_unknown_for_all_four_never_ok_never_raises():
    wsl._CACHE.clear()
    out = wsl.serve(lambda: None, now=NOW, use_cache=False, session_fn=RTH)
    assert out["verdict"] == "UNKNOWN" and [i["state"] for i in out["inputs"]] == ["UNKNOWN"] * 4
    out = wsl.serve(lambda: (_ for _ in ()).throw(RuntimeError("x")), now=NOW, use_cache=False, session_fn=RTH)
    assert out["verdict"] == "UNKNOWN"


class _Conn:
    def rollback(self):
        pass


def test_cache_30_s_and_the_double_checked_lock(monkeypatch):
    import lib.home_status_live as hsl

    calls = []

    def fake_readonly(get_conn, timeout_cls):
        def q(sql, params=None):
            calls.append(sql)
            import time as _t
            _t.sleep(0.01)
            return [{"present": True}] if "to_regclass" in sql else [{"as_of": ago(30)}]
        return q

    monkeypatch.setattr(hsl, "readonly_query", fake_readonly)
    wsl._CACHE.clear()
    outs = []
    ts = [threading.Thread(target=lambda: outs.append(wsl.serve(lambda: _Conn(), now=NOW, session_fn=RTH))) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 5, "a miss storm must cost ONE computation (5 statements), not one per request"
    assert len(outs) == 12 and all(o["verdict"] == "OK" for o in outs)
    n = len(calls)
    wsl.serve(lambda: _Conn(), now=NOW, session_fn=RTH)
    assert len(calls) == n                                   # cached
    wsl.serve(lambda: _Conn(), now=NOW, use_cache=False, session_fn=RTH)
    assert len(calls) == n + 5                               # use_cache=False recomputes
    wsl._CACHE.clear()


def test_a_failed_computation_is_not_cached_as_ok(monkeypatch):
    import lib.home_status_live as hsl

    monkeypatch.setattr(hsl, "readonly_query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    wsl._CACHE.clear()
    out = wsl.serve(lambda: _Conn(), now=NOW, session_fn=RTH)
    assert out["verdict"] == "UNKNOWN" and "v" not in wsl._CACHE


# ── the real api_v2 envelope (needs the api_v2 hunk) ────────────────────────────────────────────


def _api():
    import scripts.api_v2 as api
    return api


def _need_route():
    api = _api()
    if "/api/v2/watch/status" not in api.ROUTES:
        pytest.skip("api_v2 route hunk (PATCH-LQ-20261107-2625) not applied in this tree")
    return api


def test_route_answers_in_the_real_api_v2_envelope(monkeypatch):
    api = _need_route()
    import db_adapter

    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: None)
    wsl._CACHE.clear()
    status, body = api.handle("/api/v2/watch/status")
    wsl._CACHE.clear()
    assert status == 200
    assert set(body) == {"ok", "data"} and body["ok"] is True
    assert "verdict" not in body                               # the payload is under data, not beside ok
    d = body["data"]
    assert d["schema"] == "WatchStatus@v1" and d["verdict"] == "UNKNOWN"
    assert [i["id"] for i in d["inputs"]] == list(wsl.REQUIRED_INPUTS)


def test_the_committed_frontend_fixture_has_the_real_envelope_shape(monkeypatch):
    """The fixture the frontend tests import is ``{ok, data}``-wrapped exactly as the route serves it (Home v010 shipped
    broken because its fixtures were unwrapped)."""
    fx = json.loads((ROOT / "tests" / "fixtures" / "watch_status_envelope.json").read_text())
    assert set(fx) == {"ok", "data"} and fx["ok"] is True
    real = {"ok": True, "data": wsl.compute(FakeQ(), NOW, session_fn=RTH)}
    assert set(fx["data"]) == set(real["data"])
    assert [set(i) for i in fx["data"]["inputs"]] == [set(i) for i in real["data"]["inputs"]]
    assert [i["id"] for i in fx["data"]["inputs"]] == list(wsl.REQUIRED_INPUTS)


# ── boundaries, TTL and which column each input reads (survivors of the first mutant run) ────────


def test_the_limit_itself_is_ok_one_second_over_is_stale():
    for iid, lim in (("my_list", 1800), ("prospects", 1800), ("alerts", 1200)):
        assert by_id(wsl.compute(FakeQ(**{iid: ago(lim)}), NOW, session_fn=RTH))[iid]["state"] == "OK"
        assert by_id(wsl.compute(FakeQ(**{iid: ago(lim + 1)}), NOW, session_fn=RTH))[iid]["state"] == "STALE"
    assert by_id(wsl.compute(FakeQ(regime=ago(26 * 3600)), NOW, session_fn=OFF))["regime"]["state"] == "OK"
    assert by_id(wsl.compute(FakeQ(regime=ago(26 * 3600 + 1)), NOW, session_fn=OFF))["regime"]["state"] == "STALE"


def test_the_cache_expires_after_30_s(monkeypatch):
    import lib.home_status_live as hsl

    calls = []

    def fake_readonly(get_conn, timeout_cls):
        def q(sql, params=None):
            calls.append(sql)
            return [{"present": True}] if "to_regclass" in sql else [{"as_of": ago(30)}]
        return q

    clock = [1000.0]
    monkeypatch.setattr(hsl, "readonly_query", fake_readonly)
    monkeypatch.setattr(wsl.time, "monotonic", lambda: clock[0])
    wsl._CACHE.clear()
    wsl.serve(lambda: _Conn(), now=NOW, session_fn=RTH)
    clock[0] += 29
    wsl.serve(lambda: _Conn(), now=NOW, session_fn=RTH)
    assert len(calls) == 5                                   # still cached at 29 s
    clock[0] += 2
    wsl.serve(lambda: _Conn(), now=NOW, session_fn=RTH)
    assert len(calls) == 10                                  # recomputed after 30 s
    wsl._CACHE.clear()


def test_each_input_reads_its_documented_store_and_column():
    q = FakeQ()
    wsl.compute(q, NOW, session_fn=RTH)
    sql = " | ".join(s.lower() for s in q.sql)
    assert "max(updated_at)" in sql and "from watchlist_items" in sql
    assert "max(as_of)" in sql and "from cio_prospect" in sql
    assert "max(generated_at)" in sql and "from market_regime_snapshots" in sql
    # alerts: the evaluator's last SUCCESSFUL run, never watch_alerts.last_fired_at
    assert "max(finished_at)" in sql and "from watch_alerts_eval_runs" in sql and "status in" in sql
    assert "last_fired_at" not in sql and "from watch_alerts " not in sql

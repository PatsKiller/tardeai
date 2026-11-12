"""GET /api/v2/home/status served (home-status-backend, 2026-11-12). Synthetic data only.

Pins: the route is registered in the served ROUTES table; the request-time computation uses the 2411 rule unchanged;
every failure is UNKNOWN with a named reason (never YES, never a 500); the flat ``trade_ready`` / ``gates`` views.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib import home_status_live as hsl  # noqa: E402
from scripts.lib import home_trade_ready as htr  # noqa: E402
from scripts.lib.home_trade_ready import Item, Reading  # noqa: E402

NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)   # a Saturday: off-session thresholds
FRESH = "2026-11-14T16:59:00+00:00"
POLICY = {"confirmed_no_overrides_unknown": True}


def _ok(name, **kw):
    return Reading(name=name, state=htr.OK, as_of=FRESH, threshold_s=900, source_id=f"src_{name}", **kw)


def _all_ok():
    return [_ok(n) for n in htr.REQUIRED_INPUTS] + [_ok(htr.SCHEDULERS), _ok(htr.ALERTS)]


def _flat(readings, policy=POLICY):
    return hsl.flatten(htr.compute_verdict(readings, NOW, policy=policy), hsl.READ_FROM_COMPUTED)


# ── route registration (fail-before on c238eec68: no such key, no handler) ─────────────────────


def test_route_is_registered_in_the_served_table():
    import scripts.api_v2 as api

    assert "/api/v2/home/status" in api.ROUTES
    assert '"/api/v2/home/status": lambda: _home_status(),' in Path(api.__file__).read_text()
    assert callable(getattr(api, "_home_status", None))


def test_route_without_a_database_is_unknown_never_yes(monkeypatch):
    import scripts.api_v2 as api
    import db_adapter

    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: None)
    hsl._CACHE.clear()
    out = api.ROUTES["/api/v2/home/status"]()
    hsl._CACHE.clear()
    assert out["schema"] == htr.SCHEMA
    assert out["verdict"] == htr.UNKNOWN and out["trade_ready"]["verdict"] == htr.UNKNOWN
    assert out["trade_ready"]["cause"]
    assert out["gates"] and all(g["state"] != htr.OK for g in out["gates"] if g["required"])


# ── the flat views ──────────────────────────────────────────────────────────────────────────────


def test_yes_only_when_every_required_input_ok():
    out = _flat(_all_ok())
    assert out["trade_ready"]["verdict"] == htr.YES
    ids = [g["id"] for g in out["gates"]]
    assert ids[:7] == ["p0", "p1_blocking", "incident_classes", "gates", "portfolio", "orders", "data"]
    g = out["gates"][0]
    assert set(g) >= {"id", "label", "state", "source_id", "as_of", "age_s", "threshold_s", "reason", "needs_backend"}
    assert g["age_s"] == 60.0 and g["as_of"] == FRESH


def test_open_p0_is_no_with_its_category_as_cause_even_with_an_unknown_input():
    rs = [r for r in _all_ok() if r.name not in (htr.P0, htr.ORDERS)]
    rs.append(Reading(name=htr.P0, state=htr.WARN, as_of=FRESH, threshold_s=600, value=1,
                      items=[Item(id="i1", title="synthetic_kill", category="Synthetic Kill")]))
    rs.append(htr.no_source(htr.ORDERS, "no heartbeat"))
    out = _flat(rs)
    assert out["trade_ready"]["verdict"] == htr.NO
    assert out["trade_ready"]["cause"].startswith("Synthetic Kill")
    orders = next(g for g in out["gates"] if g["id"] == "orders")
    assert orders["state"] == htr.UNKNOWN and orders["needs_backend"] is True and "NEEDS BACKEND" in orders["reason"]


def test_unknown_names_the_unread_input():
    rs = [r for r in _all_ok() if r.name != htr.DATA] + [htr.unknown(htr.DATA, "quote store unreadable")]
    out = _flat(rs)
    assert out["trade_ready"]["verdict"] == htr.UNKNOWN
    assert "data: quote store unreadable" in out["trade_ready"]["cause"]


def test_stale_input_never_yes():
    rs = [r for r in _all_ok() if r.name != htr.PORTFOLIO]
    rs.append(Reading(name=htr.PORTFOLIO, state=htr.OK, as_of="2026-11-14T10:00:00+00:00", threshold_s=900))
    out = _flat(rs)
    # 2144 rule: a read-but-stale row is "!= OK" -> NO (never YES)
    assert out["trade_ready"]["verdict"] == htr.NO
    assert next(g for g in out["gates"] if g["id"] == "portfolio")["state"] == htr.STALE


# ── request-time computation over a stub query (the lane's providers, unchanged) ──────────────


def test_compute_runs_the_lane_providers_and_a_failing_query_is_unknown():
    def q(sql, params=None):
        raise RuntimeError("synthetic failure")

    out = hsl.compute(q, NOW, state_root=Path("/nonexistent-state-root"), registry_loader=lambda: None)
    assert out["verdict"] == htr.UNKNOWN and out["read_from"] == hsl.READ_FROM_COMPUTED
    assert {g["id"] for g in out["gates"]} >= {"p0", "gates", "portfolio", "orders", "data"}


def test_serve_never_raises_and_caches(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise ValueError("synthetic")

    monkeypatch.setattr(hsl, "compute", boom)
    hsl._CACHE.clear()
    out = hsl.serve(lambda: None, now=NOW)
    assert out["verdict"] == htr.UNKNOWN and "ValueError" in out["trade_ready"]["cause"]
    hsl.serve(lambda: None, now=NOW)
    assert len(calls) == 2   # a failure is never cached

    monkeypatch.setattr(hsl, "compute", lambda *a, **k: (calls.append(1), {"verdict": "NO", "x": 1})[1])
    hsl._CACHE.clear()
    hsl.serve(lambda: None, now=NOW)
    second = hsl.serve(lambda: None, now=NOW)
    hsl._CACHE.clear()
    assert len(calls) == 3 and "cache_age_s" in second


def test_readonly_query_sets_read_only_and_timeout_and_rolls_back():
    seen = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params=None): seen.append(sql)
        def fetchall(self): return [{"a": 1}]

    class Conn:
        rollbacks = 0
        def cursor(self, **k): return Cur()
        def rollback(self): Conn.rollbacks += 1
        def commit(self): raise AssertionError("a read-only session never commits")

    q = hsl.readonly_query(lambda: Conn(), TimeoutError)
    assert q("SELECT 1", None) == [{"a": 1}]
    assert seen[0] == "SET TRANSACTION READ ONLY" and seen[1].startswith("SET LOCAL statement_timeout")
    assert Conn.rollbacks == 2
    with pytest.raises(ConnectionError):
        hsl.readonly_query(lambda: None, TimeoutError)("SELECT 1")

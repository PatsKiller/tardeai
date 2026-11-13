"""LQ-20261107-2644: the /api/v2/home/priorities-live route (needs PATCH-LQ-20261107-2644-api_v2.diff applied)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scripts.api_v2 as api  # noqa: E402
from lib import home_approvals_api as haa  # noqa: E402

INC = {"state": "OK", "items": [{"incident_id": "a", "priority": "P0", "blocks_trading": True, "category": "Outage",
                                 "cause": "pipeline failed", "first_seen_at": "2026-11-12T10:00:00+00:00"}]}


def _wire(monkeypatch, *, inc=INC, since=None, appr=(200, {"ok": True, "data": {"count": 1, "urgent_count": 0}})):
    api._HOME_PRIORITIES_LIVE_CACHE.clear()
    monkeypatch.setattr(api, "_home_incidents", lambda: inc)
    monkeypatch.setattr(api, "_home_since_close", lambda: since if since is not None else {"status": "no_snapshot"})
    monkeypatch.setattr(haa, "handle", lambda *a, **k: appr)


def test_route_is_registered():
    import inspect
    assert '"/api/v2/home/priorities-live": lambda: _home_priorities_live()' in inspect.getsource(api)


def test_route_ranks_and_names_the_unread_stop_advice(monkeypatch):
    _wire(monkeypatch)
    out = api._home_priorities_live()
    assert out["schema"] == "HomePrioritiesLive@v1" and out["state"] == "PARTIAL"
    assert [i["id"] for i in out["items"]] == ["inc-a", "approvals"]
    assert out["unread"] == [{"input": "stop advice", "reason": "stop advice not read"}]


def test_a_refused_approvals_read_is_unread_not_zero(monkeypatch):
    _wire(monkeypatch, appr=(403, {"ok": False, "code": "AGENT_CALLER_REFUSED"}))
    out = api._home_priorities_live()
    assert any(u["input"] == "approvals" for u in out["unread"]) and all(i["kind"] != "APPROVALS" for i in out["items"])


def test_ok_and_partial_bodies_are_cached_and_unknown_is_not(monkeypatch):
    _wire(monkeypatch)
    first = api._home_priorities_live()
    monkeypatch.setattr(api, "_home_incidents", lambda: {"state": "UNKNOWN"})
    assert api._home_priorities_live() is first  # inside 30 s
    api._HOME_PRIORITIES_LIVE_CACHE.clear()
    monkeypatch.setattr(haa, "handle", lambda *a, **k: (500, {}))
    monkeypatch.setattr(api, "_home_since_close", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    down = api._home_priorities_live()
    assert down["state"] == "UNKNOWN" and down["items"] == [] and "v" not in api._HOME_PRIORITIES_LIVE_CACHE


def test_an_approvals_body_behind_a_non_200_status_is_never_used(monkeypatch):
    _wire(monkeypatch, appr=(503, {"ok": True, "data": {"count": 4, "urgent_count": 1}}))
    out = api._home_priorities_live()
    assert any(u["input"] == "approvals" for u in out["unread"]) and all(i["kind"] != "APPROVALS" for i in out["items"])

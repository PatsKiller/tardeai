"""CAMPAIGN-8H Home item 4b: /api/v2/home/priorities-live caches per authenticated principal, never globally.

The route caches an OK/PARTIAL body for 30 s. That body embeds the approvals count, whose read is principal-gated
(``home_approvals_api`` refuses any caller that is not the operator or the service token), so one body is not valid
for every caller: a body built for one principal (OK, approvals counted) must never be served to another (whose own
approvals read is refused, PARTIAL/unread), and the reverse.

This file ships WITH the ``scripts/api_v2.py`` hunk (PATCH-CAMPAIGN8H-Home-item4-api_v2-for-cc-opus-3.patch) — the
cache-key change and its test are one deliverable, applied together.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import scripts.api_v2 as api  # noqa: E402
from lib import cc_auth  # noqa: E402
from lib import home_approvals_api as haa  # noqa: E402

INC = {"state": "OK", "items": [{"incident_id": "a", "priority": "P0", "blocks_trading": True, "category": "Outage",
                                 "cause": "pipeline failed", "first_seen_at": "2026-11-12T10:00:00+00:00"}]}


def _wire(monkeypatch, principal, appr):
    monkeypatch.setattr(api, "_home_incidents", lambda: INC)
    # A brief whose stop advice was read: with approvals read too, all three inputs are in, so the ranking is OK.
    monkeypatch.setattr(api, "_home_since_close", lambda: {"status": "ok", "cio_brief": {"status": "available", "stop_advice": []}})
    monkeypatch.setattr(cc_auth, "current_principal", lambda: principal)
    monkeypatch.setattr(haa, "handle", lambda *a, **k: appr)


def test_two_principals_never_share_one_priorities_body(monkeypatch):
    api._HOME_PRIORITIES_LIVE_CACHE.clear()
    # The operator's read: approvals counted, so the ranking is complete.
    _wire(monkeypatch, "tailnet:operator", (200, {"ok": True, "data": {"count": 2, "urgent_count": 0}}))
    operator = api._home_priorities_live()
    assert operator["state"] == "OK" and any(i["kind"] == "APPROVALS" for i in operator["items"])

    # A caller whose approvals read is refused: same route, same 30 s, and it must not inherit the operator's body.
    _wire(monkeypatch, "tailnet:someone-else", (403, {"ok": False, "code": "AGENT_CALLER_REFUSED"}))
    other = api._home_priorities_live()
    assert other is not operator
    assert other["state"] == "PARTIAL"
    assert any(u["input"] == "approvals" for u in other["unread"])
    assert all(i["kind"] != "APPROVALS" for i in other["items"])

    # The operator's own entry is still its own (the second caller did not overwrite it).
    monkeypatch.setattr(cc_auth, "current_principal", lambda: "tailnet:operator")
    assert api._home_priorities_live() is operator


def test_each_principal_keeps_its_own_entry_over_time(monkeypatch):
    api._HOME_PRIORITIES_LIVE_CACHE.clear()
    _wire(monkeypatch, "tailnet:operator", (200, {"ok": True, "data": {"count": 1, "urgent_count": 0}}))
    first = api._home_priorities_live()
    _wire(monkeypatch, "tailnet:reader", (403, {"ok": False, "code": "AGENT_CALLER_REFUSED"}))
    second = api._home_priorities_live()
    assert first is not second and first["state"] != second["state"]
    assert len(api._HOME_PRIORITIES_LIVE_CACHE) >= 2


def test_the_cache_key_is_not_the_shared_literal(monkeypatch):
    api._HOME_PRIORITIES_LIVE_CACHE.clear()
    _wire(monkeypatch, "tailnet:operator", (200, {"ok": True, "data": {"count": 0, "urgent_count": 0}}))
    api._home_priorities_live()
    assert "v" not in api._HOME_PRIORITIES_LIVE_CACHE  # the unscoped key is gone for good
    assert all(isinstance(k, tuple) and k[0] == "v" and "principal=" in k[1] for k in api._HOME_PRIORITIES_LIVE_CACHE)

"""LQ-20261107-2486 — a Watch W-lane command that failed is never HTTP 200, and no client can call it success.

Defect (verified on c238eec68): the api_v2 route answered `200, _wcmd.post_star(...)` — literally — for
star / list-membership / alert / refresh-data. `api_v3_watch_commands.post_star` catches its own store
exception and returns `ok: False` with `error`/`detail`, so a failed write reached the browser as HTTP 200.
The v3 star handler happened to read the body (`!res.ok || js?.ok === false`) and the mine/suggest helper
did too, but the HTTP contract itself was wrong: any client that trusts the status sees success.

Fix: each handler names the class of failure in `http_status` (400 = the command as sent cannot be executed,
503 = the store refused or lost the write) beside the cause, and the api_v2 route maps a non-ok reply to that
status, with 400 as the fallback — never 2xx. These tests are synthetic: no DB, no network, no broker.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api_v2  # noqa: E402
import api_v3_watch_commands as wcmd  # noqa: E402


class StoreDown(RuntimeError):
    """Stand-in for psycopg's connection-already-closed (a lost store, not bad input)."""


def _store_down(monkeypatch):
    import db_adapter

    def _boom(*_a, **_k):
        raise StoreDown("connection already closed")

    monkeypatch.setattr(db_adapter, "_get_conn", _boom)


def _post(command: str, body: dict | None):
    return api_v2.handle(f"/api/v3/watch/commands/{command}", method="POST", body=body or {})


# ── the defect: a failed write reached the client as 200 ────────────────────────────────────────────────────


def test_failed_star_write_is_503_with_its_cause(monkeypatch):
    _store_down(monkeypatch)
    status, body = _post("star", {"symbol": "SYNTH"})
    assert status == 503, "a lost store on a real write must not read as success"
    assert body["ok"] is False
    assert body["error"] == "StoreDown", "the failure must name its cause"
    assert "connection already closed" in body["detail"]
    assert body["provider_calls"] == 0


def test_missing_symbol_is_400_and_never_touches_the_store(monkeypatch):
    # The store is DOWN in this test: a 400 (not a 503/500) proves validation ran first and the command was
    # rejected as input, not attempted.
    _store_down(monkeypatch)
    status, body = _post("star", {})
    assert status == 400
    assert body["ok"] is False and body["error"] == "SYMBOL_REQUIRED"
    assert body["http_status"] == 400


def test_list_membership_validation_is_400():
    status, body = _post("list-membership", {"symbol": "SYNTH"})  # no list label
    assert status == 400
    assert body["error"] == "SYMBOL_AND_LIST_REQUIRED"
    assert body["http_status"] == 400


def test_alert_validation_is_400():
    status, body = _post("alert", {})
    assert status == 400
    assert body["error"] == "SYMBOL_REQUIRED"
    assert body["http_status"] == 400


def test_mine_and_suggest_validation_stay_400():
    status, body = _post("mine", {})
    assert status == 400 and body["error"] == "ACTION_MUST_BE_ADD_OR_REMOVE"
    status, body = _post("suggest-dismiss", {})
    assert status == 400 and body["error"] == "SYMBOL_REQUIRED"


@pytest.mark.parametrize("command, handler", [
    ("mine", "post_mine_decision"),
    ("suggest-dismiss", "post_suggest_decision"),
    ("suggest-restore", "post_suggest_decision"),
])
def test_every_command_route_honours_the_handler_class(monkeypatch, command, handler):
    reply = {"ok": False, "error": "StoreDown", "detail": "connection already closed", "http_status": 503}
    monkeypatch.setattr(wcmd, handler, lambda *_a, **_k: dict(reply))
    status, body = _post(command, {"symbol": "SYNTH"})
    assert status == 503 and body["ok"] is False, f"{command} must not swallow the class"


# ── the success paths must not become failures ─────────────────────────────────────────────────────────────


def test_successful_star_write_stays_200_and_commits(monkeypatch):
    import db_adapter

    executed: list[tuple] = []

    class _Cur:
        def execute(self, sql, params=None):
            executed.append((sql, params))

    class _Conn:
        committed = False

        def cursor(self):
            return _Cur()

        def commit(self):
            self.committed = True

    conn = _Conn()
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    status, body = _post("star", {"symbol": "synth"})
    assert status == 200 and body["ok"] is True and body["symbol"] == "SYNTH"
    assert conn.committed, "the write was committed, so the 200 is truthful"
    assert executed and "operator_starred_symbols" in executed[0][0]


def test_refresh_data_success_stays_200():
    status, body = _post("refresh-data", {"symbol": "SYNTH"})
    assert status == 200 and body["ok"] is True and body["provider_calls"] == 0


# ── the route's fallback: a reply that names no class is still not a 2xx ────────────────────────────────────


@pytest.mark.parametrize("reply", [
    {"ok": False, "error": "SOMETHING"},                       # no class at all
    {"ok": False, "error": "SOMETHING", "http_status": 200},   # a 2xx smuggled into the class
    {"ok": False, "error": "SOMETHING", "http_status": 99},    # out of range
    {"ok": False, "error": "SOMETHING", "http_status": "503"},  # wrong type
])
def test_a_failed_reply_without_a_valid_class_falls_back_to_400(monkeypatch, reply):
    monkeypatch.setattr(wcmd, "post_star", lambda body=None: dict(reply))
    status, body = _post("star", {"symbol": "SYNTH"})
    assert status == 400 and body["ok"] is False


# ── the client: neither star surface may show success without one ───────────────────────────────────────────

UI = ROOT / "apps/command-center-v3/src"


def test_ui_watch_unified_star_handler_returns_on_failure_before_any_success_path():
    src = (UI / "pages/WatchIntelligenceUnified.tsx").read_text(encoding="utf-8")
    guard = src.index("!res.ok || js?.ok === false")
    early_return = src.index("return", guard)
    refresh = src.index("setRefreshKey(k => k + 1)", guard)
    assert early_return < refresh, "a failed star must return before the success refresh"


def test_ui_mine_star_toggle_flips_only_on_a_confirmed_ok():
    src = (UI / "components/watch/MineControls.tsx").read_text(encoding="utf-8")
    assert "!r.ok || d?.ok === false" in src, "mineAction must treat an ok:false body as failure"
    assert "if (res.ok) setState(!state)" in src, "the ★ must not toggle before the server confirms"

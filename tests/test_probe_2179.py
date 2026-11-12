"""Reviewer probes for LQ-2179 (cc-opus-3), copied in by LQ-2186. Adapted only where the write path moved from the
swallowing _db_query to the raising _db_query_raising (one atomic UPSERT): the fake now stands behind both names and the
F1/F2 probes fail the statement at that seam. Intent of each probe is unchanged. Synthetic only."""
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import pytest
ROOT = Path.cwd()
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
sys.path.insert(0, str(ROOT / "tests"))
from test_home_last_seen_incidents_20261111 import FakePrefs  # noqa: E402


def _auth():
    import lib.cc_auth as A  # the same module object default_ctx imports
    return A


@pytest.fixture()
def api_prefs(monkeypatch):
    import scripts.api_v2 as api
    fake = FakePrefs()
    monkeypatch.setattr(api, "_db_query", fake)
    monkeypatch.setattr(api, "_db_query_raising", fake)
    yield api, fake
    A = _auth(); A.set_request_context(None, None); A.set_request_principal("")


def _req(principal, listener="serve_proxy", headers=None):
    A = _auth()
    A.set_request_context(listener, headers or {})
    A.set_request_principal(principal)


def _op():
    A = _auth()
    logins = list(A.load_config().allowed_logins)
    assert logins, "no allowed login configured"
    return "tailnet:" + logins[0]


def test_committed_config_is_report_only():
    cfg = _auth().load_config()
    assert getattr(cfg, "report_only", None) is True


def test_report_only_would_deny_request_has_no_principal_so_is_refused(api_prefs):
    """portfolio_server sets principal = authenticated_principal(d); a would-deny decision yields ''."""
    api, fake = api_prefs
    _req("", headers={"Origin": "https://example.invalid", "Sec-Fetch-Site": "same-origin"})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert s == 403 and b["code"] == "NOT_OPERATOR" and "home.last_seen" not in fake.rows


def test_operator_without_same_origin_proof_is_csrf_refused(api_prefs):
    api, fake = api_prefs
    _req(_op(), headers={})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert s == 403 and b["code"] == "CSRF_REFUSED" and "home.last_seen" not in fake.rows


def test_operator_on_direct_listener_is_refused(api_prefs):
    api, fake = api_prefs
    _req(_op(), listener="direct", headers={"Sec-Fetch-Site": "same-origin"})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert s == 403 and "home.last_seen" not in fake.rows


def test_operator_same_origin_is_admitted_end_to_end(api_prefs):
    api, fake = api_prefs
    _req(_op(), headers={"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": "home.last_seen", "value": {"device": "phone"}})
    assert s == 200, b
    assert fake.rows["home.last_seen"]["device"] == "phone"


def test_authenticated_principal_is_empty_for_would_deny():
    A = _auth()
    import inspect
    fields = inspect.signature(A.Decision).parameters
    kw = {k: None for k in fields}
    kw.update(allowed=True, would_deny=True, principal="tailnet:x")
    d = A.Decision(**{k: v for k, v in kw.items() if k in fields})
    assert A.authenticated_principal(d) == ""


# --- F1: a failed read/write of the stored value must not erase the window -----------------------------
def test_failed_read_of_stored_value_must_not_erase_previous_seen_at(api_prefs, monkeypatch):
    api, fake = api_prefs
    fake.rows["home.last_seen"] = {"seen_at": "2026-11-10T12:00:00+00:00", "previous_seen_at": None, "device": "phone"}
    before = dict(fake.rows["home.last_seen"])

    def boom(sql, params=None, fetch="all"):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(api, "_db_query_raising", boom)
    out = api._ui_prefs_set({"key": "home.last_seen", "value": {"device": "phone"}})
    assert out.get("ok") is not True and out["code"] == "STORE_UNAVAILABLE", out
    assert fake.rows["home.last_seen"] == before


def test_failed_write_is_not_reported_ok(api_prefs, monkeypatch):
    api, fake = api_prefs
    monkeypatch.setattr(api, "_db_query_raising", lambda sql, params=None, fetch="all": None)  # no confirmation
    out = api._ui_prefs_set({"key": "home.last_seen", "value": {"device": "phone"}})
    assert out.get("ok") is not True, out
    assert "home.last_seen" not in fake.rows


# --- F3: the 45 s cache freezes served_at/age_s -----------------------------------------------------
def test_cached_body_age_is_computed_at_serve_time(monkeypatch):
    import scripts.api_v2 as api
    from scripts.lib import home_incidents as HI
    api._HOME_INCIDENTS_CACHE.clear()
    monkeypatch.setattr(api, "_db_query_raising", lambda sql, params=None, fetch="all": [] if fetch == "all" else {"events": 0})
    first = api._home_incidents()
    clock = time.monotonic() + 30
    monkeypatch.setattr(time, "monotonic", lambda: clock)
    second = api._home_incidents()
    api._HOME_INCIDENTS_CACHE.clear()
    assert second["snapshot"]["age_s"] >= 29 or second["served_at"] != first["served_at"], (first["served_at"], second["snapshot"])

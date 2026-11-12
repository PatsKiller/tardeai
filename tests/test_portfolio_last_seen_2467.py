"""LQ-20261107-2467 (Portfolio v002 G13): ``portfolio.last_seen`` in /api/v2/ui/prefs.

Same contract as ``home.last_seen`` (LQ-2142/2167/2186): the server stamps seen_at, previous_seen_at is copied
from the stored value in SQL, a client time is ignored, a read never invents a visit, and the write is admitted
only for the operator's signed-in session with same-origin CSRF. Its own key: a Home visit never moves the
Portfolio anchor. Synthetic only: an in-memory fake of ui_prefs, no DB, no network."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")]

from scripts.lib import home_last_seen as HL  # noqa: E402
from test_home_last_seen_incidents_20261111 import FakePrefs  # noqa: E402

KEY = "portfolio.last_seen"
NOW = datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc)


@pytest.fixture()
def prefs(monkeypatch):
    import scripts.api_v2 as api

    fake = FakePrefs()
    monkeypatch.setattr(api, "_db_query", fake)
    monkeypatch.setattr(api, "_db_query_raising", fake)
    yield api, fake
    import lib.cc_auth as A

    A.set_request_context(None, None)
    A.set_request_principal("")


# ----------------------------------------------------------------------------- pure lib
def test_both_keys_are_last_seen_keys_and_nothing_else_is():
    assert HL.is_last_seen_key("home.last_seen") and HL.is_last_seen_key(KEY)
    assert HL.is_last_seen_key(" portfolio.last_seen ")  # the routes strip the key; so does the check
    for other in ("portfolio.shared-symbol-context.v1", "watch.layout", "", None, 3, "portfolio.last_seen.x"):
        assert not HL.is_last_seen_key(other)


def test_read_names_the_portfolio_schema_and_home_is_unchanged():
    assert HL.read(None, None, now=NOW, exists=False, key=KEY)["schema"] == "PortfolioLastSeen@v1"
    assert HL.read(None, None, now=NOW, exists=False)["schema"] == "HomeLastSeen@v1"
    v = {"seen_at": (NOW - timedelta(hours=2)).isoformat(), "previous_seen_at": None, "device": "desktop"}
    r = HL.read(v, NOW, now=NOW, exists=True, key=KEY)
    assert r["schema"] == "PortfolioLastSeen@v1" and r["status"] == "RECORDED" and r["age_sec"] == 7200


def test_read_refuses_an_unknown_key_rather_than_mislabel_it():
    with pytest.raises(ValueError):
        HL.read(None, None, now=NOW, exists=False, key="watch.layout")


# ----------------------------------------------------------------------------- api_v2 get/set
def test_absent_key_is_the_stated_24h_fallback_never_a_visit(prefs):
    api, _ = prefs
    r = api._ui_prefs_get({"key": KEY})["read"]
    assert r["status"] == "NOT_RECORDED" and r["last_visit_recorded"] is False
    assert r["window_basis"] == "fallback_24h" and r["seen_at"] is None and r["schema"] == "PortfolioLastSeen@v1"


def test_the_server_stamps_the_times_and_a_client_cannot_set_them(prefs):
    api, fake = prefs
    forged = "2000-01-01T00:00:00+00:00"
    out = api._ui_prefs_set({"key": KEY, "value": {"device": "phone", "seen_at": forged, "previous_seen_at": forged}})
    assert out["ok"] is True
    stored = fake.rows[KEY]
    assert stored["seen_at"] != forged and stored["previous_seen_at"] is None and stored["device"] == "phone"
    first = stored["seen_at"]
    assert api._ui_prefs_set({"key": KEY, "value": {"device": "desktop"}})["ok"]
    r = api._ui_prefs_get({"key": KEY})["read"]
    assert r["status"] == "RECORDED" and r["previous_seen_at"] == HL.parse_ts(first).isoformat()


@pytest.mark.parametrize("bad", [None, "phone", {"device": "tablet"}, {}, {"seen_at": "2026-11-12T00:00:00Z"}])
def test_garbage_is_refused_and_nothing_is_stored(prefs, bad):
    api, fake = prefs
    out = api._ui_prefs_set({"key": KEY, "value": bad})
    assert out["ok"] is False and KEY not in fake.rows


def test_a_corrupt_stored_value_is_unknown_with_the_fallback(prefs):
    api, fake = prefs
    fake.rows[KEY] = {"seen_at": "yesterday"}
    r = api._ui_prefs_get({"key": KEY})["read"]
    assert r["status"] == "UNKNOWN" and r["window_basis"] == "fallback_24h" and r["reason"]


def test_home_and_portfolio_windows_are_independent(prefs):
    api, fake = prefs
    assert api._ui_prefs_set({"key": KEY, "value": {"device": "phone"}})["ok"]
    p_seen = fake.rows[KEY]["seen_at"]
    assert api._ui_prefs_set({"key": "home.last_seen", "value": {"device": "phone"}})["ok"]
    assert fake.rows[KEY]["seen_at"] == p_seen and fake.rows[KEY]["previous_seen_at"] is None
    assert api._ui_prefs_get({"key": "home.last_seen"})["read"]["schema"] == "HomeLastSeen@v1"


def test_other_keys_are_untouched(prefs):
    api, fake = prefs
    assert api._ui_prefs_set({"key": "watch.layout", "value": {"anything": [1]}})["ok"]
    out = api._ui_prefs_get({"key": "watch.layout"})
    assert out["value"] == {"anything": [1]} and "read" not in out


# ----------------------------------------------------------------------------- write gate through handle()
def _req(principal, listener="serve_proxy", headers=None):
    import lib.cc_auth as A

    A.set_request_context(listener, headers or {})
    A.set_request_principal(principal)


def _op():
    import lib.cc_auth as A

    logins = list(A.load_config().allowed_logins)
    assert logins, "no allowed login configured"
    return "tailnet:" + logins[0]


def test_no_principal_is_refused_and_nothing_is_stored(prefs):
    api, fake = prefs
    _req("", headers={"Sec-Fetch-Site": "same-origin"})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": KEY, "value": {"device": "phone"}})
    assert s == 403 and b["code"] == "NOT_OPERATOR" and KEY not in fake.rows


def test_operator_without_same_origin_proof_is_csrf_refused(prefs):
    api, fake = prefs
    _req(_op(), headers={})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": KEY, "value": {"device": "phone"}})
    assert s == 403 and b["code"] == "CSRF_REFUSED" and KEY not in fake.rows


def test_padded_key_is_still_gated(prefs):
    api, fake = prefs
    _req("", headers={"Sec-Fetch-Site": "same-origin"})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": " portfolio.last_seen ", "value": {"device": "phone"}})
    assert s == 403 and not fake.rows


def test_operator_same_origin_is_admitted_end_to_end(prefs):
    api, fake = prefs
    _req(_op(), headers={"Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"})
    s, b = api.handle("/api/v2/ui/prefs", "POST", {"key": KEY, "value": {"device": "phone"}})
    assert s == 200, b
    assert fake.rows[KEY]["device"] == "phone" and HL.parse_ts(fake.rows[KEY]["seen_at"]) is not None

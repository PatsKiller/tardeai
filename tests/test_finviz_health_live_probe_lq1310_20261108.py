"""ANCHOR: FINVIZ_HEALTH_LIVE_PROBE_LQ1310_20261108

LQ-20261107-1310 (addendum to LQ-1300). `_finviz_credential_health_live` decided health as

    healthy = bool(ok) and not is_finviz_cookie_failure_text(last_error or "")

so a *stored* `data_source_health.last_error` outvoted a live probe that had just succeeded. Measured
Friday 2026-11-08 18:25 ET: the operator renewed FINVIZ_COOKIE, the live Elite export answered ok,
and the banner stayed up "expired" because the stored text still described the old failure.

Pinned here: the live probe is the verdict (ok → cookie_status ok, no banner, no degraded features)
whatever the stored text says; the stored text may still colour a failure; and a genuinely failing
live probe still raises the banner. Pure: the DB row, the secret read and the validators are stubs —
no DB, no network, no secret is loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

STALE_FAILURE = "finviz cookie expired — screener returned the login page"


@pytest.fixture()
def live(monkeypatch):
    """`api_v2` with the DB row, the key read and both validators replaced."""
    import api_v2
    import secret_validators

    def _db_query(sql, params=(), fetch="one"):
        return {"last_error": STALE_FAILURE, "status": "error", "last_success_at": None}

    monkeypatch.setattr(api_v2, "_db_query", _db_query)
    monkeypatch.setattr(secret_validators, "_key", lambda name: "synthetic-value")
    monkeypatch.setattr(api_v2, "_finviz_cookie_feature_labels", lambda: ["a feature", "b feature"])
    return api_v2, secret_validators


def _probe(monkeypatch, sv, *, cookie_ok: bool, cookie_detail: str, token_ok: bool = True):
    monkeypatch.setattr(sv, "_finviz_cookie", lambda cookie: (cookie_ok, cookie_detail))
    monkeypatch.setattr(sv, "_finviz_token", lambda token: (token_ok, "37 screener rows"))


def test_a_live_ok_probe_beats_a_stale_stored_failure(live, monkeypatch):
    api_v2, sv = live
    _probe(monkeypatch, sv, cookie_ok=True, cookie_detail="37 screener rows")
    out = api_v2._finviz_credential_health_live()
    assert out["status"] == "ok", out
    assert out["cookie_status"] == "ok"
    assert out["show_banner"] is False
    assert out["degraded_features"] == []
    assert out["ok"] is True
    # The stale text is still disclosed — it just does not decide.
    assert out["last_error"] == STALE_FAILURE


def test_a_live_failure_still_raises_the_banner(live, monkeypatch):
    api_v2, sv = live
    _probe(monkeypatch, sv, cookie_ok=False, cookie_detail="screener could not be fetched")
    out = api_v2._finviz_credential_health_live()
    assert out["show_banner"] is True
    assert out["cookie_status"] == "expired"
    assert out["degraded_features"] == ["a feature", "b feature"]


def test_a_dead_cookie_with_a_live_token_is_degraded_not_healthy(live, monkeypatch):
    api_v2, sv = live
    _probe(monkeypatch, sv, cookie_ok=False, cookie_detail="login page", token_ok=True)
    out = api_v2._finviz_credential_health_live()
    assert out["status"] == "token_ok" and out["show_banner"] is True
    assert out["degraded_count"] == 2


def test_a_live_ok_probe_with_no_stored_error_is_unchanged(live, monkeypatch):
    api_v2, sv = live
    monkeypatch.setattr(api_v2, "_db_query", lambda sql, params=(), fetch="one": {"last_error": None})
    _probe(monkeypatch, sv, cookie_ok=True, cookie_detail="37 screener rows")
    out = api_v2._finviz_credential_health_live()
    assert out["status"] == "ok" and out["show_banner"] is False and out["last_error"] is None

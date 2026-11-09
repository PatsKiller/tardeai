"""ANCHOR: OPEND_HEALTH_THROTTLE_LQ1509_20261109 — LQ-20261107-1509.

A moomoo quote rate-limit ("Maximum 60 times per 30 seconds" / high frequency)
must not mark the data plane down. Keep last-good, classify throttled, and skip
further quote calls inside QUOTE_COOLDOWN_S so the probe stays under the shared
OpenD quota. Real auth failures still fail.

Hermetic: injectable quote/port/unit; tmp STATE/FAIL_STREAK via monkeypatch.
No broker, no credentials, no OpenD config changes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 9, 12, 15, tzinfo=timezone.utc)
THROTTLE = ("query rejected: Get Market Snapshot request failed due to high frequency. "
            "Maximum 60 times per 30 seconds.")


def _load(monkeypatch, tmp_path):
    path = ROOT / "scripts" / "moomoo" / "opend_health.py"
    spec = importlib.util.spec_from_file_location("opend_health_lq1509", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Point receipt paths at tmp before exec (module binds STATE at import).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "STATE", tmp_path / "moomoo_opend_health.json")
    monkeypatch.setattr(mod, "FAIL_STREAK", tmp_path / "moomoo_opend_fail_streak.json")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    return mod


def _prior_ok(*, checked_at: datetime) -> dict:
    return {
        "ok": True,
        "checked_at": checked_at.isoformat(),
        "unit": {"name": "trade-ai-lab-moomoo-opend.service", "active": True, "state": "active"},
        "port": {"host": "127.0.0.1", "port": 11111, "open": True},
        "quote": {"ok": True, "detail": "snapshot ok (1 row)"},
        "fail_streak": 0,
        "last_good_at": checked_at.isoformat(),
    }


def test_throttle_keeps_last_good_and_is_ok(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    calls = {"n": 0}

    def quote():
        calls["n"] += 1
        return False, THROTTLE

    prior = _prior_ok(checked_at=NOW - timedelta(seconds=300))
    out = mod.probe(now=NOW, prior=prior, quote_fn=quote,
                    port_fn=lambda: True, unit_fn=lambda: (True, "active"))
    assert out["ok"] is True and out["throttled"] is True
    assert out["fail_streak"] == 0
    assert "throttled" in out["quote"]["detail"]
    assert calls["n"] == 1
    # Must not classify as a finding / down for account_state.
    assert out["ok"] is True


def test_throttle_without_prior_still_not_down(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    out = mod.probe(now=NOW, prior={}, quote_fn=lambda: (False, THROTTLE),
                    port_fn=lambda: True, unit_fn=lambda: (True, "active"))
    assert out["ok"] is True and out["throttled"] is True
    assert "data plane responding" in out["quote"]["detail"]


def test_cooldown_skips_quote_call(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    calls = {"n": 0}

    def quote():
        calls["n"] += 1
        return False, "should not be called"

    prior = _prior_ok(checked_at=NOW - timedelta(seconds=30))
    out = mod.probe(now=NOW, prior=prior, quote_fn=quote,
                    port_fn=lambda: True, unit_fn=lambda: (True, "active"))
    assert calls["n"] == 0
    assert out["ok"] is True and out["throttled"] is True
    assert "skipped quote" in out["quote"]["detail"]


def test_real_auth_failure_still_down(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    out = mod.probe(now=NOW, prior={}, quote_fn=lambda: (False, "query rejected: not logged in"),
                    port_fn=lambda: True, unit_fn=lambda: (True, "active"))
    assert out["ok"] is False and not out.get("throttled")
    assert "not logged in" in out["quote"]["detail"]


def test_is_throttle_detail_matches_opend_wording():
    mod_path = ROOT / "scripts" / "moomoo" / "opend_health.py"
    spec = importlib.util.spec_from_file_location("opend_health_lq1509_det", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._is_throttle_detail(THROTTLE) is True
    assert mod._is_throttle_detail("query rejected: not logged in") is False

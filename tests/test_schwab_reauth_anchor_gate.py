#!/usr/bin/env python3
"""Regression tests for the Schwab reauth urgency gate and the gog binary resolution.

Both guard real incidents from 2026-07-29:

1. `_token_state()` treated "past day-6 since the last true browser login" as an emergency
   and fired a headless login. Once Schwab began answering that login with a phoned-in
   security-code challenge, the login could never succeed — and only a successful login
   writes the audit row that clears the anchor. The lane sent a FAILED alert 4x/day for a
   week while HTTP refresh rotation kept the token perfectly healthy.

2. `email_notifier` invoked bare `gog`, which lives in ~/.local/bin. cron hands jobs a
   minimal PATH, so every cron-launched email died with Errno 2 while Telegram still
   worked — the operator silently lost their second channel.

Pure: no database, no network, no notifications. schwab_token_manager is stubbed so the
gate can be tested without credentials or a live token row.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


HEALTHY = {"degraded": False, "has_token": True, "refresh_valid": True, "days_to_reauth": 7.0}
DEGRADED = {"degraded": True, "has_token": True, "refresh_valid": False, "days_to_reauth": 0.0}
NO_TOKEN = {"degraded": False, "has_token": False, "refresh_valid": False}
LEGACY_PAYLOAD = {"degraded": False, "has_token": True}  # predates refresh_valid


@pytest.fixture
def reauth(monkeypatch):
    """schwab_auto_reauth with a stubbed token manager, so no DB or secrets are needed."""
    stub = types.ModuleType("schwab_token_manager")
    stub.health = lambda *a, **k: dict(HEALTHY)
    stub.reauth_url = lambda *a, **k: {"ok": True, "authorize_url": "https://example.invalid/a",
                                       "step2_command": "exchange-code <REDIRECT>"}
    monkeypatch.setitem(sys.modules, "schwab_token_manager", stub)
    import schwab_auto_reauth as mod
    mod._stub = stub
    return mod


def _state(reauth, health, days_since_login):
    reauth._stub.health = lambda *a, **k: dict(health)
    reauth._last_true_login = lambda: reauth._now() - dt.timedelta(days=days_since_login)
    return reauth._token_state()


class TestUrgencyGate:
    def test_the_incident_case_is_advisory_not_a_browser_login(self, reauth):
        """Healthy rotation past day-6 must NOT trigger a login. This is the whole bug."""
        st = _state(reauth, HEALTHY, 6.5)
        assert st["due_now"] is False
        assert st["advisory_due"] is True

    def test_a_week_of_drift_still_never_escalates_while_healthy(self, reauth):
        st = _state(reauth, HEALTHY, 30)
        assert st["due_now"] is False
        assert st["advisory_due"] is True

    def test_fresh_login_is_neither_due_nor_advisory(self, reauth):
        st = _state(reauth, HEALTHY, 1)
        assert st["due_now"] is False
        assert st["advisory_due"] is False
        assert st["reason"] == "not due"

    @pytest.mark.parametrize("health", [DEGRADED, NO_TOKEN], ids=["degraded", "no_token"])
    def test_a_real_outage_still_escalates_immediately(self, reauth, health):
        """Recovery must not be weakened: broken rotation is due regardless of day count."""
        for days in (1, 6.5, 30):
            st = _state(reauth, health, days)
            assert st["due_now"] is True, f"broken token at day {days} must escalate"
            assert st["advisory_due"] is False

    def test_degraded_outranks_the_advisory_window(self, reauth):
        st = _state(reauth, DEGRADED, 6.5)
        assert (st["due_now"], st["advisory_due"]) == (True, False)

    def test_legacy_health_payload_does_not_read_as_dead(self, reauth):
        """A missing refresh_valid key must not be mistaken for an expired refresh token."""
        st = _state(reauth, LEGACY_PAYLOAD, 6.5)
        assert st["due_now"] is False
        assert st["advisory_due"] is True

    def test_no_recorded_login_never_invents_an_advisory(self, reauth):
        reauth._stub.health = lambda *a, **k: dict(HEALTHY)
        reauth._last_true_login = lambda: None
        st = reauth._token_state()
        assert st["due_now"] is False
        assert st["advisory_due"] is False


class TestAdvisoryNotice:
    def test_it_notifies_once_per_day_then_goes_quiet(self, reauth, tmp_path, monkeypatch):
        sent = []
        monkeypatch.setattr(reauth, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(reauth, "_notify", lambda s, b: sent.append((s, b)))
        st = {"refresh_valid": True, "degraded": False, "last_true_login": "2026-07-22T09:28:48-04:00"}

        for _ in range(4):
            assert reauth._advisory_notice(st) == 0
        assert len(sent) == 1, "the advisory must not repeat within a day"
        assert json.loads((tmp_path / "state.json").read_text())["advisory_notified_day"]

    def test_the_advisory_is_actionable_and_not_alarming(self, reauth, tmp_path, monkeypatch):
        sent = []
        monkeypatch.setattr(reauth, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(reauth, "_notify", lambda s, b: sent.append((s, b)))
        reauth._advisory_notice({"refresh_valid": True, "degraded": False,
                                 "last_true_login": "2026-07-22T09:28:48-04:00"})

        subject, body = sent[0]
        assert "FAILED" not in subject, "a healthy token must not produce a failure alarm"
        assert "not urgent" in subject.lower()
        assert "HEALTHY" in body
        assert "exchange-code" in body, "the operator needs the command that actually fixes it"

    def test_a_broken_reauth_url_still_yields_usable_instructions(self, reauth, tmp_path, monkeypatch):
        sent = []
        monkeypatch.setattr(reauth, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(reauth, "_notify", lambda s, b: sent.append((s, b)))
        reauth._stub.reauth_url = lambda *a, **k: {"ok": False, "reason": "token row missing"}

        reauth._advisory_notice({"refresh_valid": True, "degraded": False, "last_true_login": "x"})
        assert "reauth-url" in sent[0][1]


class TestGogResolution:
    def test_gog_resolves_without_help_from_PATH(self, monkeypatch):
        """cron's PATH excludes ~/.local/bin; resolution must not depend on it."""
        import email_notifier
        monkeypatch.setattr(email_notifier.shutil, "which", lambda _: None)
        fake = Path.home() / ".local" / "bin" / "gog"
        if not fake.is_file():
            pytest.skip("gog is not installed on this host")
        assert email_notifier._gog_bin() == str(fake)

    def test_missing_gog_reports_cleanly_instead_of_raising(self, monkeypatch):
        import email_notifier
        monkeypatch.setattr(email_notifier.shutil, "which", lambda _: None)
        monkeypatch.setattr(email_notifier, "_GOG_FALLBACKS", ())
        assert email_notifier._gog_bin() is None
        monkeypatch.setattr(email_notifier, "_get_keyring_password", lambda: "x")
        assert email_notifier.send_email("s", "b") is False

    def test_send_email_invokes_an_absolute_path(self, monkeypatch):
        import email_notifier
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"], captured["env"] = cmd, kw.get("env", {})
            return types.SimpleNamespace(returncode=0, stderr="", stdout="")

        monkeypatch.setattr(email_notifier, "_get_keyring_password", lambda: "pw")
        monkeypatch.setattr(email_notifier, "_gog_bin", lambda: "/opt/bin/gog")
        monkeypatch.setattr(email_notifier.subprocess, "run", fake_run)

        assert email_notifier.send_email("subj", "body") is True
        assert captured["cmd"][0] == "/opt/bin/gog", "must not invoke a bare 'gog'"
        assert "/opt/bin" in captured["env"]["PATH"]

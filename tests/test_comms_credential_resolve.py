"""Lane C — credential / interdict precedence controls."""
from __future__ import annotations

import logging

import pytest

from scripts.lib import comms_credential_resolve as cr


@pytest.fixture(autouse=True)
def _clean_flags(monkeypatch):
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    monkeypatch.delenv("ENABLE_TELEGRAM", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    # Keep PYTEST_CURRENT_TEST for suite, but resolver respects pytest_counts flag.


def test_interdict_wins_over_env(monkeypatch):
    key = cr._TG_BOT_KEY
    monkeypatch.setenv(key, "should-not-surface")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    # Under pytest, is_interdicted is true anyway; prove class explicitly.
    d = cr.resolve_secret(key, respect_interdict=True, allow_dotenv_fallback=False)
    assert d.decision_class == "INTERDICTED"
    assert d.value == ""


def test_interdict_off_env_wins(monkeypatch):
    key = cr._TG_BOT_KEY
    monkeypatch.setenv(key, "live-value-for-test")
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "0")
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    d = cr.resolve_secret(
        key, respect_interdict=True, allow_dotenv_fallback=False
    )
    # pytest still interdicts by default
    assert d.decision_class == "INTERDICTED"
    d2 = cr.resolve_secret(
        key, respect_interdict=False, allow_dotenv_fallback=False
    )
    assert d2.decision_class == "ENV"
    assert d2.value == "live-value-for-test"


def test_explicit_empty_deny_vs_delenv(monkeypatch):
    key = cr._TG_BOT_KEY
    monkeypatch.setenv(key, "")
    d = cr.resolve_secret(key, respect_interdict=False, allow_dotenv_fallback=False)
    assert d.decision_class == "EXPLICIT_EMPTY"
    assert d.present is True

    monkeypatch.delenv(key, raising=False)
    d2 = cr.resolve_secret(key, respect_interdict=False, allow_dotenv_fallback=False)
    assert d2.decision_class == "ABSENT"
    assert d2.present is False


def test_disabled_enable_telegram(monkeypatch):
    key = cr._TG_BOT_KEY
    monkeypatch.setenv(key, "x")
    monkeypatch.setenv("ENABLE_TELEGRAM", "0")
    assert cr.is_interdicted(pytest_counts=False) is True


def test_decision_log_has_no_value(monkeypatch, caplog):
    key = cr._TG_BOT_KEY
    monkeypatch.setenv(key, "super-secret-value-xyz")
    caplog.set_level(logging.INFO)
    cr.resolve_secret(key, respect_interdict=False, allow_dotenv_fallback=False)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "super-secret-value-xyz" not in joined
    assert "decision_class" in joined or "ENV" in joined

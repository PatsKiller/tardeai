"""Phase 8 — ATOMIC_INBOUND_ENABLED gate on the approved Telegram poller.

Flag OFF keeps feed_telegram_update. Flag ON routes through
process_update_atomically. Default must be OFF.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

poller = importlib.import_module("scripts.run_telegram_callback_poller")


def test_atomic_inbound_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(poller.ATOMIC_INBOUND_FLAG, raising=False)
    assert poller.atomic_inbound_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "YES", "on"])
def test_atomic_inbound_flag_truthy(monkeypatch, val):
    monkeypatch.setenv(poller.ATOMIC_INBOUND_FLAG, val)
    assert poller.atomic_inbound_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "", "no"])
def test_atomic_inbound_flag_falsy(monkeypatch, val):
    monkeypatch.setenv(poller.ATOMIC_INBOUND_FLAG, val)
    assert poller.atomic_inbound_enabled() is False


def test_persist_uses_legacy_when_flag_off(monkeypatch):
    monkeypatch.delenv(poller.ATOMIC_INBOUND_FLAG, raising=False)
    calls = {"legacy": 0, "atomic": 0}

    class _Ok:
        ok = True

    def _legacy(update):
        calls["legacy"] += 1
        return _Ok()

    def _atomic(update, **k):
        calls["atomic"] += 1
        return _Ok()

    monkeypatch.setattr(
        "scripts.lib.inbound_consumption.feed_telegram_update",
        _legacy,
    )
    monkeypatch.setattr(
        "scripts.lib.atomic_inbound.process_update_atomically",
        _atomic,
    )
    # Ensure import path used by helper resolves to patched symbols.
    import scripts.lib.inbound_consumption as ic
    import scripts.lib.atomic_inbound as ai

    monkeypatch.setattr(ic, "feed_telegram_update", _legacy)
    monkeypatch.setattr(ai, "process_update_atomically", _atomic)

    r = poller._persist_inbound_update({"update_id": 1, "message": {"text": "x"}})
    assert r.ok and calls["legacy"] == 1 and calls["atomic"] == 0


def test_persist_uses_atomic_when_flag_on(monkeypatch):
    monkeypatch.setenv(poller.ATOMIC_INBOUND_FLAG, "1")
    calls = {"legacy": 0, "atomic": 0}

    class _Ok:
        ok = True
        outcome = "processed"

    def _legacy(update):
        calls["legacy"] += 1
        return _Ok()

    def _atomic(update, **k):
        calls["atomic"] += 1
        return _Ok()

    import scripts.lib.inbound_consumption as ic
    import scripts.lib.atomic_inbound as ai

    monkeypatch.setattr(ic, "feed_telegram_update", _legacy)
    monkeypatch.setattr(ai, "process_update_atomically", _atomic)

    r = poller._persist_inbound_update({"update_id": 2, "message": {"text": "y"}})
    assert r.ok and calls["atomic"] == 1 and calls["legacy"] == 0

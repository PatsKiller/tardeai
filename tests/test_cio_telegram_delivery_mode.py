"""P1-6 — CIO Telegram delivery-mode classifier.

INTERDICTED != isolation-pass. This is a flag readout only.
Never sends Telegram. Never mutates server env.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def test_pytest_is_interdicted(monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    assert t.under_pytest() is True
    assert t.cio_delivery_mode() == t.MODE_INTERDICTED


def test_interdict_flag(monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setattr(t, "under_pytest", lambda: False)
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    assert t.cio_delivery_mode() == t.MODE_INTERDICTED


def test_telegram_disabled_is_interdicted(monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setattr(t, "under_pytest", lambda: False)
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    monkeypatch.setenv("ENABLE_TELEGRAM", "false")
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    assert t.cio_delivery_mode() == t.MODE_INTERDICTED


def test_prepare_only_without_authorize_p2(monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setattr(t, "under_pytest", lambda: False)
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    assert t.cio_delivery_mode() == t.MODE_PREPARE_ONLY


def test_cio_only_live_when_flags_open(monkeypatch):
    from lib import cio_telegram_transport as t

    monkeypatch.setattr(t, "under_pytest", lambda: False)
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
    assert t.cio_delivery_mode() == t.MODE_CIO_ONLY_LIVE


def test_docstring_separates_interdict_from_isolation_pass():
    from lib import cio_telegram_transport as t

    doc = t.cio_delivery_mode.__doc__ or ""
    assert "INTERDICTED" in doc
    assert "isolation-pass" in doc
    assert "CIO_ONLY_LIVE" in doc
    assert "never mutates env" in doc.lower()

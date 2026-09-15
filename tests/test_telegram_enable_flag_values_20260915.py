"""2026-09-15: ENABLE_TELEGRAM=1 must not silently disable operator alerts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert as ta  # noqa: E402


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " true "])
def test_truthy_values_enable(monkeypatch, value):
    monkeypatch.setattr(ta, "_env", lambda k, d="": value if k == "ENABLE_TELEGRAM" else d)
    assert ta._enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", ""])
def test_falsy_values_disable(monkeypatch, value):
    monkeypatch.setattr(ta, "_env", lambda k, d="": value if k == "ENABLE_TELEGRAM" else d)
    assert ta._enabled() is False

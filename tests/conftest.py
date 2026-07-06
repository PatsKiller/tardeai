"""Shared pytest hooks — block live side effects during unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def _block_options_monitor_live_telegram(monkeypatch):
    """Reconcile/orphan tests call real alert dispatch; never ping the operator bot."""
    from lib.options_pipeline import paper_position_alerts as ppa

    monkeypatch.setattr(ppa, "send_telegram", lambda _message: False)
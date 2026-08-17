"""Pytest configuration for the financial_senses test suite.

Ensures scripts/ and scripts/lib/ are importable and that no financial-senses
test can accidentally hit the network or production DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
LIB = SCRIPTS / "lib"

for _p in (str(SCRIPTS), str(LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _block_live_db_and_network(monkeypatch):
    """Defense-in-depth: any accidental get_connection/urlopen raises in tests.

    Providers are unit-tested with injected fakes; nothing here should ever
    touch a live database or the network.
    """

    def _no_db(*_a, **_k):
        raise RuntimeError("live db_adapter.get_connection blocked in unit tests")

    def _no_net(*_a, **_k):
        raise RuntimeError("live network blocked in unit tests")

    try:
        import db_adapter

        monkeypatch.setattr(db_adapter, "get_connection", _no_db)
    except Exception:
        pass
    try:
        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", _no_net)
    except Exception:
        pass

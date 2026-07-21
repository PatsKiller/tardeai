#!/usr/bin/env python3
"""R5: TradingView ingress stub is disabled by default (503)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_tradingview_ingress_503_when_disabled(monkeypatch):
    monkeypatch.delenv("TRADINGVIEW_INGRESS_ENABLED", raising=False)
    import api_v2
    # avoid full app init side effects where possible
    status, body = api_v2.handle("/api/v2/ingress/tradingview", "POST", {}, {})
    assert status == 503
    assert body.get("enabled") is False

#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from brokers.capability_gate import capability_gate


def test_paper_long_ok():
    r = capability_gate("tradeai_automated", {"side": "buy"})
    assert r["ok"]


def test_ira_short_blocked():
    r = capability_gate("alpaca_ira_live", {"side": "sell_short", "is_short": True})
    assert not r["ok"]
    assert any("cannot short" in b for b in r["blocks"])


def test_taxable_unverified_option_blocked():
    r = capability_gate("alpaca_taxable_live", {"is_option": True})
    assert not r["ok"]

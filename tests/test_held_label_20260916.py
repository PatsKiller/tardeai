#!/usr/bin/env python3
"""B3 (2026-09-16): held / not-held triage label on GO + entry alerts.

The operator should be able to triage at a glance whether a scalp/entry alert is on a name
already in the book. `held` is optional; None (not determined) renders no pill and is never
guessed. The authoritative source is lib.holdings_universe.held_equity_tickers().
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import telegram_rich as tr  # noqa: E402

ARMP = {"symbol": "ARMP", "price": 6.24, "gap_pct": 15.8, "rvol": 70.4, "float_m": 11.6,
        "volume": 3155156, "score": 53, "catalyst": "x"}


def test_held_pill_three_states():
    assert tr.held_pill(None) == []
    assert tr.held_pill(True) == ["🟢 HELD — in book"]
    assert tr.held_pill(False) == ["⚪ NOT HELD"]


def test_go_alert_renders_held_and_not_held():
    held = tr.go_alert(ARMP, tier="GO", passed=["rvol"], held=True).render()["text"]
    assert "HELD — in book" in held
    not_held = tr.go_alert(ARMP, tier="GO", passed=["rvol"], held=False).render()["text"]
    assert "NOT HELD" in not_held


def test_go_alert_unknown_held_renders_no_label():
    text = tr.go_alert(ARMP, tier="GO", passed=["rvol"]).render()["text"]
    assert "HELD" not in text and "NOT HELD" not in text


def test_entry_alert_renders_held():
    item = {"symbol": "AXTI", "state": "READY", "price": 12, "zone_low": 11, "zone_high": 13,
            "stop": 10, "target": 15, "rr": 3, "held": True}
    assert "HELD — in book" in tr.entry_alert(item).render()["text"]


def test_producers_thread_held_from_holdings_universe():
    # GO producer: main() reads held_equity_tickers() and stamps item["held"]; rich_alert passes it.
    src = (ROOT / "scripts" / "screener_go_alerts.py").read_text(encoding="utf-8")
    assert "from lib.holdings_universe import held_equity_tickers" in src
    assert 'held=item.get("held")' in src
    assert 'item["held"] = str(item["row"]["symbol"]).upper() in held_set' in src
    # Entry producer: _held() reads the same universe and stamps _entry_item.
    wl = (ROOT / "scripts" / "watchlist_entry_planner.py").read_text(encoding="utf-8")
    assert "from lib.holdings_universe import held_equity_tickers" in wl
    assert '_entry_item(sym, p, urg, price, held=_held(sym))' in wl

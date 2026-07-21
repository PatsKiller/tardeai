#!/usr/bin/env python3
"""Stop-health alerts state the P/L that would be realized if the stop fills.

A near-trigger on a deep loser (LDOS ~-$413) reads very differently from one
locking a gain (XLI +$576). The alert now carries that number so the operator
decides on the outcome, not just the proximity.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import stop_health_check as shc  # noqa: E402


def test_pl_if_fired_computes_realized_pl():
    # $100 stop, 10 shares, avg cost $150 (basis $1500) -> -$500 realized
    shc._HOLDINGS_BASIS = {("ZZ", "acct"): {"symbol": "ZZ", "account": "acct",
                                            "shares": 10, "cost_basis": 1500}}
    pl = shc._pl_if_fired("ZZ", "acct", 100.0, 10)
    assert pl["pl"] == -500.0
    assert pl["avg_cost"] == 150.0
    assert pl["pct"] == round((100 - 150) / 150 * 100, 1)


def test_pl_if_fired_gain_case():
    shc._HOLDINGS_BASIS = {("ZZ", "a"): {"symbol": "ZZ", "account": "a", "shares": 10, "cost_basis": 800}}
    pl = shc._pl_if_fired("ZZ", "a", 100.0, 10)
    assert pl["pl"] == 200.0 and pl["pct"] > 0


def test_unknown_basis_is_stated_not_guessed():
    shc._HOLDINGS_BASIS = {}
    assert shc._pl_if_fired("NOPE", "a", 100.0, 10) is None
    assert "basis unavailable" in shc._pl_line(None)


def test_pl_line_signs_and_partial_flag():
    assert "−$500" in shc._pl_line({"pl": -500.0, "pct": -25.0, "avg_cost": 150})
    assert "+$200" in shc._pl_line({"pl": 200.0, "pct": 25.0, "avg_cost": 80})
    assert "[partial basis]" in shc._pl_line({"pl": -500.0, "pct": -25.0, "avg_cost": 150, "partial_basis": True})


def test_alert_line_includes_pl():
    src = Path(shc.__file__).read_text()
    assert "_pl_line(_pl)" in src
    assert '"pl_if_fired"' in src   # also on the payload


# ── P/L-if-fired on the stop-management row + journal staleness marker ─────────

def test_stops_row_emits_pl_if_fired():
    import api_v2
    src = Path(api_v2.__file__).read_text()
    assert '"pl_if_fired": (round(unreal_dollars - (qty or 0) * (px - broker_stop)' in src


def test_stop_card_renders_if_fired_chip():
    sm = ROOT / "apps" / "command-center-v3" / "src" / "components" / "StopManagement.tsx"
    src = sm.read_text()
    assert "pl_if_fired" in src and "'If fired'" in src


def test_header_discloses_journal_staleness():
    ms = ROOT / "apps" / "command-center-v3" / "src" / "components" / "MetricStrip.tsx"
    src = ms.read_text()
    assert "journalStaleDays" in src and "STALE" in src and "d old" in src
    # threshold is a real age, not always-on
    assert "journalStaleDays > 7" in src

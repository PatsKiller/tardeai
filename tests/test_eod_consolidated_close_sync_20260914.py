"""eod_consolidated_close_sync: which IEX-derived closes get the consolidated close. Pure, offline."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import eod_consolidated_close_sync as sync  # noqa: E402

COVERS = ["scripts/eod_consolidated_close_sync.py"]


def test_only_disagreeing_quote_derived_closes_are_replaced():
    stored = [("AAPL", "market_quotes", 332.55), ("MNSX", "market_quotes", 24.36),
              ("HPE", "finviz", 55.0), ("XLI", "portfolio_repricer", 7.51)]
    ref = {"AAPL": 332.27, "MNSX": 20.63, "HPE": 62.09, "XLI": 172.37}
    plan = sync.plan_replacements(stored, ref)
    assert [r["symbol"] for r in plan["replace"]] == ["MNSX"]
    assert plan["unchanged"] == 1
    # other sources are not this lane's to rewrite
    assert all(r["symbol"] not in ("HPE", "XLI") for r in plan["replace"] + plan["held_back"])


def test_a_huge_disagreement_is_held_back_for_quarantine_not_synced():
    plan = sync.plan_replacements([("ADTX", "market_quotes", 0.0093), ("ODD", "market_quotes", 3.38)],
                                  {"ADTX": 0.0070, "ODD": 0.4531})
    assert [r["symbol"] for r in plan["replace"]] == ["ADTX"]
    assert [r["symbol"] for r in plan["held_back"]] == ["ODD"]


def test_no_reference_is_counted_and_left_alone():
    plan = sync.plan_replacements([("DELIST", "market_quotes", 1.0)], {"DELIST": None})
    assert plan["no_reference"] == 1 and plan["replace"] == [] and plan["held_back"] == []


def test_default_session_is_today_after_the_close_and_the_last_weekday_before():
    after_close_mon = datetime(2026, 9, 14, 21, 30, tzinfo=timezone.utc)   # 17:30 ET Monday
    before_close_mon = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)   # 09:00 ET Monday
    saturday = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
    assert sync.default_session(after_close_mon).isoformat() == "2026-09-14"
    assert sync.default_session(before_close_mon).isoformat() == "2026-09-11"
    assert sync.default_session(saturday).isoformat() == "2026-09-11"

"""Screener GO alerts: Trade-AI scalp criteria decide, one alert per symbol per session. Offline."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import screener_go_alerts as g  # noqa: E402
from lib.scalp_go_criteria import FALLBACK  # noqa: E402

COVERS = ["scripts/screener_go_alerts.py"]

GOOD = {"symbol": "ELMT", "run_label": "0930", "scanned_at": "2026-09-14T13:31:00", "score": 49, "grade": "A+",
        "decision": "GO", "rvol": 8.2, "price": 6.4, "change_pct": 12.0, "gap_pct": 9.5, "float_m": 12.0,
        "volume": 3_400_000, "catalyst": "FDA clearance", "catalyst_verified": True, "disqualified": False,
        "source": "social_scalp"}


def test_a_row_meeting_every_criterion_alerts_once():
    plan = g.pick_alerts([GOOD], sent=set(), session="2026-09-14", criteria=FALLBACK)
    assert [a["row"]["symbol"] for a in plan["alert"]] == ["ELMT"] and plan["alert"][0]["tier"] == "A+"
    again = g.pick_alerts([GOOD], sent={"2026-09-14:ELMT"}, session="2026-09-14", criteria=FALLBACK)
    assert again["alert"] == [] and again["already_sent"] == ["ELMT"]


def test_unverified_catalyst_or_big_float_is_withheld_with_the_reason():
    rows = [dict(GOOD, symbol="NOCAT", catalyst_verified=False), dict(GOOD, symbol="BIGF", float_m=150.0)]
    plan = g.pick_alerts(rows, sent=set(), session="2026-09-14", criteria=FALLBACK)
    reasons = {w["symbol"]: w["failed"] for w in plan["withheld"]}
    assert plan["alert"] == [] and "catalyst" in reasons["NOCAT"] and "float" in reasons["BIGF"]


def test_newest_scan_per_symbol_decides():
    old = dict(GOOD, scanned_at="2026-09-14T13:01:00", rvol=2.0)
    plan = g.pick_alerts([old, GOOD], sent=set(), session="2026-09-14", criteria=FALLBACK)
    assert len(plan["alert"]) == 1


def test_alert_text_names_the_criteria_and_stays_advisory():
    item = g.pick_alerts([GOOD], sent=set(), session="2026-09-14", criteria=FALLBACK)["alert"][0]
    text = g.format_alert(item)
    assert text.startswith("🔥 A+ ELMT — momentum scalp setup (social + screener)")
    assert "Meets Trade-AI scalp criteria:" in text and "catalyst" in text
    assert text.rstrip().endswith("READ_ONLY_ADVISORY") and "no order, size or stop" in text

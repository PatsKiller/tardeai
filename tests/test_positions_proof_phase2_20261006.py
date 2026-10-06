"""Positions plan phase 2 — the 10-trading-day proof grader (operator 2026-10-06: "start phase 2").

Gate (docs/architecture/POSITIONS_SOURCE_OF_TRUTH_PLAN_2026-10-05.md): 10 consecutive trading days with every
sync run complete, the heartbeat never late (30 min, operator-approved), and zero unexplained differences.
Fakes only: no database, no broker, no Telegram.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import positions_proof_daily as pd  # noqa: E402

ET = ZoneInfo("America/New_York")
DAY = date(2026, 10, 7)
CFG = {"stale_after_minutes_market": 30}


def _runs(minutes, status="complete"):
    base = datetime(2026, 10, 7, 9, 24, tzinfo=ET)
    return [{"run_id": i, "status": status, "promoted": status == "complete",
             "finished_at": base + timedelta(minutes=m)} for i, m in enumerate(minutes)]


EVERY_15 = list(range(0, 7 * 60 + 1, 15))          # 09:24 .. 16:24, the cron cadence


def test_a_clean_day_passes():
    row = pd.grade_day(DAY, _runs(EVERY_15), [], [], CFG)
    assert row["pass"] and row["checks"]["heartbeat"]["max_gap_s"] <= 15 * 60


def test_a_missed_hour_fails_the_heartbeat():
    mins = [m for m in EVERY_15 if not 120 <= m <= 180]
    row = pd.grade_day(DAY, _runs(mins), [], [], CFG)
    assert not row["pass"] and not row["checks"]["heartbeat"]["ok"]


def test_a_partial_run_fails_the_day():
    runs = _runs(EVERY_15) + [{"run_id": 99, "status": "partial", "promoted": False,
                               "finished_at": datetime(2026, 10, 7, 12, 0, tzinfo=ET)}]
    row = pd.grade_day(DAY, runs, [], [], CFG)
    assert not row["checks"]["runs"]["ok"] and row["checks"]["runs"]["not_complete"][0]["status"] == "partial"


def test_any_difference_fails_and_known_lot_gaps_do_not():
    lots = [{"account_key": "schwab_rollover_ira", "symbol": "SCHG", "issues": ["ledger lots qty 12000"]}]
    assert pd.grade_day(DAY, _runs(EVERY_15), [], lots, CFG)["pass"]
    row = pd.grade_day(DAY, _runs(EVERY_15), [{"account_key": "a", "symbol": "X", "issue": "qty"}], lots, CFG)
    assert not row["pass"] and row["checks"]["diff"]["count"] == 1


def test_day_counter_is_consecutive_passes_and_a_failure_resets_it():
    start = date(2026, 10, 7)
    led = [{"date": "2026-10-07", "pass": True}, {"date": "2026-10-08", "pass": True},
           {"date": "2026-10-09", "pass": False}, {"date": "2026-10-12", "pass": True}]
    assert pd.proof_day_number(led, date(2026, 10, 8), start) == 2
    assert pd.proof_day_number(led, date(2026, 10, 9), start) == 0
    assert pd.proof_day_number(led, date(2026, 10, 12), start) == 1


def test_one_line_is_short_and_names_the_next_feature():
    row = pd.grade_day(DAY, _runs(EVERY_15), [], [], CFG)
    line = pd.one_line(row, 1, 10)
    assert line.startswith("Positions proof day 1 of 10 PASS") and "Read-time pricing" in line and len(line) < 300


def test_proof_config_and_approved_threshold():
    cfg = pd.load_proof_config()
    assert cfg["start"] == "2026-10-07" and int(cfg["days"]) == 10 and cfg["stale_after_minutes_market"] == 30


def test_grader_is_read_only():
    src = (ROOT / "scripts" / "positions_proof_daily.py").read_text()
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "protected_holdings_write", "place_order"):
        assert verb not in src

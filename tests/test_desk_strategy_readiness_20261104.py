"""STRATEGY_READINESS_20261104 — FQ-063: a file full of measured values rendered as "not on file".

Measured live 2026-11-04 on the served release: `data/paper_trading/paper_trade_statistics_latest.json` carries
`readiness.level = P1_EARLY_SIGNAL`, `readiness.closed_usable = 158`, `performance.win_rate = 49.4`, while
`/api/v2/desks/strategy` served Phase / Closed trades / Win rate / Next gate all as "not on file". The writer had
moved to a nested schema and `desks_a.strategy_payload` still read the flat one.

These tests build the panel from fixtures: the nested schema must be read, the older flat schema must still work,
and a genuinely absent file must say what the row is waiting for rather than a bare dash.

Control — which assertion proves the fix (lead ruling 2026-11-05: a control that is not read correctly is not
evidence). Re-run by putting origin/main's projection back and running this file unchanged:

    cp scripts/lib/desks_a.py /tmp/head.py
    git show origin/main:scripts/lib/desks_a.py > scripts/lib/desks_a.py
    python3 -m pytest tests/test_desk_strategy_readiness_20261104.py -q
    cp /tmp/head.py scripts/lib/desks_a.py

Measured result: **3 failed, 1 passed**, and the three failures are assertion failures on the values the panel
prints (`'not on file' != 'P1 EARLY SIGNAL'`, `'not on file'.startswith('4,000 closed trades')`, and the gate
ladder), not import or collection errors:

* ``test_the_nested_schema_is_read_not_declared_missing`` — flips (this is the FQ-063 defect itself)
* ``test_gate_progresses_once_the_first_target_is_met`` — flips
* ``test_a_missing_file_says_so_and_says_what_is_needed`` — flips
* ``test_backward_compatibility_control_a_pre_change_flat_file_still_reads`` — **passes on both trees by
  design**: it pins the flat-schema fallback, which must survive the change. It is an invariant control, not
  proof of the fix, and its name says so.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import desks_a  # noqa: E402

NESTED = {
    "timestamp": "2026-11-04T12:05:35Z",
    "counts": {"closed_trades": 158},
    "performance": {"win_rate": 49.4, "net_pnl": 93.23},
    "readiness": {"level": "P1_EARLY_SIGNAL", "closed_usable": 158, "distance_to_2000": 1842},
}
FLAT = {"level": "P2_EARLY_SIGNAL", "closed_usable": 120, "win_rate": 41.0}


def _write(tmp_path: Path, payload: dict | None) -> Path:
    p = tmp_path / "data" / "paper_trading" / "paper_trade_statistics_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        p.write_text(json.dumps(payload))
    return tmp_path


def _readiness(tmp_path: Path) -> dict[str, str]:
    out = desks_a.strategy_payload(root=tmp_path, db_query=lambda *a, **k: None)
    for tab in out["tabs"].values():
        for panel in tab["panels"]:
            labels = [r.get("label") for r in panel["rows"]]
            if "Phase" in labels:
                return {r["label"]: r["value"] for r in panel["rows"]}
    raise AssertionError("no paper-trade readiness panel in the projection")


def test_the_nested_schema_is_read_not_declared_missing(tmp_path):
    rows = _readiness(_write(tmp_path, NESTED))
    assert rows["Phase"] == "P1 EARLY SIGNAL"
    assert rows["Closed trades"] == "158 / 2,000"
    assert rows["Win rate (all closed)"] == "49.4%"
    assert rows["Next gate"].startswith("2,000 closed trades")


def test_backward_compatibility_control_a_pre_change_flat_file_still_reads(tmp_path):
    """Invariant control: passes on origin/main AND on this head. It proves the fallback, never the fix."""
    rows = _readiness(_write(tmp_path, FLAT))
    assert rows["Phase"] == "P2 EARLY SIGNAL"
    assert rows["Closed trades"] == "120 / 2,000"
    assert rows["Win rate (all closed)"] == "41.0%"


def test_gate_progresses_once_the_first_target_is_met(tmp_path):
    rows = _readiness(_write(tmp_path, {**NESTED, "readiness": {"level": "P4", "closed_usable": 2100}}))
    assert rows["Next gate"].startswith("4,000 closed trades")


def test_a_missing_file_says_so_and_says_what_is_needed(tmp_path):
    rows = _readiness(_write(tmp_path, None))
    assert rows["Phase"] == "not on file" and rows["Closed trades"] == "not on file"
    assert "2,000 closed trades" in rows["Next gate"] and "4,000" in rows["Next gate"], (
        "a missing readiness file must still explain the gate ladder, not show a bare dash")


def test_the_leaderboard_marks_measured_figures_so_the_board_cannot_break_them(tmp_path):
    """FQ-064: the served /strategy leaderboard is the DeskPanels projection, not the classic table.

    A row whose text carries measured figures ("win 49.4% · 158 trades") is marked ``nowrap`` so the board
    breaks it only at whitespace; on a phone it could otherwise split a number in two. The prose rows keep
    wrapping, so this is a per-row mark and never a global style change.
    """
    out = desks_a.strategy_payload(
        root=_write(tmp_path, NESTED), db_query=lambda *a, **k: None,
        leaderboard={"leaderboard": [
            {"strategy_id": "core_growth_compounder", "rank": 1,
             "live": {"win_rate": 49.4, "n": 158, "total_pnl": 93.23}},
        ]})
    all_rows = [r for tab in out["tabs"].values() for panel in tab["panels"] for r in panel["rows"]
                if str(r.get("id", "")).startswith("lb-")]
    by_id = {r["id"]: r for r in all_rows}
    assert "lb-core_growth_compounder" in by_id, f"no leaderboard row in the projection: {sorted(by_id)}"
    assert by_id["lb-core_growth_compounder"].get("nowrap") is True, (
        "the measured leaderboard row must be marked nowrap, or a phone splits 'win 49.4%' inside the number")
    assert "nowrap" not in by_id["lb-sort"], "a prose row must keep wrapping"
    readiness = _readiness(_write(tmp_path, NESTED))
    assert all(readiness[k] for k in ("Closed trades", "Win rate (all closed)"))

"""STRATEGY_READINESS_20261104 — FQ-063: a file full of measured values rendered as "not on file".

Measured live 2026-11-04 on the served release: `data/paper_trading/paper_trade_statistics_latest.json` carries
`readiness.level = P1_EARLY_SIGNAL`, `readiness.closed_usable = 158`, `performance.win_rate = 49.4`, while
`/api/v2/desks/strategy` served Phase / Closed trades / Win rate / Next gate all as "not on file". The writer had
moved to a nested schema and `desks_a.strategy_payload` still read the flat one.

These tests build the panel from fixtures: the nested schema must be read, the older flat schema must still work,
and a genuinely absent file must say what the row is waiting for rather than a bare dash.
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


def test_a_pre_change_flat_file_still_reads(tmp_path):
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

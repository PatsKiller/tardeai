"""Hermetic checks for bridge pin soak recorder."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts" / "record_bridge_pin_soak.py"


def _load():
    spec = importlib.util.spec_from_file_location("record_bridge_pin_soak", SPEC)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_consecutive_matches_counts_trailing_only():
    m = _load()
    rows = [
        {"pins_match": True},
        {"pins_match": False},
        {"pins_match": True},
        {"pins_match": True},
    ]
    assert m.consecutive_matches(rows) == 2


def test_status_report_not_ready_below_need(tmp_path):
    m = _load()
    p = tmp_path / "soak.jsonl"
    p.write_text(
        json.dumps({"pins_match": True, "as_of": "t1"}) + "\n",
        encoding="utf-8",
    )
    rows = m.read_rows(p)
    text = m.status_report(rows, need=3)
    assert "streak=1" in text
    assert "soak_ready=NO" in text


def test_schema_constant():
    m = _load()
    assert m.SCHEMA == "BridgePinSoakObservation@v1"

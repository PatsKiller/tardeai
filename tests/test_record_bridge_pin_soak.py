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


def test_write_targets_env_override_is_single(tmp_path, monkeypatch):
    m = _load()
    only = tmp_path / "only.jsonl"
    monkeypatch.setenv("TRADEAI_BRIDGE_PIN_SOAK", str(only))
    assert m.write_targets() == [only]


def test_write_targets_includes_local_state(monkeypatch, tmp_path):
    m = _load()
    monkeypatch.delenv("TRADEAI_BRIDGE_PIN_SOAK", raising=False)
    local = tmp_path / "local_state" / "bridge_pin_soak.jsonl"
    monkeypatch.setattr(m, "_local_ledger", lambda: local)
    monkeypatch.setattr(
        m,
        "_persistent_ledger",
        lambda: tmp_path / "missing-persistent" / "bridge_pin_soak.jsonl",
    )
    # no checkout runtime dir from cwd — still must include local
    targets = m.write_targets()
    assert local in targets


def test_append_obs_creates_parent(tmp_path):
    m = _load()
    path = tmp_path / "nested" / "soak.jsonl"
    m._append_obs(path, {"pins_match": True, "as_of": "t"})
    assert path.is_file()
    rows = m.read_rows(path)
    assert rows[0]["pins_match"] is True

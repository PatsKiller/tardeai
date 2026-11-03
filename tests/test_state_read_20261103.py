"""Damaged state files are 'no snapshot', never a crash (2026-11-03).

Hermetic: tmp files only; no DB, no network, no live store.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import state_read as sr  # noqa: E402


def test_states_are_distinguished(tmp_path):
    p = tmp_path / "x.json"
    assert sr.read_json_state(p) == (None, "absent")
    p.write_bytes(b"")
    assert sr.read_json_state(p) == (None, "empty")
    p.write_text("   \n")
    assert sr.read_json_state(p) == (None, "empty")
    p.write_text("{not json")
    assert sr.read_json_state(p) == (None, "unparseable")
    p.write_text("[1,2,3]")
    assert sr.read_json_state(p) == (None, "not_object")
    p.write_text('{"holdings": []}')
    doc, state = sr.read_json_state(p)
    assert state == "ok" and doc == {"holdings": []}


def test_read_json_object_never_raises_on_damage(tmp_path):
    p = tmp_path / "x.json"
    for raw in (b"", b"{not json", b"[1]", b"null"):
        p.write_bytes(raw)
        assert sr.read_json_object(p, default={}) == {}
    assert sr.read_json_object(tmp_path / "missing.json", default={"a": 1}) == {"a": 1}
    p.write_text('{"a": 1}')
    assert sr.read_json_object(p, default={}) == {"a": 1}


def test_job_runner_holdings_read_survives_a_zero_byte_store(tmp_path):
    # The exact expression that raised 18 times on 2026-11-03 (now via the helper).
    state = tmp_path / "holdings.json"
    state.write_bytes(b"")
    holdings = sr.read_json_object(state, default={})
    assert holdings == {}
    assert [h for h in holdings.get("holdings", [])] == []


def test_social_ingest_symbols_on_zero_byte_store(tmp_path, monkeypatch):
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_bytes(b"")
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si._get_holdings_symbols() == []          # no crash, no invented symbols


def test_social_ingest_symbols_filters_cash_and_funds(tmp_path, monkeypatch):
    import social_ingest as si

    state_dir = tmp_path / "data" / "portfolios" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "holdings.json").write_text(json.dumps({"holdings": [
        {"symbol": "AAA"},
        {"symbol": "CASH", "is_cash": True},
        {"symbol": "FUNDX", "is_fund": True},
        {"symbol": ""},
    ]}))
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    assert si._get_holdings_symbols() == ["AAA"]

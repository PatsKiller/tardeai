"""CADI Phase 1–3 hermetic tests — SymbolDecisionObject, router, shadow, ledger."""
from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.lib.cross_asset.assemble import assemble_symbol_decision
from scripts.lib.cross_asset.events import maybe_reevaluate_on_research_complete, shadow_enabled
from scripts.lib.cross_asset.expression_router import route_expressions, SIGNAL_EXPRESSIONS
from scripts.lib.cross_asset.missed_opportunity_ledger import record_if_missed
from scripts.lib.cross_asset.persistence import append_symbol_decision, load_latest_by_symbol
from scripts.lib.cross_asset.symbol_decision_object import (
    SCHEMA,
    new_symbol_decision,
    validate_symbol_decision,
)


def test_new_has_required_groups():
    obj = new_symbol_decision("NFLX")
    assert obj["schema"] == SCHEMA
    assert obj["identity"]["symbol"] == "NFLX"
    v = validate_symbol_decision(obj)
    assert v["ok"], v


def test_validate_rejects_missing_symbol():
    obj = new_symbol_decision("AMD")
    obj["identity"]["symbol"] = ""
    v = validate_symbol_decision(obj)
    assert not v["ok"]
    assert any("symbol" in e for e in v["errors"])


def test_persist_roundtrip(tmp_path: Path):
    ledger = tmp_path / "symbol_decisions.jsonl"
    obj = new_symbol_decision("NFLX", subject_guid="guid-test")
    wr = append_symbol_decision(obj, path=ledger)
    assert wr["ok"], wr
    # corrupt line should not break load
    with ledger.open("a") as fh:
        fh.write("{not-json\n")
    latest = load_latest_by_symbol("NFLX", path=ledger)
    assert latest and latest["identity"]["symbol"] == "NFLX"


def test_assemble_links_hermes_result():
    hermes = {
        "result_id": "rr_4a877da8499b",
        "research_id": "res_bca00610a37c",
        "status": "completed",
        "summary": "NFLX de-rated; debate is monetization.",
        "subject_guid": "ecb5ba89-test",
        "confidence": 0.55,
        "findings": [{"id": "f1", "kind": "regime", "text": "risk_off"}],
    }
    obj = assemble_symbol_decision(
        "NFLX",
        hermes_result=hermes,
        provenance={"subject_guid": "ecb5ba89-test"},
        signal={"kind": "buy", "lane": "test"},
        holdings_row={"shares": 0},
        options_packet={"schema": "OptionsDecisionPacket@v2", "cio": {"status": "unreviewed"}},
        prefer_shared_spine=False,
    )
    assert obj["research_state"]["result_id"] == "rr_4a877da8499b"
    assert obj["identity"]["subject_guid"] == "ecb5ba89-test"
    assert obj["equity_thesis"]["state"] == "POPULATED"
    assert obj["options_state"]["packets"][0]["schema"] == "OptionsDecisionPacket@v2"
    assert obj["expression_comparison"]["ranked"]
    assert validate_symbol_decision(obj)["ok"]


def test_buy_hold_reentry_sell_routing():
    buy = route_expressions("buy", position_state={"held_shares": 0})
    assert {c["family"] for c in buy} == set(SIGNAL_EXPRESSIONS["buy"])

    hold = route_expressions("hold", position_state={"held_shares": 50, "coverage_100": False})
    families = {c["family"]: c for c in hold}
    assert "covered_call" in families
    assert "fewer_than_100_shares" in families["covered_call"]["blocks"]
    assert families["collar"]["status"] == "evaluable_shadow"

    reentry = route_expressions("reentry", position_state={})
    assert {c["family"] for c in reentry} == set(SIGNAL_EXPRESSIONS["reentry"])

    sell = route_expressions("sell", position_state={"held_shares": 100, "coverage_100": True})
    sf = {c["family"]: c for c in sell}
    assert "sell_shares" in sf
    assert sf["collar"]["status"] == "evaluable_shadow"


def test_event_hook_flag_off(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)
    # The shared SecurityResearchSpine is independently default-on; this test
    # covers the SymbolDecisionObject shadow flag, so disable the spine writer
    # explicitly to keep the no-shadow assertion hermetic.
    monkeypatch.setenv("CROSS_ASSET_SPINE", "0")
    assert not shadow_enabled()
    ledger = tmp_path / "s.jsonl"
    r = maybe_reevaluate_on_research_complete(
        "NFLX",
        hermes_result={"result_id": "rr_x", "summary": "x", "status": "completed"},
        ledger_path=ledger,
    )
    assert r["skipped"] is True
    assert not ledger.exists()


def test_event_hook_flag_on(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CROSS_ASSET_SHADOW", "1")
    ledger = tmp_path / "s.jsonl"
    r = maybe_reevaluate_on_research_complete(
        "NFLX",
        hermes_result={"result_id": "rr_x", "summary": "x", "status": "completed"},
        ledger_path=ledger,
        root=tmp_path,
    )
    assert r["skipped"] is False
    assert r["write"]["ok"]
    assert ledger.exists()


def test_missed_opportunity_ledger(tmp_path: Path):
    obj = assemble_symbol_decision("NFLX", signal={"kind": "buy"}, route=True)
    path = tmp_path / "miss.jsonl"
    # choose something other than top
    top = obj["expression_comparison"]["top_family"]
    other = "long_call" if top != "long_call" else "cash_secured_put"
    r = record_if_missed(obj, chosen_family=other, path=path)
    assert r["ok"] and r["recorded"]
    row = json.loads(path.read_text().strip().splitlines()[-1])
    assert row["chosen_family"] == other
    assert row["top_shadow_family"] == top

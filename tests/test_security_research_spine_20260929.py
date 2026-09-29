"""SecurityResearchSpine — CIO-owned shared research across silos."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cross_asset.assemble import assemble_symbol_decision
from scripts.lib.options_research_universe import merge_research_rows
from scripts.lib.cross_asset.security_research_spine import (
    CONSUMER_SILOS,
    empty_spine,
    spine_rows_for_options_universe,
    upsert_from_hermes,
    validate_spine,
    view_for_silo,
)


def test_spine_owner_is_cio(tmp_path: Path):
    sp = empty_spine("NFLX", subject_guid="guid-1")
    assert sp["owner"] == "cio"
    assert validate_spine(sp)["ok"]
    assert "options_desk" in CONSUMER_SILOS
    assert "reentry" in CONSUMER_SILOS
    assert "watchlist" in CONSUMER_SILOS
    assert "holdings" in CONSUMER_SILOS


def test_hermes_upsert_readable_by_every_silo(tmp_path: Path):
    ledger = tmp_path / "spine.jsonl"
    hermes = {
        "result_id": "rr_shared",
        "research_id": "res_shared",
        "status": "completed",
        "summary": "Shared NFLX thesis for all silos.",
        "subject_guid": "guid-nflx",
        "confidence": 0.6,
    }
    wr = upsert_from_hermes("NFLX", hermes, path=ledger)
    assert wr["ok"]
    for silo in ("options_desk", "watchlist", "reentry", "holdings", "cio"):
        v = view_for_silo("NFLX", silo, path=ledger)
        assert v["found"] is True
        assert v["thesis"]["summary"].startswith("Shared NFLX")
        assert v["transparency"]["shared_across_silos"] is True


def test_options_universe_consumes_spine_not_private_fork(tmp_path: Path):
    ledger = tmp_path / "spine.jsonl"
    upsert_from_hermes(
        "NFLX",
        {
            "result_id": "rr_1",
            "research_id": "res_1",
            "status": "completed",
            "summary": "One thesis",
            "subject_guid": "g1",
        },
        path=ledger,
    )
    from scripts.lib.cross_asset.security_research_spine import load_latest

    sp = load_latest("NFLX", path=ledger)
    rows = spine_rows_for_options_universe([sp])
    # Pretend watchlist also emits a thin row — merge must keep cio_research lane
    merged = merge_research_rows(rows + [{"symbol": "NFLX", "source": "watchlist", "research_status": "research_required"}])
    assert len(merged) == 1
    assert "cio_research" in merged[0]["source_lanes"]
    assert merged[0]["research_status"] == "researched"
    assert merged[0]["summary"] == "One thesis"


def test_assemble_prefers_shared_spine(tmp_path: Path):
    ledger = tmp_path / "spine.jsonl"
    upsert_from_hermes(
        "NFLX",
        {
            "result_id": "rr_pref",
            "research_id": "res_pref",
            "status": "completed",
            "summary": "Spine thesis wins",
            "subject_guid": "g2",
        },
        path=ledger,
    )
    obj = assemble_symbol_decision(
        "NFLX",
        signal={"kind": "buy"},
        spine_path=ledger,
        prefer_shared_spine=True,
    )
    assert obj["equity_thesis"]["summary"].startswith("Spine thesis")
    assert "security_research_spine" in (obj["cio_state"].get("product_refs") or [])

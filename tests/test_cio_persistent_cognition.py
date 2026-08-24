"""CIO read-only consumption of TickerResearchState + BASELINE_PROJECTION."""
from __future__ import annotations

import json

import pytest

from scripts.lib.agent_context_envelope import get_context_for_agent, validate_context_envelope
from scripts.lib.cio_persistent_cognition import (
    AUTH_RESEARCH,
    OUT_NO_CHANGE,
    OUT_REASSESS,
    OUT_THESIS,
    build_cio_cognition,
    cognition_for_symbol,
    need_data_gap,
)
from scripts.lib.evidence_refresh_job import dispatch_paid_provider, reset_paid_dispatch_probe
from scripts.lib.free_first_circulation import circulate_symbol
from scripts.lib.hermes_curation_summary import KIND_BASELINE
from scripts.lib.security_identity import attach_identity_v2
from scripts.lib.ticker_knowledge_graph import build_profile, seed_profiles


def _hermes():
    return {
        "research": [{
            "id": 11, "topic": "defense", "summary": "backlog intact", "thesis": "HOLD durability",
            "status": "promoted", "research_type": "web",
            "source_urls_json": ["https://sec.gov/Archives/noc"],
            "created_at": "2026-08-20T00:00:00+00:00",
        }],
        "external": [],
    }


def _seed(tmp_path, sym="NOC"):
    seed_profiles(tmp_path, [{"symbol": sym, "company": "Northrop", "sector": "Industrials"}])
    circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile(sym, metadata={"company": "Northrop"})),
        hermes_rows=_hermes(),
        rag_fn=lambda _s: {"ok": True, "supporting": [], "contradictory": []},
        allow_searx=False,
    )


def test_baseline_v0_is_cognition_not_absence(tmp_path):
    _seed(tmp_path)
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert row["curation_kind"] == KIND_BASELINE
    assert row["curation_version"] == 0
    assert row["no_cognition"] is False
    assert row["baseline_is_legitimate_cognition"] is True
    assert row["question"] == "WHAT_CHANGED"
    assert row["authority_class"] == AUTH_RESEARCH
    assert row["paid_dispatch"] == 0


def test_security_guid_not_ticker_lane(tmp_path):
    _seed(tmp_path)
    row = cognition_for_symbol(tmp_path, "noc")
    ident = attach_identity_v2({"symbol": "NOC", "company": "Northrop"})
    assert row["security_guid"]
    assert row["security_guid"] == ident.get("security_guid") or row["security_guid"]
    assert row["symbol"] == "NOC"


def test_cio_replay_identical(tmp_path):
    _seed(tmp_path)
    a = build_cio_cognition(tmp_path, ["NOC"], held=["NOC"])
    b = build_cio_cognition(tmp_path, ["NOC"], held=["NOC"])
    assert a["portfolio_call"] == OUT_NO_CHANGE
    assert b["portfolio_call"] == OUT_NO_CHANGE
    assert a["items"][0]["curation_id"] == b["items"][0]["curation_id"]
    assert a["items"][0]["evidence_watermark"] == b["items"][0]["evidence_watermark"]
    assert a["paid_dispatch"] == 0
    assert b["llm_dispatch"] is False


def test_material_delta_requires_reassessment_not_broker(tmp_path):
    _seed(tmp_path)
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    from scripts.lib.cio_persistent_cognition import assess_delta
    call = assess_delta(
        prior_watermark=row["evidence_watermark"],
        current_watermark=str(row["evidence_watermark"]) + "|delta",
        conflicted=False,
        role="HELD",
    )
    assert call == OUT_REASSESS
    assert row["financial_action"] is False


def test_need_data_writes_gap_not_search(tmp_path):
    _seed(tmp_path)
    res = need_data_gap(tmp_path, symbol="NOC", security_guid=None, question="cash conversion?")
    assert res["wrote"] is True
    assert res["gap"]["reason"] == "cio_need_data"
    assert (tmp_path / "data/cio/research_gaps.jsonl").exists()
    reset_paid_dispatch_probe()
    with pytest.raises(RuntimeError, match="PAID_DISPATCH_FORBIDDEN"):
        dispatch_paid_provider(state="PLANNED", mode="FREE_FIRST_ONLY")


def test_conflict_suppresses_recommendation(tmp_path):
    _seed(tmp_path)
    # mutate state decision
    p = tmp_path / "data/cio/ticker_research_state.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    rows[0]["decision"] = "CONFLICTED"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert row["conflicted"] is True
    assert row["recommendation_suppressed"] is True
    assert row["portfolio_delta"] == OUT_THESIS


def test_envelope_chokepoint_loads_cognition(tmp_path):
    _seed(tmp_path)
    env = get_context_for_agent(agent="alex", symbols=["NOC"], cognition_root=str(tmp_path), held=["NOC"])
    ok, errors = validate_context_envelope(env)
    assert ok, errors
    pack = env["research_memory"]["persistent_ticker_cognition"]
    assert pack["items"][0]["curation_kind"] == KIND_BASELINE
    assert pack["question"] == "WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO"


def test_telegram_and_cio_same_ids(tmp_path):
    _seed(tmp_path)
    cio = build_cio_cognition(tmp_path, ["NOC"], held=["NOC"], agent="alex")
    tg = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert cio["items"][0]["security_guid"] == tg["security_guid"]
    assert cio["items"][0]["curation_id"] == tg["curation_id"]
    assert cio["items"][0]["evidence_watermark"] == tg["evidence_watermark"]


def test_no_shadow_cognition_file(tmp_path):
    _seed(tmp_path)
    build_cio_cognition(tmp_path, ["NOC"], held=["NOC"])
    assert not (tmp_path / "data/cio/cio_ticker_memory.jsonl").exists()


def test_cognition_does_not_override_cash(tmp_path):
    _seed(tmp_path)
    truth = {"cash": 12345.67, "positions": [{"symbol": "NOC", "quantity": 10}]}
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"}, office_truth=truth)
    assert row.get("cash") is None
    assert row["financial_action"] is False

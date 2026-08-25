"""R10.8 — natural CIO DecisionPayload carries bounded cognition refs."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.agent_decision_payload import (
    PAYLOAD_SCHEMA,
    emit_payloads_for_decisions,
    enrich_payload_with_cognition,
    payload_from_material_decision,
)
from scripts.lib.agent_feature_flags import load_feature_flags
from scripts.lib.cio_persistent_cognition import (
    OUT_NO_CHANGE,
    OUT_REASSESS,
    OUT_THESIS,
    audit_unresolved_identity,
    cognition_for_symbol,
    cross_agent_row,
    need_data_gap,
    resolve_decision_cognition,
)
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


def _seed(tmp_path, sym="NOC", company="Northrop"):
    seed_profiles(tmp_path, [{"symbol": sym, "company": company, "sector": "Industrials"}])
    circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile(sym, metadata={"company": company})),
        hermes_rows=_hermes(),
        rag_fn=lambda _s: {"ok": True, "supporting": [], "contradictory": []},
        allow_searx=False,
    )


def _flags(**kw):
    base = load_feature_flags({})
    base.update(kw)
    return base


def test_natural_payload_carries_cognition_refs(tmp_path):
    _seed(tmp_path)
    tp = tmp_path / "traces.jsonl"
    out = emit_payloads_for_decisions(
        [{"decision_id": "dec_noc", "symbol": "NOC", "standing_recommendation": "HOLD"}],
        wake_id="wake_l5",
        surface="material_scan",
        flags=_flags(AGENT_DECISION_PAYLOAD=1),
        path=tp,
        cognition_root=tmp_path,
        held={"NOC"},
    )
    assert out["emitted"] == 1
    row = json.loads(tp.read_text().splitlines()[0])
    dec = row["decision"]
    assert dec["schema"] == PAYLOAD_SCHEMA
    refs = dec["cognition_refs"]
    assert refs["schema"] == "CIOCognitionRefs@v1"
    assert refs["security_guid"]
    assert refs["curation_kind"] == KIND_BASELINE
    assert refs["curation_version"] == 0
    assert refs["question"] == "WHAT_MATERIAL_THING_CHANGED_FOR_THE_PORTFOLIO"
    assert dec["portfolio_delta"] == OUT_NO_CHANGE
    assert dec["context_receipt"]["schema"] == "ContextUseReceipt@v1"
    assert dec["financial_action"] is False
    assert "chain_of_thought" not in json.dumps(dec)
    receipts = tmp_path / "data/cio/context_use_receipts.jsonl"
    assert receipts.is_file()
    rec = json.loads(receipts.read_text().splitlines()[0])
    assert rec["security_guid"] == refs["security_guid"]
    assert rec["decision_id"] == "dec_noc"


def test_stale_serialized_version_re_resolves(tmp_path):
    _seed(tmp_path)
    first = resolve_decision_cognition("NOC", decision_id="d1", wake_id="w1", root=tmp_path, held={"NOC"})
    v0 = first["refs"]["curation_version"]
    p = tmp_path / "data/cio/hermes_curation_summary.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    rows[0]["version"] = int(v0 or 0) + 1
    rows[0]["kind"] = "MATERIAL"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    second = resolve_decision_cognition("NOC", decision_id="d2", wake_id="w2", root=tmp_path, held={"NOC"})
    assert second["refs"]["curation_version"] == int(v0 or 0) + 1
    assert second["refs"]["curation_version"] != v0 or v0 == second["refs"]["curation_version"]


def test_no_portfolio_change_replay_no_llm(tmp_path):
    _seed(tmp_path)
    a = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    b = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert a["portfolio_delta"] == OUT_NO_CHANGE
    assert b["portfolio_delta"] == OUT_NO_CHANGE
    assert a["paid_dispatch"] == 0
    assert a["financial_action"] is False


def test_material_delta_reassessment(tmp_path):
    _seed(tmp_path)
    p = tmp_path / "data/cio/ticker_research_state.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    rows[0]["evidence_watermark"] = ["new-guid-material"]
    rows[0]["decision"] = "MATERIAL_CHANGE"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    cp = tmp_path / "data/cio/hermes_curation_summary.jsonl"
    crows = [json.loads(l) for l in cp.read_text().splitlines() if l.strip()]
    crows[0]["what_changed"] = "MATERIAL"
    crows[0]["evidence_watermark"] = ["old-guid"]
    cp.write_text("".join(json.dumps(r) + "\n" for r in crows))
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert row["portfolio_delta"] == OUT_REASSESS


def test_need_data_creates_gap_not_search(tmp_path):
    _seed(tmp_path)
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    gap = need_data_gap(
        tmp_path,
        symbol="NOC",
        security_guid=row.get("security_guid"),
        question="What is current backlog coverage?",
    )
    assert gap.get("wrote") is True
    assert (gap.get("gap") or {}).get("status") == "FREE_FIRST_PENDING"
    assert "provider" not in json.dumps(gap).lower()


def test_conflicted_suppresses_recommendation(tmp_path):
    _seed(tmp_path)
    p = tmp_path / "data/cio/ticker_research_state.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    rows[0]["decision"] = "CONFLICTED"
    rows[0]["support_evidence"] = ["s1"]
    rows[0]["counter_evidence"] = ["c1"]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert row["conflicted"] is True
    assert row["recommendation_suppressed"] is True
    assert row["portfolio_delta"] == OUT_THESIS
    pl = payload_from_material_decision(
        {"decision_id": "dec_c", "symbol": "NOC", "action": "HOLD"},
        wake_id="w",
    )
    pl = enrich_payload_with_cognition(pl, cognition_root=tmp_path, held={"NOC"})
    assert pl["cognition_refs"]["conflicted"] is True
    assert pl["cognition_refs"]["recommendation_suppressed"] is True


def test_prso_identity_not_fabricated(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "PRSO", "company": None, "sector": None}])
    circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile("PRSO", metadata={})),
        hermes_rows=_hermes(),
        rag_fn=lambda _s: {"ok": True, "supporting": [], "contradictory": []},
        allow_searx=False,
    )
    audit = audit_unresolved_identity(tmp_path, "PRSO")
    assert audit["fabricated_relationships"] == 0
    assert audit["result"] in {
        "RESOLVED_CANONICAL",
        "LEGACY_ALIAS_RESOLVED",
        "NON_SECURITY_IDENTIFIER",
        "UNRESOLVED_WITH_REASON",
    }
    if not audit.get("security_guid"):
        assert audit["result"] == "UNRESOLVED_WITH_REASON"


def test_same_brain_cross_agent(tmp_path):
    for sym, co in [("SCHD", "Schwab"), ("NOC", "Northrop")]:
        _seed(tmp_path, sym, company=co)
    for sym in ("SCHD", "NOC"):
        m = cross_agent_row(tmp_path, sym, held={sym})
        assert m["consistent"] is True
        assert m["advisory"]["security_guid"] == m["security_guid"]
        assert m["telegram"]["curation_id"] == m["curation_id"]


def test_membership_label_skips_cognition():
    pl = payload_from_material_decision(
        {"decision_id": "dec_cash", "symbol": "CASH", "action": "HOLD_CASH"},
        wake_id="w",
    )
    pl = enrich_payload_with_cognition(pl)
    assert pl["symbol"] == "DATA_UNAVAILABLE"
    assert pl["cognition_refs"]["skipped"] == "non_security_symbol"


def test_no_provider_on_unchanged(tmp_path):
    _seed(tmp_path)
    row = cognition_for_symbol(tmp_path, "NOC", held={"NOC"})
    assert row["paid_dispatch"] == 0
    assert row["financial_action"] is False

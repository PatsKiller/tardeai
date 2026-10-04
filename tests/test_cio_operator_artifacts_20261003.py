"""CIOOperatorArtifact@v1: operator-relevant CIO outputs that used to be transient.

Operator-approved store (2026-10-03). Thirteen CIO outputs were produced but never
stored, so the Command Center could not show them later. These pin the writer
(append once, never raise, bounded), that hooked producers record their output
without changing it, the read endpoint's filters, and the completeness count.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_operator_artifacts as coa  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    path = tmp_path / "data" / "cio" / "cio_operator_artifacts.jsonl"
    monkeypatch.setenv("CIO_OPERATOR_ARTIFACTS_JSONL", str(path))
    coa._INDEX.clear()
    return path


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


# --- writer ------------------------------------------------------------------

def test_appends_once_per_schema_and_id(store):
    a = coa.record_advisory_message({"text": "Cash above band."}, producer="t", artifact_id="sit1:x",
                                    links={"decision_id": "dec_1", "symbol": "CASH"}, source_as_of="2026-10-03T10:00:00+00:00")
    b = coa.record_advisory_message({"text": "Cash above band."}, producer="t", artifact_id="sit1:x")
    assert a["written"] is True and b == {"written": False, "reason": "duplicate", "artifact_id": "sit1:x"}
    rows = _rows(store)
    assert len(rows) == 1
    r = rows[0]
    assert r["schema"] == "CIOOperatorArtifact@v1" and r["original_schema"] == "CIOAdvisoryMessage@v1"
    assert r["artifact_id_basis"] == "producer_id" and r["decision_id"] == "dec_1" and r["symbol"] == "CASH"
    assert r["authority"] == "READ_ONLY_ADVISORY" and r["memory_behavior_influence"] == 0


def test_same_id_under_another_schema_is_a_different_artifact(store):
    coa.record_composed_narrative({"sentences": []}, producer="t", artifact_id="w1:AES")
    coa.record_wake_composition({"sentences": []}, producer="t", artifact_id="w1:AES")
    assert len(_rows(store)) == 2


def test_missing_producer_id_falls_back_to_a_labelled_content_hash(store):
    coa.record_attention_answer({"reply": "Nothing material."}, producer="t")
    r = _rows(store)[0]
    assert r["artifact_id_basis"] == "content_sha256" and len(r["artifact_id"]) == 24


def test_oversized_payload_is_truncated_with_a_marker(store):
    coa.record_agent_brief({"text": "x" * 50_000}, producer="t")
    r = _rows(store)[0]
    assert r["payload_truncated"] is True and r["payload"]["_truncated"] is True
    assert r["payload"]["_original_bytes"] > coa.MAX_PAYLOAD_BYTES


def test_writer_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    monkeypatch.setenv("CIO_OPERATOR_ARTIFACTS_JSONL", str(blocker / "x.jsonl"))
    coa._INDEX.clear()
    out = coa.record_grok_critique({"verdict": "PASS"}, producer="t")
    assert out["written"] is False


# --- hooked producers record without changing what they produce --------------

def _raise(*a, **k):
    raise RuntimeError("store down")


def test_notify_bridge_records_the_message_and_its_output_is_unchanged(store, monkeypatch):
    from scripts.lib import cio_situation_notify_bridge as bridge

    sit = {"situation_id": "sit_abc1234567890123", "situation_class": "CONTRADICTION",
           "notification_eligibility": "NOTIFY", "what_changed": "Thesis contradicted", "new_state": {"symbol": "SCHD"}}
    with_hook = bridge.situation_to_decision(dict(sit))
    rows = _rows(store)
    assert [r["original_schema"] for r in rows] == ["CIOAdvisoryMessage@v1"]
    assert rows[0]["decision_id"] == with_hook["decision_id"]
    monkeypatch.setattr(coa, "record_advisory_message", _raise)
    without = bridge.situation_to_decision(dict(sit))
    def strip(d):  # per-call clocks differ by microseconds; everything else must match
        return {k: v for k, v in d.items() if not (k.endswith("_at") or k in ("next_review", "as_of"))}
    assert strip(with_hook) == strip(without)


ENV_ON = {"CIO_NARRATIVE_COMPOSITION_ENABLED": "1"}


def test_wake_compose_records_composition_narrative_and_model_narration(store, tmp_path):
    from scripts.lib import cio_wake_compose as cwc

    feed = tmp_path / "research.jsonl"
    feed.write_text(json.dumps({"subject_guid": "g1", "symbol": "AES", "content_hash": "h1",
                                "title": "Filing A", "source_url": "https://reuters.com/a"}) + "\n", encoding="utf-8")
    env = {**ENV_ON, "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH": str(feed)}
    ctx = {"wake_id": "w1", "agent_id": "cio", "subject_guid": "g1", "memory_facts": [], "comm_events": [],
           "operator_turns": [], "memory_empty": True,
           "selection": {"source": "unconsumed_research", "source_id": "r1", "observed_at": "2026-09-10T13:45:00Z"}}
    cwc._composed_this_process = 0
    out = cwc.composing_decide(ctx, env=env, narrator=lambda **kw: [{"sentence": "AES filed.", "cites": ["content_hash:h1"]}])
    assert "narrative" in out
    got = sorted(r["original_schema"] for r in _rows(store))
    assert got == ["CioComposedNarrative@v1", "CioModelNarration@v1", "CioWakeComposition@v1"]
    assert all(r["wake_id"] == "w1" for r in _rows(store))


def test_committee_decision_is_recorded_as_its_envelope(store):
    from scripts.lib.cio_advisory_schema import EvidenceSource, SpecialistAdvisory, SpecialistAdvisoryPosition
    from scripts.lib.cio_committee_synthesis import synthesize_decision
    from scripts.lib.cio_evidence_ref import make_ref
    from scripts.lib.cio_investment_decision import POSITION_HOLD

    def adv(sid):
        return SpecialistAdvisory(
            specialist_id=sid, parent_run_id="run_1", run_purpose="allocation review",
            position=SpecialistAdvisoryPosition.SUPPORT, recommendation="Adjust allocation.",
            rationale="Drift toward target.",
            evidence_sources=[EvidenceSource(source_id="ds-1", domain="portfolio", quality_state="AVAILABLE")],
            evidence_summary="ok", confidence=0.7, confidence_basis="PARTIAL_EVIDENCE", material_risks=[],
            alternatives_considered=[], conditions_to_change_view=[], evidence_gaps=[], deficiencies_acknowledged=[],
        )

    ev = make_ref("holdings_detail", {"symbol": "SCHD", "weight_pct": 14.2},
                  source="data/portfolios/state/holdings.json", quality_state="AVAILABLE", symbol="SCHD",
                  deterministic_calculation_version="holding-agg-v1")
    d = synthesize_decision(parent_run_id="run_1", intended_position=POSITION_HOLD,
                            specialist_advisories=[adv("steph"), adv("morgan"), adv("maria")],
                            evidence_refs=[ev], rationale_linked_to_evidence="Hold SCHD.",
                            conditions_to_change_view=["weight breaches fire"], symbols=["SCHD"])
    rows = _rows(store)
    assert [r["original_schema"] for r in rows] == ["InvestmentDecision@v1"]
    assert rows[0]["run_id"] == "run_1"
    assert rows[0]["payload"]["final_position"] == d.final_position


# --- read endpoint -------------------------------------------------------------

def test_endpoint_filters_by_schema_and_decision(store, tmp_path, monkeypatch):
    coa.record_advisory_message({"text": "A"}, producer="t", artifact_id="a", links={"decision_id": "dec_1"})
    coa.record_grok_critique({"verdict": "PASS"}, producer="t", artifact_id="g")
    import scripts.api_v3_cio as api

    monkeypatch.setattr(coa, "_buy_ready_rows", lambda root, limit: [])
    every = api.get_cio_operator_artifacts({})
    assert every["ok"] is True and every["total_matched"] == 2
    one = api.get_cio_operator_artifacts({"decision_id": ["dec_1"]})
    assert [r["original_schema"] for r in one["artifacts"]] == ["CIOAdvisoryMessage@v1"]
    by_schema = api.get_cio_operator_artifacts({"schema": "GrokCritique@v1"})
    assert [r["artifact_id"] for r in by_schema["artifacts"]] == ["g"]


def test_buy_ready_packets_are_served_from_their_own_store_not_copied(store, tmp_path):
    packets = tmp_path / "data" / "runtime" / "buy_ready_packets"
    packets.mkdir(parents=True)
    (packets / "SCHD.json").write_text(json.dumps({"schema": "BuyReadyInstitutionalPacket@v2", "symbol": "SCHD",
                                                   "as_of": "2026-10-03T09:00:00+00:00"}), encoding="utf-8")
    out = coa.list_operator_artifacts(root=tmp_path)
    rows = [r for r in out["artifacts"] if r["original_schema"] == "BuyReadyInstitutionalPacket@v2"]
    assert rows and rows[0]["source_ref"] == "buy_ready_packets/SCHD.json"
    assert not store.exists()  # nothing was copied into the artifact store


# --- completeness -------------------------------------------------------------

def test_completeness_leaves_only_the_dead_producer_unsurfaced():
    import subprocess

    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "cio_completeness_measurement.py"), "--json"],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)
    data = json.loads(proc.stdout)
    assert data["produced_not_surfaced_operator_relevant"] == ["schema:AlertQuality@v1"]
    verified = {e["name"] for e in data["record_edges"] if e["verified"]}
    for name in ("CIOAdvisoryMessage@v1", "CIOAdvisorySynthesis@v1", "CIOAgentBrief@v1", "CIOAttentionAnswer@v1",
                 "CIOWhatChanged@v1", "CioComposedNarrative@v1", "CioModelNarration@v1", "CioWakeComposition@v1",
                 "GrokCritique@v1", "InvestmentDecision@v1", "InvestmentIntelligenceCard@v1"):
        assert f"schema:{name}" in verified
    # BuyReady packets are visible through the payload flow itself (served from their own store).
    visible = data.get("visibility_evidence") or {}
    assert "schema:BuyReadyInstitutionalPacket@v2" in visible
    assert "schema:CIOOperatorArtifact@v1" in visible

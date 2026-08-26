"""M4 ContextEnvelope@v2 same-brain source tests."""
from __future__ import annotations

from scripts.lib.agent_context_envelope import get_context_for_agent, validate_context_envelope
from scripts.lib.cio_context_envelope_v2 import AGENTS, SECTIONS, attach_v2, same_brain
from scripts.lib.cio_persistent_cognition import build_cio_cognition, cognition_for_symbol
from scripts.lib.free_first_circulation import circulate_symbol
from scripts.lib.proactive_cio import detect
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


def _seed(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "Northrop", "sector": "Industrials"}])
    circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile("NOC", metadata={"company": "Northrop"})),
        hermes_rows=_hermes(),
        rag_fn=lambda _s: {"ok": True, "supporting": [], "contradictory": []},
        allow_searx=False,
    )


def test_v1_still_validates_with_v2_nested(tmp_path):
    _seed(tmp_path)
    env = get_context_for_agent(agent="alex", symbols=["NOC"], cognition_root=str(tmp_path), held=["NOC"])
    pack = env["research_memory"]["persistent_ticker_cognition"]
    env2 = attach_v2(env, pack)
    ok, errors = validate_context_envelope(env2)
    assert ok, errors
    assert env2["research_memory"]["cio_context_v2"]["schema"] == "CIOContextEnvelope@v2"


def test_same_brain_agents(tmp_path):
    _seed(tmp_path)
    matrix = same_brain(tmp_path, ["NOC"], held={"NOC"})
    assert matrix["consistent"] is True
    assert "telegram" in matrix["agents"]
    assert "maria" in matrix["agents"]
    assert "steph" in matrix["agents"]
    row = matrix["symbols"]["NOC"]
    guid = row["security_guid"]
    assert row["advisory"]["security_guid"] == guid
    assert row["telegram"]["security_guid"] == guid


def test_required_v2_sections_listed():
    assert "OFFICE_TRUTH" in SECTIONS
    assert "MEMORY_RETRIEVAL_UNITS" in SECTIONS
    assert "alex" in AGENTS


def test_m4_consumes_m3_contracts():
    from scripts.lib.agent_episode import SCHEMA as EP
    from scripts.lib.memory_consolidator import SCHEMA as CS
    assert EP == "AgentEpisode@v1"
    assert CS == "MemoryConsolidator@v1"


def test_proactive_cash_band_no_trade():
    d = detect(cash=0.02, policy_cash_band=(0.05, 0.15))
    assert d["call"] == "OPERATOR_NOTIFICATION_CANDIDATE"
    assert d["trading"] is False
    assert d["financial_action"] is False

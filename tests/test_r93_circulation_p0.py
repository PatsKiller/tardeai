"""P0 circulation: Hermes projection, gates, 503, replay, no paid dispatch."""
from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest

from scripts.lib.artifact_embed import PENDING, embed_artifact
from scripts.lib.evidence_refresh_job import (
    dispatch_paid_provider,
    paid_dispatch_entered,
    reset_paid_dispatch_probe,
)
from scripts.lib.free_first_circulation import circulate_symbol, project_hermes_rows
from scripts.lib.security_identity import attach_identity_v2
from scripts.lib.ticker_knowledge_graph import build_profile, retrieve_context, seed_profiles
from scripts.lib.ticker_research_state import upsert_state, build_state


def _profile(sym="NOC"):
    return attach_identity_v2(build_profile(sym, metadata={"company": "Northrop", "sector": "Industrials"}))


def _hermes():
    return {
        "research": [{
            "id": 11, "topic": "defense", "summary": "backlog intact", "thesis": "HOLD durability",
            "status": "promoted", "research_type": "web",
            "source_urls_json": ["https://sec.gov/Archives/noc"],
            "created_at": "2026-08-20T00:00:00+00:00",
        }],
        "external": [{
            "id": 22, "lane": "deepseek", "recommendation": "HOLD / DO NOT ADD",
            "created_at": "2026-08-22T00:00:00+00:00",
        }],
    }


def _empty_rag(_sym):
    return {"ok": True, "supporting": [], "contradictory": []}


def test_planned_cannot_dispatch_paid():
    reset_paid_dispatch_probe()
    with pytest.raises(RuntimeError, match="PAID_DISPATCH_FORBIDDEN"):
        dispatch_paid_provider(state="PLANNED", mode="FREE_FIRST_ONLY")
    assert paid_dispatch_entered() == 1  # entered then rejected


def test_llm_eligible_does_not_authorize_paid():
    reset_paid_dispatch_probe()
    with pytest.raises(RuntimeError, match="PAID_DISPATCH_FORBIDDEN"):
        dispatch_paid_provider(state="LLM_ELIGIBLE", mode="FREE_FIRST_ONLY")


def test_hermes_projects_artifacts_idempotently(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "NG"}])
    a = project_hermes_rows(tmp_path, "NOC", rows=_hermes())
    b = project_hermes_rows(tmp_path, "NOC", rows=_hermes())
    assert a["rows_examined"] == 2
    arts = retrieve_context(tmp_path, "NOC", limit=50)
    n = sum(1 for r in arts["linear"] + arts["lateral"] if r.get("research_artifact_guid"))
    assert n >= 2
    # second pass same GUIDs
    assert b["artifacts_after"] == a["artifacts_after"]


def test_circulation_hermes_reuse_no_paid_no_searx(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "NG", "sector": "Industrials"}])
    r = circulate_symbol(
        tmp_path, _profile(), hermes_rows=_hermes(), rag_fn=_empty_rag, allow_searx=False,
    )
    assert r["hermes_resolved"] is True
    assert r["decision"] == "NO_NEW_INFO"
    assert r["paid_dispatch_entered"] == 0
    assert r["searx_queries"] == 0
    assert r["llm_eligible"] is None
    assert "HERMES" in r["path"]


def test_no_new_info_replay_zero_new_state(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC", "company": "NG", "sector": "Industrials"}])
    r1 = circulate_symbol(tmp_path, _profile(), hermes_rows=_hermes(), rag_fn=_empty_rag, allow_searx=False)
    n1 = r1["artifacts"]
    r2 = circulate_symbol(tmp_path, _profile(), hermes_rows=_hermes(), rag_fn=_empty_rag, allow_searx=False)
    assert r2["artifacts"] == n1
    assert r2["state_wrote"] is False
    assert r2["paid_dispatch_entered"] == 0


def test_embedding_503_keeps_artifact(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "NOC"}])
    project_hermes_rows(tmp_path, "NOC", rows=_hermes())
    art = {"research_artifact_guid": "guid-1", "title": "t", "summary": "s", "symbol": "NOC"}

    def boom(_text):
        raise HTTPError("http://x", 503, "unavailable", hdrs=None, fp=BytesIO())

    rec = embed_artifact(tmp_path, art, embed_fn=boom)
    assert rec["status"] == PENDING
    assert rec.get("acquired_artifact_preserved") is True
    n = sum(1 for r in retrieve_context(tmp_path, "NOC")["linear"] if r.get("research_artifact_guid"))
    assert n >= 1
    # retry same attempt is idempotent
    embed_artifact(tmp_path, art, embed_fn=boom)


def test_structured_card_is_not_thesis_evidence(tmp_path):
    seed_profiles(tmp_path, [{"symbol": "GOVX"}])
    r = circulate_symbol(
        tmp_path,
        attach_identity_v2(build_profile("GOVX")),
        hermes_rows={"research": [], "external": []},
        rag_fn=_empty_rag,
        structured_fn=lambda _s, _p: {"items": [], "gaps_ok": []},
        allow_searx=False,
    )
    assert r["decision"] == "LLM_ELIGIBLE_NOT_AUTHORIZED"
    assert r["paid_dispatch_entered"] == 0
    assert r["llm_eligible"] == "Flash"

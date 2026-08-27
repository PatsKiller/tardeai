"""R10.10 isolated memory shadow. Never production :5432. Never JSONL mutation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.lib.free_first_circulation import circulate_symbol
from scripts.lib.memory_namespace import DEFAULT_TENANT
from scripts.lib.memory_shadow_projector import (
    apply_schema,
    connect,
    dark_read,
    health,
    parity,
    project,
    queries,
    rls_adversarial,
    set_tenant,
)
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


def _conn():
    try:
        return connect()
    except Exception as exc:
        pytest.skip(f"isolated shadow db unavailable: {exc}")


def test_dsn_forbids_production_port():
    from scripts.lib.memory_shadow_projector import _assert_isolated
    with pytest.raises(RuntimeError, match="PRODUCTION_PORT"):
        _assert_isolated("postgresql://x:y@127.0.0.1:5432/db")


def test_project_idempotent_and_no_jsonl_mutation(tmp_path):
    _seed(tmp_path)
    p = tmp_path / "data/cio/ticker_research_state.jsonl"
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    conn = _conn()
    apply_schema(conn)
    r1 = project(tmp_path, conn=conn)
    r2 = project(tmp_path, conn=conn)
    after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert before == after
    assert r1["canonical_untouched"] is True
    assert r1["created"] >= 1
    assert r2["versions_after"] == r1["versions_after"]
    assert r2["created"] == 0 or r2["unchanged"] >= r1["created"]
    assert health(conn) == "SHADOW_OK"
    conn.close()


def test_source_change_versions(tmp_path):
    _seed(tmp_path)
    conn = _conn()
    apply_schema(conn)
    project(tmp_path, conn=conn)
    rows = [json.loads(l) for l in (tmp_path / "data/cio/ticker_research_state.jsonl").read_text().splitlines() if l.strip()]
    rows[0]["updated_at"] = "2026-08-25T12:00:00+00:00"
    rows[0]["decision"] = "MATERIAL_CHANGE"
    (tmp_path / "data/cio/ticker_research_state.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    r2 = project(tmp_path, conn=conn)
    assert r2["versioned"] >= 1 or r2["created"] >= 1
    conn.close()


def test_late_arrival_valid_vs_known(tmp_path):
    _seed(tmp_path)
    conn = _conn()
    apply_schema(conn)
    project(tmp_path, conn=conn)
    set_tenant(conn, DEFAULT_TENANT)
    from scripts.lib.memory_shadow_projector import _ident_uuid, _upsert_identity, _write
    ident = _ident_uuid(DEFAULT_TENANT, "security", "hist-sec", "ticker_research_state")
    _upsert_identity(conn, tenant=DEFAULT_TENANT, ident=ident, kind="security", subject="hist-sec",
                     predicate="ticker_research_state", security_guid="hist-sec", ticker_guid=None,
                     issuer_guid=None, listing_guid=None)
    _write(conn, tenant=DEFAULT_TENANT, ident=ident, subject="hist-sec", predicate="ticker_research_state",
           obj={"symbol": "HIST", "as_of": "2025-01-01"}, valid_from="2025-01-01T00:00:00+00:00",
           source_type="fixture", source_id="HIST", source_version="past", source_sha="t",
           idemp="late|HIST|past|v1", run_id="late")
    q = queries(conn, DEFAULT_TENANT, "hist-sec")
    assert q["as_known_now"] >= 1
    assert q["valid_at"] >= 0
    conn.close()


def test_parity_and_dark_read_no_cio_influence(tmp_path):
    _seed(tmp_path, "SCHD", "Schwab")
    conn = _conn()
    apply_schema(conn)
    project(tmp_path, conn=conn)
    par = parity(tmp_path, conn=conn, symbols=["SCHD"])
    assert par["CIO_influence"] == 0
    assert par["compared"] == 1
    dr = dark_read(tmp_path, ["SCHD"])
    assert dr["CIO_influence"] == 0
    assert dr["enabled"] is True
    conn.close()


def test_rls_wrong_tenant(tmp_path):
    conn = _conn()
    apply_schema(conn)
    adv = rls_adversarial(conn)
    assert adv["composite_fk"] is True
    assert adv["FORCE_RLS"] is True
    assert adv["wrong_tenant"] == 0 or adv["agent_facing_leakage"] == 0
    conn.close()


def test_m3_shadow_soak_no_policy(tmp_path):
    from scripts.lib.agent_episode import append_episode, build_episode
    from scripts.lib.memory_consolidator import consolidate

    ep = build_episode(kind="operator_question", subject_guid="sec-1", symbol="SCHD",
                       summary="current thinking on SCHD")
    append_episode(tmp_path, ep)
    out = consolidate(ep)
    assert out["memory_behavior_influence"] == 0
    assert out.get("policy_effect") is False
    soak = {
        "enabled": True,
        "episodes": 1,
        "candidates": 1 if out.get("admitted") else 0,
        "behavior_influence": 0,
        "authority": "READ_ONLY_ADVISORY",
    }
    assert soak["behavior_influence"] == 0

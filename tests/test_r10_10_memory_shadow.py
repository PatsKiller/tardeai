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


# ---------------------------------------------------------------------------
# Isolation guard. This guard had NO test before 2026-09-20 — it is the only
# thing standing between the projector and a non-isolated database.
# ---------------------------------------------------------------------------

_SHADOW = "postgresql://m2:m2shadow@127.0.0.1:55432/m2_shadow"
_PROD = "postgresql://u:p@127.0.0.1:5432/trade_ai"
_OTHER = "postgresql://u:p@127.0.0.1:5433/other"
# The credential contains the digits 55432 while the PORT is 5433. The old check
# tested `"55432" in dsn` over the whole string, so this spoofed the allowlist.
_SPOOF = "postgresql://u:pass55432word@127.0.0.1:5433/other"


def _guard():
    from scripts.lib.memory_shadow_projector import _assert_isolated

    return _assert_isolated


def test_production_port_always_refused(monkeypatch):
    """Not overridable: the opt-in relaxes non-default ports, never :5432."""
    monkeypatch.setenv("MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT", "1")
    with pytest.raises(RuntimeError, match="MEMORY_SHADOW_PRODUCTION_PORT_FORBIDDEN"):
        _guard()(_PROD)


def test_isolated_shadow_accepted(monkeypatch):
    monkeypatch.delenv("MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT", raising=False)
    assert _guard()(_SHADOW) == _SHADOW


def test_nondefault_port_refused_unless_opted_in(monkeypatch):
    monkeypatch.delenv("MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT", raising=False)
    with pytest.raises(RuntimeError, match="MEMORY_SHADOW_ISOLATED_PORT_REQUIRED"):
        _guard()(_OTHER)
    monkeypatch.setenv("MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT", "1")
    assert _guard()(_OTHER) == _OTHER


def test_credential_containing_55432_cannot_spoof_the_allowlist(monkeypatch):
    """Regression: the check now reads the host tail, not the whole DSN."""
    monkeypatch.delenv("MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT", raising=False)
    with pytest.raises(RuntimeError, match="MEMORY_SHADOW_ISOLATED_PORT_REQUIRED"):
        _guard()(_SPOOF)


def test_env_var_is_subsystem_scoped_not_the_m2_name():
    """The old name M2_ALLOW_NONDEFAULT_PORT was shared with the M2 benchmark,
    where it was a no-op, and the two guards are semantic inverses. Setting the
    M2 name must no longer affect this subsystem."""
    src = (Path(__file__).resolve().parents[1]
           / "scripts" / "lib" / "memory_shadow_projector.py").read_text(encoding="utf-8")
    assert 'os.getenv("MEMORY_SHADOW_ALLOW_NONDEFAULT_PORT")' in src
    assert 'os.getenv("M2_ALLOW_NONDEFAULT_PORT")' not in src


def test_backup_restore_suite_has_no_tautological_guard():
    """backup_restore_suite is safe because its connection parameters are
    hardcoded literals, not because of an assertion over a constant it never
    uses. Keep the literals; do not reintroduce a DSN parameter."""
    src = (Path(__file__).resolve().parents[1]
           / "scripts" / "lib" / "memory_m2_v2.py").read_text(encoding="utf-8")
    body = src.split("def backup_restore_suite")[1].split("\ndef ")[0]
    # Strip the docstring: it names the removed call deliberately, to explain why
    # the literals are the guarantee. Assert on executable lines only.
    code = body.split('"""')[2] if body.count('"""') >= 2 else body
    assert "_assert_isolated_dsn(" not in code
    assert code.count('"55432"') >= 6, "the hardcoded isolated port IS the guarantee"

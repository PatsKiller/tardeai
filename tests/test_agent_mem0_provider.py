"""Phase 4 — Mem0 shadow adapter + local test provider tests.

No broker, no network. Deterministic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_context_envelope import (  # noqa: E402
    MEMORY_AUTHORITY_NON_AUTHORITATIVE,
    RETRIEVAL_NOT_CONFIGURED,
)
from scripts.lib.agent_memory_provider import (  # noqa: E402
    LocalTestMemoryProvider,
    NullMemoryProvider,
)
from scripts.lib.agent_memory_governance import (  # noqa: E402
    MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
    MEMORY_TYPE_OPERATOR_INFERRED_PREFERENCE,
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    build_memory_record,
    resolve_conflict,
)
from scripts.lib.agent_mem0_provider import (  # noqa: E402
    MEM0_DUE_DILIGENCE,
    Mem0MemoryProvider,
)


# ── Mem0 adapter: honest NOT_CONFIGURED ──────────────────────────────────


def test_mem0_health_not_configured():
    h = Mem0MemoryProvider().health()
    assert h["status"] == "NOT_CONFIGURED"
    assert "reason" in h


def test_mem0_search_fail_soft():
    res = Mem0MemoryProvider().search(query="SCHD")
    assert res["retrieval_status"] == RETRIEVAL_NOT_CONFIGURED
    assert res["records"] == []
    assert res["counter_memory"] == []


def test_mem0_add_candidate_noop():
    assert Mem0MemoryProvider().add_candidate({"content": "x"}) is None


def test_mem0_due_diligence_is_honest():
    assert MEM0_DUE_DILIGENCE["installed"] is False
    assert MEM0_DUE_DILIGENCE["version"] == "none installed"
    assert MEM0_DUE_DILIGENCE["production_status"] == "NOT_CONFIGURED — shadow pilot only"
    assert MEM0_DUE_DILIGENCE["hosting_preference"] == "self-hosted/local-controlled"


def test_mem0_provider_exposes_no_runtime_flag_defaults():
    # The single source of truth for runtime activation is agent_feature_flags.
    # Mem0 must NOT declare contradictory activation defaults.
    import scripts.lib.agent_mem0_provider as m0  # noqa: E402

    for forbidden in ("MEMORY_SHADOW", "MEMORY_PROVIDER", "MEMORY_BEHAVIOR_INFLUENCE"):
        assert not hasattr(m0, forbidden), f"agent_mem0_provider must not define {forbidden}"


# ── Null provider fail-soft ──────────────────────────────────────────────


def test_null_provider_fail_soft():
    p = NullMemoryProvider()
    assert p.health()["status"] == "NOT_CONFIGURED"
    assert p.search(query="x")["retrieval_status"] == RETRIEVAL_NOT_CONFIGURED
    assert p.add_candidate({"content": "x"}) is None
    assert p.get("m1") is None
    assert p.dispute("m1", "reason") is False
    assert p.expire("m1") is False


# ── LocalTestMemoryProvider round-trip ───────────────────────────────────

# add_candidate is a governed admission path: it requires provenance and
# rejects forbidden-authoritative subjects. Raw provenance-free dicts are
# rejected rather than becoming retrievable context.
def _ok(content, subject="SCHD", **kw):
    kw.setdefault("source_event_ids", ["evt_1"])
    return {"content": content, "subject": subject, **kw}


def test_local_add_get_dispute_expire_round_trip():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(_ok("op prefers SCHD", confidence=0.9))
    assert mid
    got = p.get(mid)
    assert got["content"] == "op prefers SCHD"
    assert got["memory_id"] == mid

    assert p.dispute(mid, "contradicted")
    assert p.get(mid)["status"] == "DISPUTED"

    assert p.expire(mid)
    assert p.get(mid)["status"] == "EXPIRED"

    res = p.search(query="SCHD")
    ids = [r["memory_id"] for r in res["records"] + res["counter_memory"]]
    assert mid not in ids


def test_local_search_supporting_and_counter():
    p = LocalTestMemoryProvider()
    a = p.add_candidate(_ok("keep SCHD", confidence=0.9))
    p.add_candidate(_ok("reduce SCHD", contradicts=[a]))
    res = p.search(query="SCHD")
    assert len(res["records"]) >= 1
    assert len(res["counter_memory"]) >= 1


def test_local_health_ok():
    p = LocalTestMemoryProvider()
    p.add_candidate(_ok("hello", subject="greeting"))
    h = p.health()
    assert h["status"] == "OK"
    assert h["memory_count"] == 1


# ── Governed admission: provenance + forbidden-subject closure ───────────


def test_local_add_candidate_rejects_no_provenance():
    p = LocalTestMemoryProvider()
    assert p.add_candidate({"content": "op prefers SCHD", "subject": "SCHD"}) is None
    assert p.health()["memory_count"] == 0


def test_local_add_candidate_rejects_forbidden_subject():
    p = LocalTestMemoryProvider()
    assert p.add_candidate(_ok("cash is $1,000,000", subject="cash")) is None
    assert p.add_candidate(_ok("risk limit 10%", subject="risk limit")) is None
    assert p.health()["memory_count"] == 0


# ── Canonical feature flags are the single runtime source ────────────────


def test_canonical_flags_default_all_off():
    from scripts.lib.agent_feature_flags import load_feature_flags  # noqa: E402

    flags = load_feature_flags({})
    assert flags["AGENT_CONTEXT_ENVELOPE"] == 0
    assert flags["AGENT_RUN_TRACE"] == 0
    assert flags["MCP_READ_ONLY_GATEWAY"] == 0
    assert flags["MEMORY_PROVIDER"] == "null"
    assert flags["MEMORY_SHADOW"] == 0
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert flags["LANGGRAPH_WORKER_PILOT"] == 0


# ── Forced admission privilege fields (P1 regression) ─────────────────────


def _forged_pref(**kw):
    """An inferred preference the caller tries to elevate to ACTIVE/AUTHORITATIVE."""
    kw.setdefault("memory_type", MEMORY_TYPE_OPERATOR_INFERRED_PREFERENCE)
    kw.setdefault("subject", "SCHD preference")
    kw.setdefault("content", "seems to like SCHD")
    kw.setdefault("source_event_ids", ["evt_1"])
    return kw


def test_forged_authority_class_is_downgraded():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(_forged_pref(authority_class="AUTHORITATIVE"))
    assert mid is not None
    got = p.get(mid)
    assert got["authority_class"] == MEMORY_AUTHORITY_NON_AUTHORITATIVE


def test_inferred_preference_forged_active_is_downgraded():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(_forged_pref(status=STATUS_ACTIVE))
    assert mid is not None
    got = p.get(mid)
    assert got["status"] == STATUS_CANDIDATE


def test_explicit_preference_may_be_active_under_canonical_rule():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(
        {
            "memory_type": MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
            "subject": "SCHD",
            "content": "operator wants SCHD core",
            "source_event_ids": ["evt_1"],
            "status": STATUS_ACTIVE,
        }
    )
    assert mid is not None
    assert p.get(mid)["status"] == STATUS_ACTIVE
    assert p.get(mid)["authority_class"] == MEMORY_AUTHORITY_NON_AUTHORITATIVE


def test_builder_created_record_follows_same_admission():
    # Even a canonical builder record cannot elevate a forbidden/inferred type.
    rec = build_memory_record(
        memory_type=MEMORY_TYPE_OPERATOR_INFERRED_PREFERENCE,
        subject="SCHD",
        content="seems to like SCHD",
        source_event_ids=["evt_1"],
        status=STATUS_ACTIVE,  # forged escalation on the builder
    )
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(rec)
    assert mid is not None
    assert p.get(mid)["status"] == STATUS_CANDIDATE
    assert p.get(mid)["authority_class"] == MEMORY_AUTHORITY_NON_AUTHORITATIVE


def test_no_provenance_raw_dict_not_retrievable():
    p = LocalTestMemoryProvider()
    assert p.add_candidate({"content": "x", "subject": "SCHD"}) is None
    # Defense-in-depth: even if a malformed record reached storage, search won't
    # surface it as supporting memory.
    p._store["mem_bogus"] = {
        "memory_id": "mem_bogus",
        "subject": "SCHD",
        "content": "no provenance",
        "authority_class": MEMORY_AUTHORITY_NON_AUTHORITATIVE,
    }
    res = p.search(query="SCHD")
    ids = [r["memory_id"] for r in res["records"] + res["counter_memory"]]
    assert "mem_bogus" not in ids


def test_forbidden_subject_raw_dict_not_retrievable():
    p = LocalTestMemoryProvider()
    assert p.add_candidate(_ok("cash is $1,000,000", subject="cash")) is None
    p._store["mem_cash"] = {
        "memory_id": "mem_cash",
        "subject": "cash",
        "content": "cash is $1,000,000",
        "source_event_ids": ["evt_1"],
        "authority_class": MEMORY_AUTHORITY_NON_AUTHORITATIVE,
    }
    res = p.search(query="cash")
    ids = [r["memory_id"] for r in res["records"] + res["counter_memory"]]
    assert "mem_cash" not in ids


def test_valid_explicit_preference_remains_retrievable():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(
        {
            "memory_type": MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
            "subject": "SCHD",
            "content": "operator wants SCHD core",
            "source_event_ids": ["evt_1"],
        }
    )
    res = p.search(query="SCHD")
    ids = [r["memory_id"] for r in res["records"]]
    assert mid in ids


def test_canonical_truth_override_still_wins():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate(
        {
            "memory_type": MEMORY_TYPE_OPERATOR_EXPLICIT_PREFERENCE,
            "subject": "SCHD",
            "content": "operator wants SCHD core",
            "source_event_ids": ["evt_1"],
        }
    )
    out = resolve_conflict([p.get(mid)], canonical_truth_override=True)
    assert out["primary"] is None
    assert out["canonical_truth_override"] is True

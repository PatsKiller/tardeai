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

from scripts.lib.agent_context_envelope import RETRIEVAL_NOT_CONFIGURED  # noqa: E402
from scripts.lib.agent_memory_provider import (  # noqa: E402
    LocalTestMemoryProvider,
    NullMemoryProvider,
)
from scripts.lib.agent_mem0_provider import (  # noqa: E402
    MEM0_DUE_DILIGENCE,
    MEMORY_BEHAVIOR_INFLUENCE,
    MEMORY_PROVIDER,
    MEMORY_SHADOW,
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


def test_local_add_get_dispute_expire_round_trip():
    p = LocalTestMemoryProvider()
    mid = p.add_candidate({"content": "op prefers SCHD", "subject": "SCHD", "confidence": 0.9})
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
    a = p.add_candidate({"content": "keep SCHD", "subject": "SCHD", "confidence": 0.9})
    p.add_candidate({"content": "reduce SCHD", "subject": "SCHD", "contradicts": [a]})
    res = p.search(query="SCHD")
    assert len(res["records"]) >= 1
    assert len(res["counter_memory"]) >= 1


def test_local_health_ok():
    p = LocalTestMemoryProvider()
    p.add_candidate({"content": "hello", "subject": "greeting"})
    h = p.health()
    assert h["status"] == "OK"
    assert h["memory_count"] == 1


# ── Shadow flags: conservative by default ────────────────────────────────


def test_shadow_flags_conservative():
    assert MEMORY_SHADOW == 1
    assert MEMORY_BEHAVIOR_INFLUENCE == 0
    assert MEMORY_PROVIDER == "local"

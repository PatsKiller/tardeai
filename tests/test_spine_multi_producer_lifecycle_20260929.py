"""Multi-producer SecurityResearchSpine — not Hermes-only; tagged full lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest

REG = "ecb5ba89-96c6-536c-ba76-89e468a81bf1"
ISSUER = "8dfc96ee-0000-5000-8000-000000000001"


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch):
    def _resolve(symbol: str, *, root=None):
        sym = str(symbol or "").upper()
        if sym != "NFLX":
            return {
                "symbol": sym or None,
                "subject_guid": None,
                "issuer_guid": None,
                "security_guid": None,
                "identity_status": "UNRESOLVED",
                "identity_lookup": "UNRESOLVED",
            }
        return {
            "symbol": "NFLX",
            "subject_guid": REG,
            "issuer_guid": ISSUER,
            "security_guid": REG,
            "identity_status": "CONFIRMED",
            "identity_lookup": "RESOLVED",
        }

    monkeypatch.setattr("scripts.lib.identity_carriage.resolve_security_identity", _resolve)
    return _resolve


@pytest.fixture()
def spine_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CROSS_ASSET_SPINE", "1")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)


def test_upsert_research_memory_accumulates_multi_tags(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.security_research_spine import upsert_research_memory, view_for_silo
    from scripts.lib.identity_carriage import is_registry_guid

    upsert_research_memory(
        "NFLX",
        silo="hermes",
        kind="research_result",
        summary="Hermes thesis on NFLX",
        tags=["hermes", "lifecycle"],
        root=tmp_path,
    )
    upsert_research_memory(
        "NFLX",
        silo="cio",
        kind="operator_answered",
        summary="Operator asked about NFLX entry",
        tags=["operator_qa", "operator_ask", "lifecycle"],
        root=tmp_path,
    )
    upsert_research_memory(
        "NFLX",
        silo="cio",
        kind="thesis_publish",
        summary="Desk thesis v3",
        tags=["thesis", "llm_research", "lifecycle"],
        root=tmp_path,
    )
    v = view_for_silo("NFLX", "options_desk", root=tmp_path)
    assert v.get("found") is True
    assert is_registry_guid(v.get("subject_guid"))
    tags = set(v.get("tags") or [])
    assert {"hermes", "operator_qa", "thesis", "lifecycle"} <= tags


def test_notify_operator_desk_result_writes_spine(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.hooks import notify_operator_desk_result
    from scripts.lib.cross_asset.security_research_spine import view_for_silo

    out = notify_operator_desk_result(
        {"symbols": ["NFLX"], "intent": "freeform"},
        {
            "kind": "answered",
            "text": "NFLX looks extended; wait for pullback.",
            "pending_id": "opr_test123",
            "reply_source": "test",
        },
        root=tmp_path,
    )
    assert out.get("ok") is True
    assert out.get("written") == 1
    v = view_for_silo("NFLX", "cio", root=tmp_path)
    assert v.get("found") is True
    assert "operator_qa" in (v.get("tags") or [])
    assert (v.get("latest_operator") or {}).get("pending_id") == "opr_test123"


def test_notify_thesis_published_writes_linked_symbols(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.hooks import notify_thesis_published
    from scripts.lib.cross_asset.security_research_spine import view_for_silo

    out = notify_thesis_published(
        {
            "thesis_id": "sym-nflx",
            "thesis_version": "sym-nflx@v1",
            "summary": "NFLX concentration watch",
            "linked_symbols": ["NFLX"],
            "subject_guid": REG,
            "stance": "WATCH",
        },
        root=tmp_path,
    )
    assert out.get("written") == 1
    v = view_for_silo("NFLX", "holdings", root=tmp_path)
    assert v.get("found") is True
    assert "thesis" in (v.get("tags") or [])


def test_spine_write_gated_when_flag_off(registry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("CROSS_ASSET_SPINE", "0")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)
    from scripts.lib.cross_asset.hooks import notify_operator_desk_result

    out = notify_operator_desk_result(
        {"symbols": ["NFLX"]},
        {"kind": "answered", "text": "hi"},
        root=tmp_path,
    )
    assert out.get("skipped") is True
    assert out.get("reason") == "CROSS_ASSET_SPINE_off"


def test_source_gates_multi_producer_wired():
    root = Path(__file__).resolve().parents[1]
    checks = {
        "scripts/lib/cross_asset/security_research_spine.py": "upsert_research_memory",
        "scripts/lib/cross_asset/hooks.py": "notify_operator_desk_result",
        "scripts/lib/cross_asset/hooks.py": "notify_thesis_published",
        "scripts/lib/cio_operator_desk_loop.py": "notify_operator_desk_result",
        "scripts/lib/cio_theses.py": "notify_thesis_published",
        "scripts/ops/backfill_security_research_spine.py": "upsert_from_hermes",
    }
    # dict literal overwrites duplicate keys — check explicitly
    assert "notify_operator_desk_result" in (root / "scripts/lib/cross_asset/hooks.py").read_text()
    assert "notify_thesis_published" in (root / "scripts/lib/cross_asset/hooks.py").read_text()
    assert "upsert_research_memory" in (root / "scripts/lib/cross_asset/security_research_spine.py").read_text()
    assert "notify_operator_desk_result" in (root / "scripts/lib/cio_operator_desk_loop.py").read_text()
    assert "notify_thesis_published" in (root / "scripts/lib/cio_theses.py").read_text()
    assert "upsert_from_hermes" in (root / "scripts/ops/backfill_security_research_spine.py").read_text()

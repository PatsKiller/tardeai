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


def test_notify_llm_curation_tags_and_owner(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.hooks import notify_llm_curation, notify_thesis_published
    from scripts.lib.cross_asset.security_research_spine import view_for_silo

    # Seed a house thesis tip first so LLM does not become the tip thesis.
    notify_thesis_published(
        {
            "thesis_id": "sym-nflx",
            "thesis_version": "sym-nflx@v1",
            "summary": "House thesis: concentration watch",
            "linked_symbols": ["NFLX"],
            "subject_guid": REG,
            "stance": "WATCH",
        },
        root=tmp_path,
    )
    out = notify_llm_curation(
        ["NFLX"],
        text="LLM rewrite of gathered evidence on NFLX — not a fact.",
        source="llm_curation",
        model="deepseek-chat",
        curated_from=["brave_hits", "hermes_partial"],
        root=tmp_path,
    )
    assert out.get("ok") is True
    assert out.get("owner") == "cio"
    assert "llm_curation" in (out.get("tags") or [])
    assert "llm_research" in (out.get("tags") or [])
    assert "deepseek" in (out.get("tags") or [])
    v = view_for_silo("NFLX", "cio", root=tmp_path)
    assert v.get("found") is True
    assert v.get("owner") == "cio"
    assert "llm_curation" in (v.get("tags") or [])
    assert "llm_research" in (v.get("tags") or [])
    llm = v.get("latest_llm") or {}
    assert llm.get("source") == "llm_curation"
    assert llm.get("model") == "deepseek-chat"
    # Tip thesis remains house, not LLM rewrite.
    assert "House thesis" in str((v.get("thesis") or {}).get("summary") or "")
    assert "LLM rewrite" not in str((v.get("thesis") or {}).get("summary") or "")


def test_notify_llm_flash_tag(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.hooks import notify_llm_curation
    from scripts.lib.cross_asset.security_research_spine import view_for_silo

    notify_llm_curation(
        ["NFLX"],
        text="Flash answer on NFLX.",
        source="deepseek_flash",
        model="deepseek-flash",
        root=tmp_path,
    )
    v = view_for_silo("NFLX", "aegis", root=tmp_path)
    tags = set(v.get("tags") or [])
    assert {"llm_research", "llm_flash", "deepseek", "lifecycle"} <= tags
    assert (v.get("latest_llm") or {}).get("source") == "deepseek_flash"


def test_source_gates_multi_producer_wired():
    root = Path(__file__).resolve().parents[1]
    assert "notify_operator_desk_result" in (root / "scripts/lib/cross_asset/hooks.py").read_text()
    assert "notify_thesis_published" in (root / "scripts/lib/cross_asset/hooks.py").read_text()
    assert "notify_llm_curation" in (root / "scripts/lib/cross_asset/hooks.py").read_text()
    assert "upsert_research_memory" in (root / "scripts/lib/cross_asset/security_research_spine.py").read_text()
    assert "notify_operator_desk_result" in (root / "scripts/lib/cio_operator_desk_loop.py").read_text()
    assert "notify_llm_curation" in (root / "scripts/lib/cio_operator_desk_loop.py").read_text()
    assert "notify_llm_curation" in (root / "scripts/lib/gap_resolver.py").read_text()
    assert "pending_fulfilled" in (root / "scripts/lib/cio_operator_desk_loop.py").read_text()
    assert "notify_thesis_published" in (root / "scripts/lib/cio_theses.py").read_text()
    assert "upsert_from_hermes" in (root / "scripts/ops/backfill_security_research_spine.py").read_text()
    assert 'view_for_silo(sym, "aegis"' in (root / "scripts/aegis_synthesis.py").read_text()
    assert "latest_llm" in (root / "scripts/aegis_synthesis.py").read_text()
    assert "operator_asks" in (
        root / "scripts/lib/cross_asset/security_research_spine.py"
    ).read_text()
    assert "symbol_thesis_sla" in (root / "scripts/lib/cio_operator_desk_loop.py").read_text()
    assert "spine_fresh" in (root / "scripts/lib/cross_asset/hooks.py").read_text()
    assert "refuse_fresh_claim" in (
        root / "scripts/lib/cross_asset/security_research_spine.py"
    ).read_text()
    assert "spine_write_enabled" in (
        root / "scripts/lib/cross_asset/events.py"
    ).read_text()
    assert 'os.environ.get("CROSS_ASSET_SPINE", "1")' in (
        root / "scripts/lib/cross_asset/events.py"
    ).read_text()

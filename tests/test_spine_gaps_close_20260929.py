"""Residual spine gap closure — SLA enqueue, sector ETF proxy, organic metric."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REG = "ecb5ba89-96c6-536c-ba76-89e468a81bf1"
ISSUER = "8dfc96ee-0000-5000-8000-000000000001"
XLK_REG = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch):
    def _resolve(symbol: str, *, root=None):
        sym = str(symbol or "").upper()
        if sym == "NFLX":
            return {
                "symbol": "NFLX",
                "subject_guid": REG,
                "issuer_guid": ISSUER,
                "security_guid": REG,
                "identity_status": "CONFIRMED",
                "identity_lookup": "RESOLVED",
            }
        if sym == "XLK":
            return {
                "symbol": "XLK",
                "subject_guid": XLK_REG,
                "issuer_guid": ISSUER,
                "security_guid": XLK_REG,
                "identity_status": "CONFIRMED",
                "identity_lookup": "RESOLVED",
            }
        return {
            "symbol": sym or None,
            "subject_guid": None,
            "issuer_guid": None,
            "security_guid": None,
            "identity_status": "UNRESOLVED",
            "identity_lookup": "UNRESOLVED",
        }

    monkeypatch.setattr("scripts.lib.identity_carriage.resolve_security_identity", _resolve)
    return _resolve


@pytest.fixture()
def spine_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CROSS_ASSET_SPINE", "1")
    monkeypatch.delenv("CROSS_ASSET_SHADOW", raising=False)


def test_spine_sla_enqueue_selects_stale_tip(registry, spine_on, tmp_path: Path, monkeypatch):
    from scripts.lib.cross_asset.hooks import notify_thesis_published
    from scripts.lib.cross_asset import spine_sla_enqueue as sse
    from scripts.lib.cross_asset.security_research_spine import load_latest, append_spine

    sse.reset_dedupe_for_tests()
    monkeypatch.setenv("SPINE_SLA_ENQUEUE_MAX_PER_DAY", "8")

    notify_thesis_published(
        {
            "thesis_id": "sym-nflx",
            "thesis_version": "sym-nflx@v1",
            "summary": "old tip",
            "linked_symbols": ["NFLX"],
            "subject_guid": REG,
        },
        root=tmp_path,
    )
    tip = load_latest("NFLX", root=tmp_path)
    assert tip
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat().replace("+00:00", "Z")
    tip["as_of"] = old
    append_spine(tip, root=tmp_path)

    called: list = []

    def _fake_enq(**kwargs):
        called.append(kwargs)
        return {"ok": True, "emitted": 1}

    dry = sse.enqueue_spine_sla_breaches(["NFLX"], root=tmp_path, apply=False)
    assert dry.get("selected") == 1
    assert dry.get("symbols") == ["NFLX"]
    assert dry.get("dry_run") is True

    live = sse.enqueue_spine_sla_breaches(
        ["NFLX"], root=tmp_path, apply=True, enqueue_fn=_fake_enq
    )
    assert live.get("selected") == 1
    assert len(called) == 1
    assert called[0]["symbols"] == ["NFLX"]

    # Dedupe: second apply same day should skip
    live2 = sse.enqueue_spine_sla_breaches(
        ["NFLX"], root=tmp_path, apply=True, enqueue_fn=_fake_enq
    )
    assert live2.get("selected") == 0
    assert len(called) == 1


def test_spine_sla_enqueue_skips_fresh(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.hooks import notify_thesis_published
    from scripts.lib.cross_asset import spine_sla_enqueue as sse

    sse.reset_dedupe_for_tests()
    notify_thesis_published(
        {
            "thesis_id": "sym-nflx",
            "thesis_version": "sym-nflx@v1",
            "summary": "fresh tip",
            "linked_symbols": ["NFLX"],
            "subject_guid": REG,
        },
        root=tmp_path,
    )
    out = sse.enqueue_spine_sla_breaches(["NFLX"], root=tmp_path, apply=False)
    assert out.get("candidates") == 0
    assert out.get("selected") == 0


def test_notify_sector_research_etf_proxy(registry, spine_on, tmp_path: Path, monkeypatch):
    from scripts.lib.cross_asset.hooks import notify_sector_research, sector_etf_proxy
    from scripts.lib.cross_asset.security_research_spine import view_for_silo

    assert sector_etf_proxy("Technology") == "XLK"

    monkeypatch.setattr(
        "scripts.lib.cio_narrative_subjects.resolve_subject",
        lambda et, name, **kw: {
            "guid": "11111111-2222-4333-8444-555555555555",
            "semantic_subject": "Technology",
            "entity_type": "SECTOR",
        },
    )
    out = notify_sector_research(
        "Technology",
        summary="Sector move: Tech relative strength rising",
        root=tmp_path,
    )
    assert out.get("ok") is True
    assert out.get("etf_proxy") == "XLK"
    v = view_for_silo("XLK", "cio", root=tmp_path)
    assert v.get("found") is True
    tags = set(v.get("tags") or [])
    assert "sector" in tags
    assert "sector_subject" in tags


def test_organic_metric_separates_canary(registry, spine_on, tmp_path: Path):
    from scripts.lib.cross_asset.hooks import notify_llm_curation
    from scripts.ops.spine_llm_organic_metric import measure

    notify_llm_curation(
        ["NFLX"],
        text="organic-looking but tagged canary",
        source="deepseek_flash",
        model="x",
        root=tmp_path,
        extra_tags=["canary"],
    )
    m = measure(tmp_path)
    assert m["organic_latest_llm"] == 0
    assert m["canary_or_backfill_latest_llm"] == 1

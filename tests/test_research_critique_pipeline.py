"""Tests for librarian + taxonomy critique scoring."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "research_critique_pipeline", ROOT / "scripts" / "research_critique_pipeline.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_librarian_rejects_generic_label():
    mod = _load()
    out = mod.librarian_score(
        kind="trend",
        label="trend earnings",
        spec={"keywords": ["earnings"]},
    )
    assert out["librarian_verdict"] in ("review", "reject")
    assert out["librarian_score"] < 65


def test_librarian_approves_sector_with_rs():
    mod = _load()
    out = mod.librarian_score(
        kind="sector",
        label="sector Technology",
        spec={
            "finviz_sector": "Technology",
            "keywords": ["Technology sector", "relative strength", "XLK", "semiconductor"],
            "seed_symbols": ["NVDA", "AMD"],
            "change_pct": 1.2,
            "think_tank_source": "sector_universe",
        },
    )
    assert out["librarian_score"] >= 65
    assert out["librarian_verdict"] == "approve"


def test_taxonomy_scores_market_industry():
    mod = _load()
    out = mod.taxonomy_score(
        kind="trend",
        label="industry Software - Application",
        spec={
            "finviz_industry": "Software - Application",
            "keywords": ["software", "application", "cloud"],
            "think_tank_source": "sector_universe_industry",
        },
    )
    assert out["taxonomy_score"] >= 38
    assert "taxonomy_tags" in out


def test_composite_score_blend():
    mod = _load()
    comp = mod.composite_score(
        {"librarian_score": 80},
        {"taxonomy_score": 60},
    )
    assert comp["composite_score"] == round(80 * 0.55 + 60 * 0.45, 1)
    assert comp["composite_verdict"] == "approve"


def test_directive_stale_ttl_and_generic():
    mod = _load()
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 6, 24, tzinfo=timezone.utc)
    reasons = mod.directive_stale_reasons(
        label="trend earnings",
        spec={"composite_verdict": "review", "composite_score": 45},
        status="active",
        ttl_days=90,
        created_at=now - timedelta(days=100),
        updated_at=now - timedelta(days=40),
        last_serviced_at=None,
        cold_since=None,
        hits_30d=0,
        now=now,
    )
    assert any("TTL expired" in r for r in reasons)
    assert any("Generic pipeline label" in r for r in reasons)


def test_staging_stale_undrained():
    mod = _load()
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 6, 24, tzinfo=timezone.utc)
    reasons = mod.staging_stale_reasons(
        proposed_at=now - timedelta(days=25),
        directive_status="active",
        source_detail={"composite_verdict": "reject", "composite_score": 38},
        now=now,
    )
    assert any("Undrained" in r for r in reasons)
    assert any("reject" in r for r in reasons)


def test_extract_critique_fields_and_snapshot(tmp_path, monkeypatch):
    mod = _load()
    spec = {
        "keywords": ["defense"],
        "librarian_score": 72.0,
        "composite_verdict": "approve",
        "librarian_stale_flag": True,
        "stale_reasons": ["TTL expired"],
    }
    out = mod.extract_critique_fields(spec)
    assert out["librarian_score"] == 72.0
    assert out["librarian_stale_flag"] is True
    assert mod.is_removal_flagged(spec)

    latest = tmp_path / "research_critique_latest.json"
    monkeypatch.setattr(mod, "CRITIQUE_LATEST", latest)
    latest.write_text('{"updated_at":"2026-06-24T00:00:00+00:00","summary":{"stale_flagged_total":2}}')
    snap = mod.load_critique_snapshot()
    assert snap["summary"]["stale_flagged_total"] == 2


def test_curator_creators_constant():
    mod = _load()
    assert "think_tank" in mod.CURATOR_CREATORS
    assert "operator" not in mod.CURATOR_CREATORS


def test_retention_constants_ordered():
    mod = _load()
    assert mod.RETENTION_STAGING_DAYS < mod.RETENTION_RESEARCH_DAYS
    assert mod.RETENTION_RESEARCH_DAYS <= mod.RETENTION_DIRECTIVE_DAYS


def test_research_stale_freshness():
    mod = _load()
    from datetime import date, datetime, timezone

    reasons = mod.research_stale_reasons(
        freshness_date=date(2026, 5, 1),
        confidence_score=0.5,
        status="promoted",
        created_at=None,
        now=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    assert reasons and "Freshness date" in reasons[0]
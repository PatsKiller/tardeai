"""LQ-20261107-244: a research brief with no sources must read as unsourced, not complete.

Synthetic rows only (no DB, no network).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib import research_intelligence as ri  # noqa: E402


def _row(i, **kw):
    base = {"id": i, "topic": f"Synthetic topic {i}", "summary": "A synthetic summary sentence.",
            "thesis": "A synthetic thesis.", "symbol": None, "research_type": "general",
            "confidence_score": 0.5, "quality_score": 0.5, "status": "active", "model_used": "other",
            "source": "x", "created_at": None, "freshness_date": None, "evidence_json": None,
            "source_urls_json": None, "tags": None, "category_content": None,
            "category_sector": None, "updated_at": None}
    base.update(kw)
    return base


def _feed(rows):
    def db_query(sql, *a, **k):
        return rows if "hermes_research_intelligence" in sql and "FROM hermes" in sql else []
    return {it["source_id"]: it for it in ri.build_feed(db_query=db_query, limit=50)["items"]
            if it.get("source_table") == "hermes_research_intelligence"}


def test_sources_from_row_drops_empty_entries():
    row = _row(1, evidence_json={"grounded_on": [{"title": None, "url": None, "source": "x"}]},
               source_urls_json=[{}])
    assert ri._sources_from_row(row) == []


def test_unsourced_brief_is_marked_and_sourced_is_not():
    items = _feed([
        _row(1),
        _row(2, evidence_json={"grounded_on": [{"title": "T", "url": "https://example.test/a"}]}),
        _row(3, evidence_json={"grounded_on": [{"title": None, "url": None}]}),
    ])
    assert items[1]["source_status"] == "unsourced" and items[1]["source_count"] == 0
    assert items[2]["source_status"] == "sourced" and items[2]["source_count"] == 1
    assert items[3]["source_status"] == "unsourced" and items[3]["source_count"] == 0


def test_withheld_brief_is_unsourced():
    items = _feed([_row(4, model_used="synth:x", evidence_json={"grounded_count": 0},
                        source_urls_json=["https://example.test/b"])])
    assert items[4]["source_status"] == "unsourced"


def test_hub_shows_unsourced():
    src = (ROOT / "apps/command-center-v3/src/pages/ResearchIntelligenceHub.tsx").read_text()
    assert "source_status" in src and "No sources" in src

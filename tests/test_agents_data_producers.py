"""AGENTS.md §13.6 operator surface data producers must stay discoverable."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "AGENTS.md"


def _section_136() -> str:
    text = HUB.read_text(encoding="utf-8")
    start = text.index("## 13.6 · Operator surface data producers")
    end = text.index("# 14 · Documentation standards", start)
    return text[start:end]


def test_section_136_exists_after_prebuild_check():
    text = HUB.read_text(encoding="utf-8")
    assert text.index("## 13.5 · Pre-build check") < text.index("## 13.6 · Operator surface data producers")
    assert "## 13.6 · Operator surface data producers" in text


def test_section_136_covers_finviz_auth_and_paths():
    body = _section_136()
    for keyword in (
        "FINVIZ_COOKIE",
        "FINVIZ_API_TOKEN",
        "&auth=",
        "finviz_ingestion.py",
        "finviz_enrichment.py",
        "social_ingest",
        "social_scalp",
        "heal_trade_ai_session_cache",
        "never auto-remediate divergent copies",
        "STALE_DATA_RCA_AND_REMEDIATION_PLAN_2026-09-01.md",
    ):
        assert keyword in body, keyword

"""Taxonomy retirement tests — content_subject path is a no-op.

Confirms the retired DB-writing functions return "retired" status and that the
harmless classifier still works via keyword fallback (no network, no DB).
"""
from __future__ import annotations

from scripts.lib.hermes_librarian import taxonomy


class TestRetirement:
    def test_backfill_content_tags_is_retired(self):
        result = taxonomy.backfill_content_tags(None)
        assert result["status"] == "retired"
        assert "strategy_tags" in result["note"]

    def test_retire_tag_is_noop(self):
        assert taxonomy.retire_tag(None, "earnings", "low efficacy") is False

    def test_content_tag_efficacy_empty(self):
        assert taxonomy.content_tag_efficacy(None) == {}

    def test_classify_content_keyword_fallback(self):
        # prefer_llm=False forces keyword path — no network, no Ollama dependency
        tags = taxonomy.classify_content(
            "Company reported strong quarterly earnings and raised guidance",
            prefer_llm=False,
        )
        assert isinstance(tags, list)
        assert "earnings" in tags

    def test_classify_short_text_returns_empty(self):
        assert taxonomy.classify_content("too short", prefer_llm=False) == []

"""Deterministic tests for the RAG job-coverage schedule matcher (R7.1).

Regression: rag_embeddings was registered with schedule_match='embedding', but the
canonical RAG indexer (rag_indexer.py) runs every 4h via cron and never emits the
literal token 'embedding' in its active line — so the monitor reported NOT_SCHEDULED
despite the job being scheduled and healthy. The matcher must recognize the real
cron entry, report NOT_SCHEDULED when it is absent, and never false-pass on an
unrelated 'embedding' string.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import job_coverage_monitor as m  # noqa: E402

REAL_RAG_CRON = (
    "0 */4 * * * cd $PROJ && bash $PROJ/scripts/llm_priority_guard.sh "
    "&& timeout 5m $PY scripts/rag_indexer.py >> logs/rag_indexer.log 2>&1"
)


def _rag_entry():
    for j in m.REGISTRY:
        if j["name"] == "rag_embeddings":
            return j
    raise AssertionError("rag_embeddings entry missing from REGISTRY")


def test_rag_entry_matches_real_indexer():
    assert _rag_entry()["schedule_match"] == "rag_indexer.py"


def test_real_rag_cron_is_scheduled():
    assert m._is_scheduled("rag_indexer.py", [REAL_RAG_CRON]) is True


def test_missing_rag_cron_is_not_scheduled():
    assert m._is_scheduled("rag_indexer.py", []) is False
    # A crontab that has other jobs but not the RAG indexer must not pass.
    assert m._is_scheduled(
        "rag_indexer.py",
        ["0 6 * * * cd $PROJ && $PY scripts/news_ingestion.py >> logs/news.log 2>&1"],
    ) is False


def test_unrelated_embedding_text_does_not_false_pass():
    # The old matcher ('embedding') false-passed on anything mentioning embeddings,
    # yet real rag_indexer cron had no such token — the exact bug. Guard both halves:
    # (a) 'embedding' must NOT count as the rag_indexer match, and
    # (b) the real cron line (which lacks 'embedding') must still be recognized.
    comment_only = ["# Taxonomy tag-forward keeps content_embeddings categorized"]
    assert m._is_scheduled("rag_indexer.py", comment_only) is False
    assert "embedding" not in REAL_RAG_CRON

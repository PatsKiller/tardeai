"""The maturity board must see every agent, not just the chatty one — 2026-09-15.

Measured on the LAB database: agent_runs held 3,789 rows ordered started_at DESC, of which
concierge owned 2,553. collect_runtime_evidence paged a single global window of 2,000 runs,
so concierge (row 1) and atlas (row 5) were scanned and every other agent — argus 3,717,
darwin 3,754, reflection 3,765, iris 3,772, sentinel 3,776, watch_producer_shadow 3,787 —
fell outside it. The board therefore reported REPOSITORY_EVIDENCE / sample_size null for all
four MVL agents while their evidence sat in the database. Discovery is now metadata-only and
the expensive per-run detail work is bounded PER AGENT.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.maturity_observability import collect_runtime_evidence  # noqa: E402


class FakeReader:
    """Newest-first run listing, like the Postgres reader's ORDER BY started_at DESC."""

    def __init__(self, runs, artifacts=None, reviews=None, scores=None):
        self._runs = list(runs)
        self._artifacts = artifacts or {}
        self._reviews = reviews or {}
        self._scores = scores or {}
        self.detail_calls: dict[str, int] = {}

    def list_runs(self, *, limit, offset, agent_id=None, status=None):
        rows = [r for r in self._runs if agent_id in (None, r["agent_id"])]
        return rows[offset:offset + limit]

    def _count(self, run_id):
        self.detail_calls[run_id] = self.detail_calls.get(run_id, 0) + 1

    def list_artifacts(self, run_id):
        self._count(run_id)
        return self._artifacts.get(run_id, [])

    def list_reviews(self, run_id):
        return self._reviews.get(run_id, [])

    def list_scores(self, run_id):
        return self._scores.get(run_id, [])


def _chatty_fleet(chatty_runs: int = 2600):
    """One agent with thousands of runs, then a critic whose only run sorts dead last."""
    runs, artifacts = [], {}
    for i in range(chatty_runs):
        rid = f"run_chatty_{i:05d}"
        runs.append({"run_id": rid, "agent_id": "concierge"})
        artifacts[rid] = [{"artifact_id": f"art_chatty_{i:05d}", "producer_agent_id": "concierge"}]
    runs.append({"run_id": "run_producer", "agent_id": "watch_producer_shadow"})
    artifacts["run_producer"] = [{"artifact_id": "art_watch", "producer_agent_id": "watch_producer_shadow"}]
    reviews = {"run_producer": [{"artifact_id": "art_watch", "reviewer_agent_id": "sentinel_shadow",
                                 "verdict": "pass", "created_at": "2026-07-27T00:00:00Z"}]}
    scores = {"run_producer": [{"artifact_id": "art_watch", "scorer_agent_id": "darwin_shadow",
                                "created_at": "2026-07-27T00:00:00Z"}]}
    return FakeReader(runs, artifacts, reviews, scores)


def test_a_chatty_agent_no_longer_hides_every_other_agent():
    reader = _chatty_fleet()
    evidence, _reviews = collect_runtime_evidence(reader)
    assert "concierge" in evidence
    assert "sentinel" in evidence, "critic's evidence was buried behind the chatty agent's runs"
    assert "darwin" in evidence
    assert "watch_producer" in evidence or "watch_producer_shadow" in evidence


def test_detail_queries_are_bounded_per_agent_not_globally():
    reader = _chatty_fleet()
    collect_runtime_evidence(reader, per_agent_runs=50)
    chatty = [r for r in reader.detail_calls if r.startswith("run_chatty_")]
    assert len(chatty) == 50, f"expected 50 chatty runs scanned, got {len(chatty)}"
    assert "run_producer" in reader.detail_calls, "the last-sorting agent must still be scanned"


def test_sample_size_counts_distinct_artifacts_the_agent_touched():
    reader = _chatty_fleet(chatty_runs=3)
    evidence, _ = collect_runtime_evidence(reader)
    assert evidence["concierge"]["sample_size"] == 3
    assert evidence["sentinel"]["sample_size"] == 1
    assert evidence["sentinel"]["source_class"] == "RUNTIME_EVIDENCE"


def test_framework_gates_are_never_claimed_complete_from_the_read_plane():
    evidence, _ = collect_runtime_evidence(_chatty_fleet(chatty_runs=2))
    for agent, rec in evidence.items():
        assert rec["framework_gates_complete"] is False, agent
        assert rec["effective_production_activation_verified"] is False, agent


def test_no_reader_and_empty_reader_stay_repository_evidence():
    assert collect_runtime_evidence(None) == ({}, {})
    assert collect_runtime_evidence(FakeReader([])) == ({}, {})


def test_a_reader_that_raises_never_crashes_the_board():
    class Broken(FakeReader):
        def list_runs(self, **kw):
            raise RuntimeError("reader hiccup")

    assert collect_runtime_evidence(Broken([])) == ({}, {})

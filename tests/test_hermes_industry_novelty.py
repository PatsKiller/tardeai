#!/usr/bin/env python3
"""Industry/sector novelty discovery test suite.

Pure synthetic-data tests — the DB seam (industry_novelty._execute) and the
inbox write path are monkeypatched, so the suite runs under TRADE_AI_CI with no
PostgreSQL. Covers BOTH directions the plan requires: a news-prominent uncovered
sector → one GAP_CANDIDATE, and an already-covered sector → no candidate/noise.

    .venv/bin/python -m pytest tests/test_hermes_industry_novelty.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import dedupe, industry_novelty as N  # noqa: E402


def _obs(value, n=5, n_sources=3, sources=None):
    return {"entity_value": value, "n": n, "n_sources": n_sources,
            "sources": sources or [f"src{i}" for i in range(n_sources)],
            "sample": f"news about {value}"}


COVERED = {dedupe.normalize_key("Technology"), dedupe.normalize_key("Energy")}


# ── POSITIVE: news-prominent uncovered sector becomes a candidate ────────────

def test_novel_sector_detected():
    novel = N.compute_novel([_obs("space economy", n=6, n_sources=4)], COVERED)
    assert len(novel) == 1
    assert novel[0]["sector"] == "space economy"

    payloads = N.build_payloads(novel, limit=5)
    assert len(payloads) == 1
    p = payloads[0]
    assert p["candidate_type"] == "GAP_CANDIDATE"
    assert p["meta"]["gap_type"] == "MISSING_SECTOR"
    assert p["meta"]["lane"] == "industry_novelty"
    assert p["safe_action_level"] == "OPERATOR_REVIEW_REQUIRED"


# ── NEGATIVE: an already-covered sector produces nothing ─────────────────────

def test_covered_sector_produces_no_candidate():
    skipped = {}
    novel = N.compute_novel([_obs("Technology", n=20, n_sources=6)], COVERED,
                            skipped=skipped)
    assert novel == []
    assert skipped.get("already_covered") == 1


def test_low_recurrence_and_single_source_skipped():
    skipped = {}
    novel = N.compute_novel(
        [_obs("rare theme", n=1, n_sources=3),        # below min_mentions
         _obs("one outlet", n=8, n_sources=1)],        # below min_sources
        COVERED, min_mentions=3, min_sources=2, skipped=skipped)
    assert novel == []
    assert skipped.get("low_recurrence") == 1
    assert skipped.get("low_cross_source") == 1


def test_max_per_day_cap_enforced():
    novel = N.compute_novel(
        [_obs(f"novel theme {i}", n=5, n_sources=3) for i in range(10)], COVERED)
    skipped = {}
    payloads = N.build_payloads(novel, limit=3, skipped=skipped)
    assert len(payloads) == 3
    assert skipped.get("run_cap") == 7


def test_duplicate_in_run_deduped():
    skipped = {}
    novel = N.compute_novel([_obs("space economy"), _obs("Space  Economy")],
                            COVERED, skipped=skipped)
    assert len(novel) == 1
    assert skipped.get("duplicate_in_run") == 1


# ── run_discovery: shadow-first (writes nothing while disabled) ──────────────

def test_run_discovery_shadow_first(monkeypatch):
    monkeypatch.setattr(N, "collect_observed_sectors",
                        lambda *a, **k: [_obs("space economy", n=6, n_sources=4)])
    monkeypatch.setattr(N, "covered_sector_keys", lambda *a, **k: COVERED)

    def _boom(*a, **k):
        raise AssertionError("must not write while disabled")
    monkeypatch.setattr(N.inbox, "upsert_candidate", _boom)

    rep = N.run_discovery(dry_run=False)   # config default: disabled
    assert rep["effective_dry_run"] is True
    assert rep["upserted"] == 0
    assert rep["would_upsert"] == 1
    assert any("industry_novelty_enabled=false" in n for n in rep["notes"])


def test_run_discovery_writes_when_enabled(monkeypatch, tmp_path):
    cfg = tmp_path / "sched.json"
    cfg.write_text('{"industry_novelty_enabled": true, '
                   '"industry_novelty_min_mentions": 3, '
                   '"industry_novelty_min_sources": 2}')
    monkeypatch.setattr(N, "collect_observed_sectors",
                        lambda *a, **k: [_obs("space economy", n=6, n_sources=4)])
    monkeypatch.setattr(N, "covered_sector_keys", lambda *a, **k: COVERED)
    calls = []
    monkeypatch.setattr(N.inbox, "upsert_candidate",
                        lambda **p: calls.append(p) or {"id": 7, "status": "READY_FOR_REVIEW",
                                                        "seen_count": 1})
    rep = N.run_discovery(dry_run=False, config_path=cfg)
    assert rep["effective_dry_run"] is False
    assert rep["upserted"] == 1
    assert calls[0]["actor"] == N.ACTOR
    assert calls[0]["meta"]["gap_type"] == "MISSING_SECTOR"

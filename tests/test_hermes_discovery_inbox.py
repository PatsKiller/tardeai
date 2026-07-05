#!/usr/bin/env python3
"""Hermes Discovery Inbox (Stage 1) test suite.

TRADE_AI_CI-safe: DB-bound tests skip when TRADE_AI_CI is set or PostgreSQL is
unreachable; pure-function tests (dedupe, scoring, boundary rule) always run.

    .venv/bin/python -m pytest tests/test_hermes_discovery_inbox.py -q
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import dedupe, scoring  # noqa: E402
from lib.hermes_discovery.symbol_validation import (  # noqa: E402
    DENYLIST, VERDICT_VALID, validate_ticker)


def _db_available() -> bool:
    if os.getenv("TRADE_AI_CI"):
        return False
    try:
        from db_adapter import USE_DB, _execute
        if not USE_DB:
            return False
        return bool(_execute("SELECT 1 AS ok", fetch="one"))
    except Exception:
        return False


DB_OK = _db_available()
needs_db = pytest.mark.skipif(not DB_OK, reason="DB unavailable or TRADE_AI_CI set")

# Unique tag per run so tests never collide with real inbox rows and cleanup is exact.
TAG = f"hditest{uuid.uuid4().hex[:8]}"
_created_ids: list[int] = []


def _track(row: dict) -> dict:
    _created_ids.append(row["id"])
    return row


@pytest.fixture(scope="module", autouse=True)
def _cleanup_test_rows():
    yield
    if not DB_OK or not _created_ids:
        return
    from db_adapter import _execute
    ids = tuple(set(_created_ids))
    _execute("DELETE FROM hermes_discovery_feedback WHERE candidate_id IN %s", (ids,))
    _execute("DELETE FROM hermes_discovery_audit WHERE candidate_id IN %s", (ids,))
    _execute("DELETE FROM hermes_discovery_clusters WHERE cluster_key LIKE %s", (f"%{TAG}%",))
    _execute("DELETE FROM hermes_discovery_candidates WHERE id IN %s", (ids,))
    # scrub this run's TAG-scoped keys from the persisted weights file
    try:
        from lib.hermes_discovery import feedback as fb_mod
        data = fb_mod.load_weight_adjustments()
        for bucket in ("source_deltas", "trend_deltas"):
            data[bucket] = {k: v for k, v in data.get(bucket, {}).items() if TAG not in k}
        fb_mod._save_weight_adjustments(data)
    except Exception:
        pass


# ── pure-function tests (always run) ─────────────────────────────────────────

def test_normalized_key_builder():
    assert dedupe.normalize_key("The AI Datacenter Buildout!") == "ai datacenter buildout"
    # stable + punctuation/stopword insensitive
    assert dedupe.normalize_key("AI datacenter buildout, the") == \
        dedupe.normalize_key("  ai DATACENTER (buildout)  ")


def test_near_duplicate_operator_rows_never_merge():
    existing = [{"id": 1, "label": "quantum chip demand surging", "is_operator": True}]
    # operator target is never returned as a merge candidate
    assert dedupe.find_near_duplicate("quantum chip demand surge", existing) is None
    # an operator-created label is never merged into anything
    machine = [{"id": 2, "label": "quantum chip demand surging", "is_operator": False}]
    assert dedupe.find_near_duplicate("quantum chip demand surge", machine,
                                      is_operator=True) is None
    # sanity: machine-vs-machine over the threshold DOES match
    hit = dedupe.find_near_duplicate("quantum chip demand surge", machine)
    assert hit and hit["id"] == 2 and hit["_similarity"] >= dedupe.NEAR_DUP_JACCARD


def test_scoring_parts_sum_to_total():
    candidate = {
        "candidate_type": "TREND_CANDIDATE", "normalized_key": "test trend",
        "label": "test trend", "seen_count": 2, "ttl_days": 30,
        "source_domain": f"{TAG}.example.com",
        "evidence_json": [{"source_domain": "a.com"}, {"source_domain": "b.com"}],
        "risk_flags": ["noise"], "duplicate_cluster_id": 42,
    }
    result = scoring.discovery_score(candidate)
    parts = result["parts"]
    weighted = sum(c["weighted"] for c in parts["components"].values())
    penalties = sum(p["value"] for p in parts["penalties"].values())
    assert abs(parts["weighted_sum"] - weighted) < 1e-6
    assert abs(parts["penalty_sum"] - penalties) < 1e-6
    assert abs(parts["raw_total"] - (weighted - penalties)) < 1e-6
    assert result["total"] == max(0.0, min(1.0, round(parts["raw_total"], 6)))
    # every spec component present, each 0..1, stubs annotated
    assert set(parts["components"]) == set(scoring.WEIGHTS)
    for comp in parts["components"].values():
        assert 0.0 <= comp["value"] <= 1.0
    assert "duplicate" in parts["penalties"] and "noise" in parts["penalties"]


def test_no_broker_imports_in_package_source():
    pkg_dir = ROOT / "scripts" / "lib" / "hermes_discovery"
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:scripts\.)?(?:lib\.)?(brokers\b|schwab_adapter|"
        r"schwab_order_adapter|alpaca)", re.MULTILINE)
    offenders = []
    for path in sorted(pkg_dir.glob("*.py")):
        m = forbidden.search(path.read_text(encoding="utf-8"))
        if m:
            offenders.append(f"{path.name}: {m.group(0).strip()}")
    assert not offenders, f"broker imports found in advisory-only package: {offenders}"


# ── ticker validation ────────────────────────────────────────────────────────

def test_denylist_tickers_rejected():
    for sym in ("AI", "CEO", "USA"):
        assert sym in DENYLIST
        verdict = validate_ticker(sym)
        assert verdict["valid"] is False, f"{sym} must never validate as tradeable"
        assert verdict["verdict"] != VERDICT_VALID


@needs_db
def test_valid_ticker_googl():
    verdict = validate_ticker("GOOGL")
    assert verdict["valid"] is True and verdict["verdict"] == VERDICT_VALID
    assert verdict["company_name"]  # derived from symbol_profiles.description_1s
    assert verdict["instrument_type"]


# ── DB-bound inbox tests ─────────────────────────────────────────────────────

@needs_db
def test_upsert_idempotency_bumps_seen_count():
    from lib.hermes_discovery import inbox
    label = f"battery recycling capacity {TAG}"
    first = _track(inbox.upsert_candidate(
        "TOPIC_CANDIDATE", label, source_domain="example.com",
        evidence=[{"source_domain": "example.com", "note": "first sighting"}]))
    second = inbox.upsert_candidate(
        "TOPIC_CANDIDATE", label.upper() + "!",  # same normalized key
        evidence=[{"source_domain": "other.com", "note": "second sighting"}])
    assert second["id"] == first["id"]
    assert second["seen_count"] == first["seen_count"] + 1
    assert len(second["evidence_json"]) == 2  # merged, not replaced
    assert second["score_json"]["parts"]["components"]  # parts always persisted


@needs_db
def test_trend_near_duplicates_cluster():
    from lib.hermes_discovery import inbox
    a = _track(inbox.upsert_candidate(
        "TREND_CANDIDATE", f"quantum encryption chip demand surging {TAG}"))
    b = _track(inbox.upsert_candidate(
        "TREND_CANDIDATE", f"quantum encryption chip demand surge {TAG}"))
    assert b["id"] != a["id"]
    assert b["duplicate_cluster_id"] is not None
    assert b["status"] == "CLUSTERED"
    anchor = inbox.get_candidate(a["id"])
    assert anchor["duplicate_cluster_id"] == b["duplicate_cluster_id"]
    assert "duplicate" in b["score_json"]["parts"]["penalties"]


@needs_db
def test_operator_trend_never_auto_merged():
    from lib.hermes_discovery import inbox
    op = _track(inbox.upsert_candidate(
        "TREND_CANDIDATE", f"grid storage subsidies expanding {TAG}", is_operator=True))
    machine = _track(inbox.upsert_candidate(
        "TREND_CANDIDATE", f"grid storage subsidies expansion {TAG}"))
    assert machine["duplicate_cluster_id"] is None
    assert machine["status"] == "DISCOVERED"
    assert inbox.get_candidate(op["id"])["duplicate_cluster_id"] is None


@needs_db
def test_ticker_candidate_validation_wiring():
    from lib.hermes_discovery import inbox
    valid = _track(inbox.upsert_candidate(
        "TICKER_CANDIDATE", "GOOGL", normalized_key=f"googl {TAG}"))
    assert valid["status"] == "READY_FOR_REVIEW"
    assert valid["meta_json"]["ticker_validation"]["verdict"] == VERDICT_VALID

    bogus = _track(inbox.upsert_candidate(
        "TICKER_CANDIDATE", "CEO", normalized_key=f"ceo {TAG}"))
    assert bogus["status"] == "NEEDS_VALIDATION"
    assert "ticker_unvalidated" in bogus["risk_flags"]


@needs_db
def test_illegal_transition_raises():
    from lib.hermes_discovery import inbox
    row = _track(inbox.upsert_candidate(
        "SOURCE_CANDIDATE", f"contrarian macro substack {TAG}",
        source_domain=f"{TAG}.substack.com"))
    assert row["status"] == "DISCOVERED"
    with pytest.raises(inbox.IllegalTransitionError):
        inbox.transition_candidate(row["id"], "PROMOTED_TO_WATCH_EVALUATION",
                                   actor="pytest")
    assert inbox.get_candidate(row["id"])["status"] == "DISCOVERED"  # unchanged


@needs_db
def test_decide_appends_audit_row():
    from db_adapter import _execute
    from lib.hermes_discovery import inbox
    row = _track(inbox.upsert_candidate(
        "TOPIC_CANDIDATE", f"uranium enrichment onshoring {TAG}"))
    inbox.transition_candidate(row["id"], "READY_FOR_REVIEW", actor="pytest")
    decided = inbox.decide_candidate(row["id"], "REJECTED", actor="pytest",
                                     notes="test rejection")
    assert decided["status"] == "REJECTED"
    assert decided["decided_by"] == "pytest" and decided["decided_at"] is not None
    audit = _execute(
        """SELECT action, actor, before_json, after_json FROM hermes_discovery_audit
           WHERE candidate_id = %s ORDER BY id""", (row["id"],), fetch="all")
    actions = [a["action"] for a in audit]
    assert actions == ["CREATE", "TRANSITION", "DECIDE"]
    decide_row = audit[-1]
    assert decide_row["before_json"]["status"] == "READY_FOR_REVIEW"
    assert decide_row["after_json"]["status"] == "REJECTED"


@needs_db
def test_feedback_row_and_bounded_weight_delta(tmp_path):
    from lib.hermes_discovery import feedback, inbox
    row = _track(inbox.upsert_candidate(
        "TREND_CANDIDATE", f"desalination capex wave {TAG}",
        source_domain=f"{TAG}-feed.example.com"))
    fb = feedback.record_feedback(row["id"], "useful", actor="pytest",
                                  notes="test feedback")
    assert fb and fb["candidate_id"] == row["id"]
    adjustments = feedback.load_weight_adjustments()
    assert adjustments["source_deltas"].get(f"{TAG}-feed.example.com") == pytest.approx(0.05)

    # bound check on an isolated file: 20 negative events must clamp at -0.3
    path = tmp_path / "weights.json"
    for _ in range(20):
        feedback.apply_weight_delta(source_domain="noisy.example.com",
                                    delta=-0.05, path=path)
    data = json.loads(path.read_text())
    assert data["source_deltas"]["noisy.example.com"] == pytest.approx(-feedback.MAX_ABS_DELTA)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

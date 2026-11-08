"""LQ-20261107-434: market-event-detect's attempt receipt must satisfy its own output contract.

The 19:00 ET live run on 6d4876426 upserted 91 candidate rows for one open episode and wrote produced_count=91,
attempted_count=1 (episodes). n8n_output_verdict.evaluate grades attempted < produced as ``counts_inconsistent``, so
the run ended RUN_FAILED output_unverifiable and opened the lane breaker. The contract's unit is candidate rows, so
attempted_count now counts candidate rows too. These tests run the real detector ``run()`` against stubbed data
access (synthetic fixtures, no DB), then grade the attempt receipt it writes through the real evaluate(), the real
health-contract rule and the real executor apply_output_verdict().
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import market_event_detect as med  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import n8n_output_verdict as V  # noqa: E402

LANE = med.LANE_ID
CODE = "c" * 40
RULE = {c["id"]: c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}[LANE]["expected_output"]
ENTRY = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}[LANE]
POLICY = {"data": {"close_time_et": "16:00"}, "detector": {"rank_on_detect": True}, "ranking": {"max_candidates": 25}}


class _Conn:
    autocommit = True

    def commit(self):
        pass

    def close(self):
        pass


def _episode(i: int) -> dict:
    return {"episode_id": f"broad_selloff:market:2026-11-0{4 + i}", "state": "ACTIVE", "affected_sectors": [],
            "baseline_date": "2026-11-04", "last_eval": {}, "_new": False}


def _cand(sym: str) -> dict:
    return {"symbol": sym, "rank": 1, "source": "sp500", "drawdown_pct": -9.0, "quality_score": 0.5,
            "discount_score": 0.5, "combined_score": 0.5, "fell_for_reason": False,
            "reason_evidence": {"group": "tech", "quality_coverage": 1.0}}


@pytest.fixture
def detect(tmp_path, monkeypatch):
    """Run the real run() --apply as a live executor attempt; data access stubbed; returns (rc, doc, verdict, graded)."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", CODE)
    monkeypatch.setattr(med.rank, "load_policy", lambda p: POLICY)
    monkeypatch.setattr(med, "load_mre", lambda p: {})
    monkeypatch.setattr(med, "connect", lambda read_only: _Conn())
    monkeypatch.setattr(med, "index_closes", lambda conn, policy, last: {})
    monkeypatch.setattr(med.sector_proxies, "read_moves", lambda conn, policy, now=None: {})
    monkeypatch.setattr(med, "evaluate_triggers", lambda *a, **k: {})
    monkeypatch.setattr(med, "advance_state", lambda ep, cands, trig, policy, now: ep)
    monkeypatch.setattr(med.store, "list_episodes", lambda conn: [])
    monkeypatch.setattr(med.store, "upsert_episode", lambda conn, ep: None)
    monkeypatch.setattr(med.store, "upsert_candidates", lambda conn, eid, cands: len(cands))  # one row per candidate
    monkeypatch.setattr(med.store, "unrank_missing", lambda conn, eid, syms: 0)

    def fire(n_episodes: int, per_episode: int, tables: bool = True):
        monkeypatch.setattr(med.store, "tables_exist", lambda conn: tables)
        monkeypatch.setattr(med, "plan_episodes", lambda existing, trig, policy, now: [_episode(i) for i in range(n_episodes)])
        monkeypatch.setattr(med.rank, "build_candidates", lambda conn, ep, mre, policy, now: {
            "candidates": [_cand(f"S{j:03d}") for j in range(per_episode)], "excluded": {}, "inputs": {}})
        run_id = f"d:{LANE}:live:20261107T1900:{n_episodes}x{per_episode}:{int(tables)}"
        monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
        started = datetime.now(timezone.utc) - timedelta(seconds=1)
        rc = med.run(argparse.Namespace(apply=True, dry_run=False, policy=None, mre="unused.json",
                                        now="2026-11-07T19:00:00-05:00", top=5, evidence_out=None))
        finished = datetime.now(timezone.utc) + timedelta(seconds=1)
        doc = X.read_attempt_receipt(tmp_path, LANE, run_id)
        verdict = V.evaluate(RULE, doc, run_id=run_id, lane_id=LANE, mode="live", attempt=1,
                             started_at=started.isoformat(), finished_at=finished.isoformat(), code_sha=CODE)
        exec_receipt = {"run_id": run_id, "lane_id": LANE, "mode": "live", "state": "RUN_DONE" if rc == 0 else "RUN_FAILED",
                        "reason": None if rc == 0 else "exit_nonzero", "attempt": 1, "code_sha": CODE,
                        "started_at": started.isoformat(), "finished_at": finished.isoformat()}
        graded = X.apply_output_verdict(dict(exec_receipt), {LANE: RULE}, lane_id=LANE, mode="live",
                                        state_root=tmp_path, entry=ENTRY)
        return rc, doc, verdict, graded

    return fire


def test_lane_is_enforced_and_the_rule_is_valid():
    assert ENTRY.get("output_receipt") == X.OUTPUT_RECEIPT_ENFORCED
    assert V.validate_expected_output(RULE) == []


def test_the_live_shape_that_opened_the_breaker_is_counts_inconsistent():
    """Regression anchor: the 19:00 ET receipt's counts (91 rows written, attempted=1 episode) never pass."""
    doc = {"schema": "LaneRunReceipt@v2", "status": "ok", "produced_count": 91, "attempted_count": 1, "run_id": "r"}
    v = V.evaluate(RULE, {**doc, "lane_id": LANE}, run_id="r", lane_id=LANE, mode="live")
    assert v["verdict"] == "unverifiable" and v.get("why") == "counts_inconsistent", v


def test_one_episode_91_candidates_grades_produced(detect):
    rc, doc, verdict, graded = detect(1, 91)
    assert rc == 0 and doc["schema"] == "LaneRunReceipt@v2"
    assert doc["produced_count"] == 91 and doc["attempted_count"] == 91, doc
    assert doc["summary"]["episodes"] == 1
    assert verdict["verdict"] == "produced", verdict
    assert graded["state"] == "RUN_DONE" and graded["output_verdict"]["verdict"] == "produced", graded


def test_two_episodes_sum_their_candidate_rows(detect):
    rc, doc, verdict, graded = detect(2, 30)
    assert rc == 0 and doc["produced_count"] == 60 and doc["attempted_count"] == 60
    assert verdict["verdict"] == "produced" and graded["state"] == "RUN_DONE", (verdict, graded)


def test_no_open_episode_is_allowed_empty(detect):
    rc, doc, verdict, graded = detect(0, 0)
    assert rc == 0 and doc["produced_count"] == 0 and doc["attempted_count"] == 0
    assert doc["empty_reason"] == "no_open_episode"
    assert verdict["verdict"] == "empty_allowed" and graded["state"] == "RUN_DONE", (verdict, graded)


def test_missing_tables_is_a_graded_failure_not_unverifiable(detect):
    rc, doc, verdict, graded = detect(1, 5, tables=False)
    assert rc == 2
    assert doc is not None and doc["schema"] == "LaneRunReceipt@v2", "tables-missing must still write the attempt receipt"
    assert doc["empty_reason"] == "dependency_unavailable" and doc["skipped_reasons"] == {"dependency_unavailable": 1}
    assert verdict["verdict"] == "empty_violation", verdict
    assert graded["state"] == "RUN_FAILED", graded

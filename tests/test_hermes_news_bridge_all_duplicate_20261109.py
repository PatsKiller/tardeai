"""ANCHOR: HERMES_NEWS_BRIDGE_ALL_DUPLICATE_20261109. LQ-20261107-1330 — a run that read candidates and
skipped every one as a clean duplicate said ``empty_reason: no_new_input``: the receipt claimed no input
on a run that had two. Live evidence (data/runtime/n8n_runs/d:hermes-news-bridge:live:20261108T1840.json,
output_verdict): attempted_count 2, skipped_reasons {duplicate: 2, insert_error: 0}, empty_reason
no_new_input, verdict empty_allowed.

The zero is still a correct run — the lane did its job on input it had already bridged. So the truthful
reason must be BOTH stated and allowed: it is a reviewed idle token (config/run_quality_idle_reasons.json)
and an allowed empty reason in the lane's health contract, or the receipt would go from lying-but-idle to
truthful-but-RUN_FAILED (scripts/lib/n8n_output_verdict.evaluate -> empty_reason_not_allowed).

Hermetic: no database, no network, synthetic counts. Lane ids and reason strings are the only real values,
because the contract and the enums match them by name.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_news_bridge as B  # noqa: E402
from scripts.lib import n8n_output_verdict as V  # noqa: E402
from scripts.lib import run_quality as Q  # noqa: E402


def _summary(*, candidates: int, bridged: int, skipped_dup: int, insert_errors: int) -> dict:
    # the shape run() returns (plus the keys lane_output does not read)
    return {"run_at": "2026-11-08T18:40:00+00:00", "candidates": candidates, "bridged": bridged,
            "skipped_dup": skipped_dup, "insert_errors": insert_errors, "window_hours": B.WINDOW_HOURS,
            "rows": []}


# ── the reason the receipt states ───────────────────────────────────────────────────────────────────

def test_every_attempted_row_a_duplicate_is_all_duplicate_not_no_new_input():
    out = B.lane_output(_summary(candidates=2, bridged=0, skipped_dup=2, insert_errors=0), window_rows=5)
    assert out["empty_reason"] == B.ALL_DUPLICATE_REASON == "all_duplicate"
    assert out["empty_reason"] != "no_new_input"
    assert out["produced_count"] == 0
    assert out["attempted_count"] == 2
    assert out["skipped_reasons"] == {"duplicate": 2, "insert_error": 0}
    assert "dependency_unavailable" not in out["skipped_reasons"]


def test_the_live_run_from_the_finding_reads_all_duplicate():
    """d:hermes-news-bridge:live:20261108T1840, replayed from its recorded counts."""
    out = B.lane_output(_summary(candidates=2, bridged=0, skipped_dup=2, insert_errors=0), window_rows=4)
    assert out["empty_reason"] == "all_duplicate"


def test_no_candidate_at_all_is_still_no_new_input():
    """The 2026-10-29..11-07 case: the feed was dead, so the run really had no input. That reason stands."""
    out = B.lane_output(_summary(candidates=0, bridged=0, skipped_dup=0, insert_errors=0), window_rows=5)
    assert out["empty_reason"] == "no_new_input"


def test_one_insert_error_is_not_a_duplicate_so_the_reason_does_not_change():
    """Only a run whose every skip is a duplicate gets the new token. The error is already carried in
    skipped_reasons.insert_error; this change does not relabel a mixed zero."""
    out = B.lane_output(_summary(candidates=2, bridged=0, skipped_dup=1, insert_errors=1), window_rows=5)
    assert out["empty_reason"] == "no_new_input"
    assert out["skipped_reasons"]["insert_error"] == 1


def test_a_window_failure_still_outranks_all_duplicate():
    dead = B.lane_output(_summary(candidates=2, bridged=0, skipped_dup=2, insert_errors=0), window_rows=0)
    assert dead["empty_reason"] == B.WINDOW_EMPTY_REASON
    assert dead["skipped_reasons"]["dependency_unavailable"] == 1
    unknown = B.lane_output(_summary(candidates=2, bridged=0, skipped_dup=2, insert_errors=0), window_rows=None)
    assert unknown["empty_reason"] == B.WINDOW_UNKNOWN_REASON
    assert unknown["skipped_reasons"]["dependency_unavailable"] == 1


def test_a_producing_run_states_no_empty_reason():
    out = B.lane_output(_summary(candidates=2, bridged=2, skipped_dup=0, insert_errors=0), window_rows=6)
    assert out["empty_reason"] is None


# ── the top-level outcome must agree with the output ────────────────────────────────────────────────

def _outcome(summary: dict) -> tuple[str, str]:
    return B.receipt_outcome(summary, failed=False, window_unknown=False, window_empty=False,
                             inserts_failed=False)


def test_outcome_reason_agrees_with_the_empty_reason():
    assert _outcome(_summary(candidates=2, bridged=0, skipped_dup=2, insert_errors=0)) == ("empty", "all_duplicate")
    assert _outcome(_summary(candidates=0, bridged=0, skipped_dup=0, insert_errors=0)) == ("empty", "no_new_input")
    assert _outcome(_summary(candidates=2, bridged=2, skipped_dup=0, insert_errors=0)) == ("ok", "bridged")


# ── the token must be allowed everywhere a receipt is graded ───────────────────────────────────────

def _contract_row() -> dict:
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    return next(c for c in doc["contracts"] if isinstance(c, dict) and c.get("id") == B.LANE_ID)


def test_the_token_is_registered_in_the_idle_reasons_and_the_contract():
    assert "all_duplicate" in Q.idle_reasons(), "an unlisted idle token grades the truthful zero EMPTY, not idle"
    assert "all_duplicate" in _contract_row()["expected_output"]["empty_allowed_reasons"]


def test_the_lane_contract_accepts_the_token_in_the_closed_enum():
    """FW-M6 refuses an empty_allowed_reasons entry outside the enum, which would make the contract (and
    every run judged by it) unverifiable."""
    from scripts.check_n8n_workflow_framework import EMPTY_ALLOWED_REASONS
    assert "all_duplicate" in EMPTY_ALLOWED_REASONS
    assert V.validate_expected_output(_contract_row()["expected_output"]) == []


def test_the_duplicate_zero_grades_as_an_allowed_empty_not_a_run_failure():
    """The executor's own verdict on a receipt shaped like the live one. Before the registration the same
    receipt came back empty_violation / empty_reason_not_allowed and the run was RUN_FAILED."""
    rule = _contract_row()["expected_output"]
    doc = {"schema": V.LANE_RECEIPT_V2, "run_id": "d:hermes-news-bridge:live:20311108T1840", "lane_id": B.LANE_ID,
           "produced_count": 0, "attempted_count": 2,
           "skipped_reasons": {"duplicate": 2, "insert_error": 0}, "empty_reason": "all_duplicate",
           "status": "ok", "outcome": "empty", "outcome_reason": "all_duplicate",
           "mode": "live", "run_mode": "live",
           "started_at": "2031-11-08T18:40:00+00:00", "finished_at": "2031-11-08T18:40:01+00:00",
           "ok_at": "2031-11-08T18:40:01+00:00"}
    out = V.evaluate(rule, doc, run_id=doc["run_id"], lane_id=B.LANE_ID, mode="live")
    assert out["verdict"] == "empty_allowed", out
    assert out["empty_reason"] == "all_duplicate"


def test_main_writes_the_truthful_reason_and_stays_green(monkeypatch, tmp_path):
    import lib.lane_last_receipt as llr

    captured: dict = {}

    def fake_run(**kwargs):
        return {**_summary(candidates=2, bridged=0, skipped_dup=2, insert_errors=0), "window_rows": 5}

    def fake_write(lane_id, **kw):
        captured.update({"lane_id": lane_id, **kw})
        return {"lane_id": lane_id}

    monkeypatch.setattr(B, "run", fake_run)
    monkeypatch.setattr(llr, "write_lane_receipt", fake_write)
    monkeypatch.setattr(llr, "receipt_path", lambda name: tmp_path / f"{name}_last.json")
    monkeypatch.setattr(llr, "now_iso", lambda: "2026-11-08T18:40:00+00:00")
    assert B.main(["--json"]) == 0
    assert captured["ok"] is True
    assert captured["output"]["empty_reason"] == "all_duplicate"
    assert (captured["outcome"], captured["outcome_reason"]) == ("empty", "all_duplicate")

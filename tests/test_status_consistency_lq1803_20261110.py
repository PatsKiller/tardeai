"""ANCHOR: STATUS_CONSISTENCY_LQ1803_20261110 — one document, one health; the worse claim wins.

LQ-20261107-1803 (operator, P0 SEV-1) and its addendum (20261110T1725Z): for EVERY ``runtime/*_last.json`` /
health-producing writer, ``verdict``, ``status``, ``outcome``, ``health`` and the display state must reconcile. No file
may legally contain ``verdict=BLOCK + status=ok``, ``verdict=FAIL + status=HEALTHY``, or any equivalent contradiction;
a contradictory combination is downgraded to the worse state (never upgraded) and logged.

BEFORE the fix each of these fixtures produced the contradiction it names (``status: ok`` beside a BLOCK verdict, a
failed receipt rendered ``succeeded`` because it carried an old ``ok_at``, a DEGRADED verdict graded GOOD). Hermetic:
synthetic receipts only, no state root, no network, no DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from scripts.lib import jobs_history as J
from scripts.lib import lane_last_receipt as L
from scripts.lib import run_quality as R
from scripts.lib import status_consistency as SC
import scripts.sweep_status_contradictions as SWEEP

NOW = datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc)  # Tuesday 12:00 ET
WEEKDAY = lambda d: d.weekday() < 5  # noqa: E731


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _litmus_receipt(*, verdict="BLOCK", **over) -> dict:
    """The 2026-11-10T12:46:37Z source-litmus-vs-yahoo receipt, verbatim in the fields that matter."""
    doc = {"schema": "LaneRunReceipt@v1", "lane_id": "synthetic-litmus", "mode": "live", "status": "ok",
           "outcome": "ok", "exit": 1, "started_at": "2026-11-10T12:46:34.846632+00:00",
           "finished_at": "2026-11-10T12:46:37.589641+00:00", "ok_at": "2026-11-10T12:46:37.589641+00:00",
           "consecutive_failures": 0, "summary": {"verdict": verdict, "checked": 12, "blocked": 1}}
    doc.update(over)
    return doc


# ── 1. the writer (one place: lane_last_receipt.build_receipt) ───────────────────────────────────────────────────

def test_block_verdict_never_writes_status_ok():
    doc = L.build_receipt("synthetic-litmus", ok=True, exit_code=1, summary={"verdict": "BLOCK", "blocked": 1},
                          finished_at="2026-11-10T12:46:37.589641+00:00")
    assert doc["status"] == "blocked", "a BLOCK verdict may not be written as status ok"
    assert doc["outcome"] == "blocked"
    assert doc["status_consistency"] == {
        "schema": SC.SCHEMA, "downgraded": True, "from": "ok", "to": "blocked",
        "fields": [{"field": "summary.verdict", "value": "BLOCK", "rank": "blocked"},
                   {"field": "exit", "value": 1, "rank": "blocked"},
                   {"field": "outcome", "value": "ok", "rank": "blocked"}]}
    # the RUN succeeded (it ran and wrote its report): its own success marker advances, the registry signal is intact
    assert doc["ok_at"] == "2026-11-10T12:46:37.589641+00:00"


def test_fail_verdict_with_a_healthy_status_is_downgraded():
    result = SC.scan({"status": "ok", "outcome": "ok", "health": "healthy", "summary": {"verdict": "FAIL"}})
    assert result["contradictions"], "verdict FAIL beside health healthy must be a contradiction"
    assert result["proposed_status"] == "failed" and result["proposed_outcome"] == "error"
    assert {c["field"] for c in result["contradictions"]} == {"summary.verdict", "outcome"}


def test_non_zero_exit_with_status_ok_is_not_ok():
    doc = L.build_receipt("synthetic-exit", ok=True, exit_code=2, finished_at="2026-11-10T12:00:00+00:00")
    assert doc["status"] == "failed" and doc["outcome"] == "error"
    assert doc["ok_at"] is None, "a failed run may not advance the success marker"


def test_block_with_exit_zero_is_still_blocked():
    # a lane that reports BLOCK without the non-zero exit: the verdict, not the exit code, is the claim
    doc = L.build_receipt("synthetic-zero", ok=True, exit_code=0, summary={"verdict": "BLOCK"},
                          finished_at="2026-11-10T12:00:00+00:00")
    assert doc["status"] == "blocked"


def test_degraded_verdict_is_written_as_degraded_not_ok():
    doc = L.build_receipt("synthetic-freshness", ok=True, exit_code=0, summary={"verdict": "DEGRADED"},
                          finished_at="2026-11-10T17:01:05+00:00")
    assert doc["status"] == "degraded" and doc["outcome"] == "degraded"


def test_reconcile_never_upgrades_and_is_idempotent():
    doc = {"status": "failed", "outcome": "error", "summary": {"verdict": "ok"}}
    assert SC.scan(doc)["contradictions"] == [], "an ok verdict never raises a failed status"
    once, _ = SC.reconcile(_litmus_receipt(), log=False)
    twice, again = SC.reconcile(once, log=False)
    assert again == [] and twice == once


def test_an_unverified_claim_is_reported_never_rewritten():
    doc = {"status": "ok", "outcome": "ok", "summary": {"verdict": "UNVERIFIED"}}
    result = SC.scan(doc)
    assert result["contradictions"] == [] and result["advisories"], "unknown beats a wrong rewrite"
    out, changed = SC.reconcile(dict(doc), log=False)
    assert changed == [] and out["status"] == "ok"


# ── 2. the page (: the Jobs projection reads the receipt, not just ok_at) ────────────────────────────────────────

def test_failed_receipt_with_a_carried_ok_at_is_not_a_success():
    """BEFORE: receipt_success() answered from the carried ok_at, so this run rendered "succeeded" (exit 2, status failed)."""
    receipt = {"lane_id": "synthetic-fail", "mode": "live", "status": "failed", "outcome": "error", "exit": 2,
               "started_at": "2026-11-10T16:00:00+00:00", "finished_at": "2026-11-10T16:00:04+00:00",
               "ok_at": "2026-11-09T09:00:00+00:00", "error": "source refused"}
    run = J.receipt_run(receipt, None)
    assert run["result"] == "failed", "a failed receipt may not be read as a success because ok_at is present"
    assert run["reason"] == "source refused"


def test_the_projection_reconciles_a_prefix_receipt_the_file_still_says_ok():
    """The file on disk is unchanged (status ok, verdict BLOCK); the page may not repeat its contradiction."""
    run = J.receipt_run(_litmus_receipt(), None)
    assert run["result"] == "blocked"
    assert "BLOCK" in run["reason"]


def test_the_same_live_run_takes_the_receipts_word_never_the_ledgers_ok():
    """A ledger row (executor exit 0, "succeeded") and the lane's own receipt describe ONE run: worse word wins."""
    lane = {"lane_id": "synthetic-litmus", "state": "ACTIVE", "expected_cadence_hours": 1,
            "scheduler": {"kind": "n8n"}, "dispatch": {"cron": "0 * * * *", "tz": "America/New_York"}}
    start = datetime(2026, 11, 10, 12, 46, 34, tzinfo=timezone.utc)
    receipt = _litmus_receipt(started_at=_z(start), finished_at=_z(start + timedelta(seconds=3)),
                              ok_at=_z(start + timedelta(seconds=3)))
    lane_receipt = J.receipt_run(receipt, None)
    lane_receipt["source"] = "lane receipt"
    ledger = [{"run_id": "d:synthetic-litmus:live:20261110T1246", "lane_id": "synthetic-litmus", "mode": "live",
               "state": "RUN_DONE", "requested_by": "n8n", "requested_at": _z(start),
               "started_at": _z(start + timedelta(seconds=1)), "finished_at": _z(start + timedelta(seconds=4)),
               "exit_code": 0, "duration_s": 3, "attempt": 1, "parent_run_id": None,
               "slot_key": "d:synthetic-litmus:live:20261110T1246", "reason": None, "attempt_states": None}]
    result = J.build({"lanes": [lane]}, {"ledger_runs": ledger, "lane_receipts": {"synthetic-litmus": lane_receipt},
                                         "ledger_since": NOW - timedelta(days=10),
                                         "journal_since": NOW - timedelta(days=10)},
                     now=NOW, trading_day=WEEKDAY)
    row = result["rows"][0]
    assert row["status"] == "blocked", "the ledger's exit 0 may not hide the run's BLOCK verdict"
    assert "BLOCK" in (row["status_reason"] or "")
    assert result["summary"]["blocked"] == 1 and result["summary"]["ok"] == 0


def test_a_dry_run_ledger_row_does_not_shadow_the_live_receipt():
    """source-litmus: the 12:46:02 dry-run ledger row was matched to the 12:46:34 live receipt and the page showed the dry run."""
    lane = {"lane_id": "synthetic-litmus", "state": "ACTIVE", "expected_cadence_hours": 1,
            "scheduler": {"kind": "systemd"}, "output_signal": {"kind": "json_key",
                                                                "path": "data/runtime/synthetic-litmus_last.json",
                                                                "key": "ok_at"}}
    receipt = _litmus_receipt()
    lane_receipt = J.receipt_run(receipt, None)
    lane_receipt["source"] = "lane receipt"
    dry = [{"run_id": "d:synthetic-litmus:dry:20261110T1246", "lane_id": "synthetic-litmus", "mode": "dry_run",
            "state": "RUN_DONE", "requested_by": "n8n", "requested_at": "2026-11-10T12:46:02+00:00",
            "started_at": "2026-11-10T12:46:03+00:00", "finished_at": "2026-11-10T12:46:05+00:00",
            "exit_code": 0, "duration_s": 2, "attempt": 1, "parent_run_id": None,
            "slot_key": "d:synthetic-litmus:dry:20261110T1246", "reason": None, "attempt_states": None}]
    result = J.build({"lanes": [lane]}, {"ledger_runs": dry, "lane_receipts": {"synthetic-litmus": lane_receipt},
                                         "ledger_since": NOW - timedelta(days=10),
                                         "journal_since": NOW - timedelta(days=10)},
                     now=NOW, trading_day=WEEKDAY)
    row = result["rows"][0]
    assert (row["last_run"] or {}).get("mode") == "live"
    assert (row["last_run"] or {}).get("result") == "blocked"
    assert row["status"] == "blocked"


# ── 3. the quality column ───────────────────────────────────────────────────────────────────────────────────────

def test_quality_reads_the_block_and_degraded_words():
    assert R.receipt_status(_litmus_receipt()) == "blocked", "status ok + ok_at + verdict BLOCK is not 'ok'"
    assert R.receipt_status(_litmus_receipt(verdict="DEGRADED", exit=0)) == "degraded"
    assert R.receipt_status({"status": "degraded", "outcome": "ok", "ok_at": "x"}) == "degraded"


def test_quality_grades_a_block_verdict_failed_with_the_verdict_as_reason():
    lane = {"lane_id": "synthetic-litmus", "state": "ACTIVE", "output_signal": {"kind": "json_key",
            "path": "data/runtime/synthetic-litmus_out.json"}, "scheduler": {"kind": "systemd"}, "dispatch": {}}
    start = NOW - timedelta(minutes=30)
    row = {"lane_id": "synthetic-litmus", "state": "ACTIVE", "status": "blocked", "runs": [], "last_run": None,
           "history_gap": None}
    evidence = {"receipt": _litmus_receipt(started_at=_z(start), finished_at=_z(start + timedelta(seconds=3)),
                                           ok_at=_z(start + timedelta(seconds=3))),
                "receipt_path": "data/runtime/synthetic-litmus_last.json", "output_at": start,
                "ledger": [], "history": [], "contract": None, "freshness": [], "freshness_known": True,
                "plausibility": [], "plausibility_known": True}
    out = R.grade(row, lane, evidence, now=NOW)
    assert out["grade"] == "FAILED" and out["sub"] == "blocked_verdict"
    assert "BLOCK" in out["headline"]


# ── 4. the sweep (deliverable 2): lists the contradictions, invents nothing ─────────────────────────────────────

def test_sweep_lists_every_contradiction_and_nothing_else(tmp_path):
    runtime = tmp_path / "data/runtime"
    runtime.mkdir(parents=True)
    (runtime / "synthetic-litmus_last.json").write_text(json.dumps(_litmus_receipt()), encoding="utf-8")
    (runtime / "synthetic-freshness_last.json").write_text(
        json.dumps({"status": "ok", "outcome": "ok", "exit": 0, "summary": {"verdict": "DEGRADED"}}), encoding="utf-8")
    (runtime / "synthetic-clean_last.json").write_text(
        json.dumps({"status": "ok", "outcome": "ok", "exit": 0, "summary": {"verdict": "OK"}}), encoding="utf-8")
    (runtime / "synthetic-nostatus_last.json").write_text(json.dumps({"verdict": "DRIFT"}), encoding="utf-8")
    out = SWEEP.sweep(tmp_path)
    assert out["read"] == 4
    by_path = {c["path"]: c for c in out["contradictions"]}
    assert set(by_path) == {"data/runtime/synthetic-litmus_last.json", "data/runtime/synthetic-freshness_last.json"}
    litmus = by_path["data/runtime/synthetic-litmus_last.json"]
    assert litmus["display"] == {"status": "blocked", "outcome": "blocked"}
    assert [a["path"] for a in out["advisories"]] == ["data/runtime/synthetic-nostatus_last.json"]
    assert SWEEP.main(["--state-root", str(tmp_path), "--fail-on-contradiction"]) == 1
    assert SWEEP.main(["--state-root", str(tmp_path)]) == 0


def test_an_unreadable_document_says_cannot_be_read_and_is_never_ok(tmp_path):
    """REVIEW-LQ1829 S2: acceptance 4's literal phrase. The substance (an UNREADABLE section, never ``ok``) was
    already met; this pins the wording so a reader is told the cause instead of a file that was quietly skipped."""
    runtime = tmp_path / "data/runtime"
    runtime.mkdir(parents=True)
    (runtime / "synthetic-bad_last.json").write_text("{bad json", encoding="utf-8")
    (runtime / "synthetic-list_last.json").write_text("[1, 2]", encoding="utf-8")
    out = SWEEP.sweep(tmp_path)
    assert out["read"] == 2 and out["clean"] == 0
    assert out["contradictions"] == [] and out["advisories"] == []
    text = SWEEP._render(out)
    assert "synthetic-bad_last.json  cannot be read: JSONDecodeError" in text, text
    assert "synthetic-list_last.json  cannot be read: top level is list, not an object" in text, text


def test_the_health_contract_calls_a_block_known_never_malformed():
    """BEFORE: a blocked receipt failed `status in {ok, failed}` and read as ERROR "receipt_outcome_invalid"."""
    from scripts.lib import system_health_freshness as F
    doc = L.build_receipt("synthetic-litmus", ok=True, exit_code=1, summary={"verdict": "BLOCK"},
                          started_at="2026-11-10T16:57:00+00:00", finished_at="2026-11-10T17:00:00+00:00")
    out = F.lane_receipt_freshness(doc, lane_id="synthetic-litmus", script="synthetic-litmus", now=NOW, max_age_min=60)
    assert out["status"] == "BLOCKED" and out["reason"] == "latest_receipt_blocked", out
    assert out["subject_reason"] == "BLOCK" and out["latest_attempt_status"] == "blocked"
    bad = dict(doc, status="something_else")
    assert F.lane_receipt_freshness(bad, lane_id="synthetic-litmus", script="synthetic-litmus", now=NOW,
                                    max_age_min=60)["reason"] == "receipt_outcome_invalid"


def test_the_health_contract_reads_a_prefix_receipt_through_the_same_reconciliation():
    """LQ-20261107-1833 (REVIEW-LQ1829 S1). BEFORE, the freshness check branched on the document's own stale word, so
    a pre-fix file still on disk disagreed with the Jobs projection: the canonical 12:46:37Z receipt read ERROR
    "receipt_success_outcome_inconsistent" (BLOCK verdict) and a WARN verdict read OK (green). Every consumer must
    read one calculation; the reconcile is downgrade-only, so a post-fix document is unchanged."""
    from scripts.lib import system_health_freshness as F
    blocked = _litmus_receipt(script="synthetic-litmus")  # status/outcome ok, exit 1, summary.verdict BLOCK
    out = F.lane_receipt_freshness(blocked, lane_id="synthetic-litmus", script="synthetic-litmus", now=NOW,
                                   max_age_min=600)
    assert out["status"] == "BLOCKED" and out["reason"] == "latest_receipt_blocked", out
    assert out["latest_attempt_status"] == "blocked" and out["subject_reason"] == "BLOCK"
    degraded = _litmus_receipt(verdict="WARN", exit=0, script="synthetic-litmus")
    out = F.lane_receipt_freshness(degraded, lane_id="synthetic-litmus", script="synthetic-litmus", now=NOW,
                                   max_age_min=600)
    assert out["status"] == "DEGRADED" and out["reason"] == "latest_receipt_degraded", out
    assert out["latest_attempt_status"] == "degraded"
    post_fix = L.build_receipt("synthetic-litmus", ok=True, exit_code=1, summary={"verdict": "BLOCK"},
                               started_at="2026-11-10T16:57:00+00:00", finished_at="2026-11-10T17:00:00+00:00")
    again = F.lane_receipt_freshness(post_fix, lane_id="synthetic-litmus", script="synthetic-litmus", now=NOW,
                                     max_age_min=60)
    assert again["status"] == "BLOCKED" and again["latest_attempt_status"] == "blocked", again


def test_catalog_mix_and_filters_cover_the_new_statuses():
    from scripts.lib import n8n_catalog as N
    # LQ-20261107-1842: the degraded-VERDICT status is `subject_degraded` (the run reports a degraded subject); the
    # quality grade DEGRADED owns the bare word, so no row status, filter or mix key may be called "degraded".
    for status in ("blocked", "subject_degraded"):
        assert status in J.STATUS_FILTERS and status in J._ORDER and status in J._MIX
        assert J._MIX[status] == status and status in N.MIX_KEYS and N.STATUS_MIX[status] == status
    assert "degraded" not in J.STATUS_FILTERS and "degraded" not in J._MIX and "degraded" not in N.MIX_KEYS
    assert "blocked" in J._ATTENTION

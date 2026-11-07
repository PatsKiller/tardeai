"""LQ-20261107-192: a receipt says ok | empty | error, so a failed source call is not an "ok / 0 rows" result."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.lib import lane_last_receipt as R  # noqa: E402
from scripts.lib import n8n_catalog as C  # noqa: E402
from scripts.lib import n8n_output_verdict as V  # noqa: E402


def test_outcome_derived():
    assert R.build_receipt("l", ok=True, produced_count=3)["outcome"] == "ok"
    d = R.build_receipt("l", ok=True, produced_count=0, empty_reason="no_new_input")
    assert (d["outcome"], d["outcome_reason"]) == ("empty", "no_new_input")
    e = R.build_receipt("l", ok=False, error="OSError: boom")
    assert (e["outcome"], e["outcome_reason"]) == ("error", "OSError")
    assert R.build_receipt("l", ok=True)["outcome"] == "ok"


def test_explicit_error_overrides_ok_and_blocks_ok_at():
    d = R.build_receipt("l", ok=True, outcome="error", outcome_reason="source_error", produced_count=0,
                        previous_ok_at="2026-01-01T00:00:00+00:00")
    assert d["outcome"] == "error" and d["status"] == "failed"
    assert d["ok_at"] == "2026-01-01T00:00:00+00:00"


def test_bad_outcome_rejected():
    try:
        R.build_receipt("l", ok=True, outcome="fine")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_output_dict_empty_counts_as_empty():
    assert R.build_receipt("l", ok=True, output={"produced_count": 0, "empty_reason": "x"})["outcome"] == "empty"


def test_write_lane_receipt_passes_outcome(tmp_path):
    p = tmp_path / "x_last.json"
    R.write_lane_receipt("x", ok=True, path=p, outcome="error", outcome_reason="source_error")
    doc = json.loads(p.read_text())
    assert doc["outcome"] == "error" and doc["status"] == "failed"


def test_evaluate_error_outcome_is_violation():
    rule = {"schema": V.EXPECTED_OUTPUT_SCHEMA, "unit": "rows", "rule": "min_produced", "produced_field": "produced_count",
            "min_produced": 1, "fatal_skip_reasons": [],
            "evidence": [{"kind": sorted(V.EVIDENCE_KINDS)[0], "ref": "t"}]}
    doc = {"schema": V.LANE_RECEIPT_V2, "run_id": "r", "lane_id": "l", "produced_count": 0, "status": "ok",
           "outcome": "error", "mode": "live", "run_mode": "live"}
    out = V.evaluate(rule, doc, run_id="r", lane_id="l", mode="live")
    assert out["verdict"] == "empty_violation" and out["why"] == "receipt_outcome_error"


def test_catalog_overlays_fail_run(tmp_path):
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    (rt / "a_last.json").write_text(json.dumps({"lane_id": "a", "outcome": "error", "outcome_reason": "source_error"}))
    (rt / "b_last.json").write_text(json.dumps({"lane_id": "b", "outcome": "empty"}))
    (rt / "c_last.json").write_text("{bad")
    verdicts = {"a": {"verdict": "PASS", "defect": None, "fix_suggestion": None, "work_item": None, "audited_at": None},
                "d": {"verdict": "FAIL_DATA", "defect": "x", "fix_suggestion": None, "work_item": None, "audited_at": None}}
    out = C.overlay_receipt_errors(verdicts, tmp_path)
    assert out["a"]["verdict"] == "FAIL_RUN" and "source_error" in out["a"]["defect"]
    assert "b" not in out and out["d"]["verdict"] == "FAIL_DATA"
    assert C.verdict_class(out["a"]["verdict"]) == "fail"


def test_enrich_outcomes():
    import enrich_proposal_technicals as E
    assert E.receipt_outcome(0, 0, 0) == ("empty", "no_active_proposal_symbols")
    assert E.receipt_outcome(5, 0, 5) == ("error", "every_snapshot_failed")
    assert E.receipt_outcome(5, 5, 0, finviz_got=0) == ("error", "finviz_returned_no_symbols")
    assert E.receipt_outcome(5, 4, 1, finviz_got=5) == ("ok", "partial_failures:1")


def test_hermes_outcomes():
    import hermes_news_bridge as H
    s = {"bridged": 0, "candidates": 0, "skipped_dup": 0, "insert_errors": 0}
    kw = dict(failed=False, window_unknown=False, window_empty=False, inserts_failed=False)
    assert H.receipt_outcome(s, **kw) == ("empty", "no_new_input")
    assert H.receipt_outcome({**s, "bridged": 2}, **kw) == ("ok", "bridged")
    assert H.receipt_outcome(s, **{**kw, "failed": True, "window_unknown": True})[0] == "error"
    assert H.receipt_outcome(s, **{**kw, "failed": True, "window_empty": True}) == ("error", "no_source_rows_in_window")


def test_cio_ask_source_error_receipt_is_error(tmp_path, monkeypatch):
    import cio_ask_lifecycle as M
    got = {}
    monkeypatch.setattr("scripts.lib.lane_last_receipt.write_lane_receipt", lambda lane, **kw: got.update(kw))
    monkeypatch.setattr("scripts.lib.cio_ask_lifecycle.run_once", lambda **kw: {"ok": False, "source_errors": ["SecFilingEventsFile: missing"], "tracked_threads": 1})
    M.main(["--once", "--events-only"])
    assert got["outcome"] == "error" and got["outcome_reason"] == "source_error"

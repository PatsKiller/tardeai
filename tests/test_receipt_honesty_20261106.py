"""ANCHOR: RECEIPT_HONESTY_20261106 — a run that produced nothing must be able to say why, and a subject verdict must
not be read as the run's status. Synthetic fixtures only (the repo is public); no real lane, store or credential.

Four lanes were graded on 2026-11-06 for what their receipt did NOT say:

* n8n-pilot-dispatch / n8n-research-intake-consumer — their declared output document carried only ``as_of``, so the
  jobs page could not tie it to the run, fell back to "the receipt does not say why", and graded a healthy empty run
  ``EMPTY/unexpected``. The LaneRunReceipt next door said ``no_new_input`` all along.
* hermes-governance-api — the research-scope audit's WARN about the 30-day record was filed as ``summary.status``,
  which run_quality reads as the RUN's status, so a healthy warm graded DEGRADED whenever the audit was unhappy.
* audit-enrichment-coverage — the audit's own finding (members missing a surface) was filed as ``summary
  .symbols_with_gaps``; run_quality flags any summary key ending in _gaps as the run's own gap (covered in
  tests/test_refactor_w1_audit_reports_20261010.py).
"""
from datetime import datetime, timedelta, timezone
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import run_quality as Q  # noqa: E402

NOW = datetime(2026, 11, 6, 15, 7, tzinfo=timezone.utc)


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _evidence(doc, path, start):
    led = {"run_id": "r1", "mode": "live", "state": "RUN_DONE", "started": start, "duration_s": 1.0, "produced": 0,
           "reason": None, "why": None}
    run = {"mode": "live", "result": "succeeded", "started_at": z(start), "finished_at": z(start + timedelta(seconds=1)),
           "duration_s": 1.0, "run_id": "r1", "exit_code": 0, "reason": None, "source": "n8n run ledger"}
    lane = {"lane_id": doc["lane_id"], "state": "ACTIVE", "output_signal": {"kind": "file_mtime", "path": path},
            "scheduler": {"kind": "n8n", "stage": "canary"}, "dispatch": {"mode": "live"}}
    row = {"lane_id": doc["lane_id"], "state": "ACTIVE", "status": "ok", "runs": [run], "last_run": run}
    ev = {"receipt": doc, "receipt_path": path, "output_at": start + timedelta(seconds=1), "ledger": [led],
          "history": [], "contract": {"stage": "canary"}, "freshness": [], "freshness_known": True,
          "plausibility": [], "plausibility_known": True}
    return row, lane, ev


@pytest.mark.parametrize("module_name,lane_id,rel", [
    ("n8n_pilot_dispatch", "n8n-pilot-dispatch", "data/runtime/n8n_pilot_dispatch_last.json"),
    ("n8n_research_intake_consumer", "n8n-research-intake-consumer", "data/runtime/n8n_research_intake_last.json"),
])
def test_the_declared_output_document_is_also_a_receipt(module_name, lane_id, rel, tmp_path):
    """The state document must carry the run identity and the output verdict, and the page must read it as the run's
    own receipt — otherwise an honest empty run is graded 'the receipt does not say why'."""
    m = __import__(module_name)
    start = NOW - timedelta(minutes=30)
    state = {"schema": "SyntheticRun@v1", "lane_id": lane_id, "as_of": start.isoformat(), "mode": "apply", "ok": True,
             "lanes": [], "fired": 0, "listed": 0}
    output = {"produced_count": 0, "attempted_count": 0, "skipped_reasons": {}, "empty_reason": "no_new_input"}
    doc = m.state_document(state, output, now=start)

    assert doc["started_at"] == start.isoformat() and doc["finished_at"] and doc["status"] == "ok"
    assert doc["produced_count"] == 0 and doc["empty_reason"] == "no_new_input"
    # the dispatcher's own fields survive (no consumer of the state document loses a key)
    assert doc["as_of"] == start.isoformat() and doc["lanes"] == [] and doc["ok"] is True

    page = tmp_path / rel
    page.parent.mkdir(parents=True)
    page.write_text(json.dumps(doc))
    rc, rpath = Q.read_receipt({"lane_id": lane_id, "output_signal": {"kind": "file_mtime", "path": rel}}, tmp_path)
    assert rpath == rel and rc["empty_reason"] == "no_new_input"

    row, lane, ev = _evidence(doc, rel, start)
    q = Q.grade(row, lane, ev, now=NOW)
    assert (q["grade"], q["sub"]) == ("EMPTY", "nothing_due"), q["reasons"]


def test_governance_warm_files_the_audit_verdict_as_the_subject_not_the_run(monkeypatch):
    """A WARN about the 30-day research record is not a WARN about the warm."""
    import hermes_governance_api as g
    from lib import lane_last_receipt as llr

    written = []
    monkeypatch.setattr(g, "_governance_summary_compute", lambda: {"status": "WARN", "by_tier": {}, "window": {}})
    monkeypatch.setattr(g, "_write_cache", lambda d: None)
    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: written.append(k))
    assert g.main(["--warm"]) == 0
    summary = written[0]["summary"]
    assert summary["subject_status"] == "WARN"
    assert "status" not in summary and "verdict" not in summary
    assert Q.receipt_flags({"status": "ok", "summary": summary}) == []

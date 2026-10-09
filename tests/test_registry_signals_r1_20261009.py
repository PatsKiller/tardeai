"""Registry signals r1 (2026-10-09): three lanes whose output signal read as false NO_OUTPUT.

* cio-stance-classification-drain: the receipts file is appended only when a request is pending; the
  run log (one "[APPLY] pending=N" line every run) is the signal.
* watch-review-workers: two crontab lines (maria 16:05, cio 16:20) were one row with the maria log
  only; now one row per line, each with its own log.
* due-diligence-questions: max(created_at) does not move on a 0-row run; the */20 run log is the signal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}


def test_cio_stance_drain_signal_is_run_log_and_script_prints_every_run():
    sig = ROWS["cio-stance-classification-drain"]["output_signal"]
    assert sig == {"kind": "file_mtime", "path": "logs/cio_stance_classification_drain.log"}
    src = (ROOT / "scripts" / "drain_cio_stance_classification.py").read_text(encoding="utf-8")
    assert "pending={report['pending']}" in src


def test_watch_review_workers_split_one_row_per_crontab_line():
    maria, cio = ROWS["watch-review-workers"], ROWS["watch-review-workers-cio"]
    assert maria["scheduler"]["match"].endswith("--role maria")
    assert cio["scheduler"]["match"].endswith("--role cio")
    assert maria["output_signal"]["path"] == "logs/watch_review_maria.log"
    assert cio["output_signal"]["path"] == "logs/watch_review_cio.log"
    for row in (maria, cio):
        assert row["state"] == "ACTIVE"
        assert re.match(r"^\d+ 16 \* \* 1,3,5 ", row["scheduler"]["expression"])
    # no other row may also claim either line
    others = [r["lane_id"] for r in REG["lanes"]
              if "run_watch_review_workers.py" in str((r.get("scheduler") or {}).get("match") or "")]
    assert sorted(others) == ["watch-review-workers", "watch-review-workers-cio"]


def test_due_diligence_questions_signal_is_run_log():
    sig = ROWS["due-diligence-questions"]["output_signal"]
    assert sig == {"kind": "file_mtime", "path": "logs/due_diligence_questions.log"}


def test_n8n_governance_rows_cadence_without_state_change():
    assert ROWS["n8n-activation-grants"]["expected_cadence_hours"] == 0.5
    assert ROWS["n8n-workflow-drift-check"]["expected_cadence_hours"] == 1.0
    for lid in ("n8n-activation-grants", "n8n-workflow-drift-check"):
        assert ROWS[lid]["state"] == "NEVER_SCHEDULED"
        assert ROWS[lid]["scheduler"]["kind"] == "none"


def test_watch_intelligence_dependency_names_both_review_lanes():
    src = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert '"watch_intelligence": ("watch-review-workers", "watch-review-workers-cio"),' in src

"""2026-11-07 (LQ item 12): the diagnoser's receipt compared rows it was never allowed to touch against the rows it
produced, so a cycle that diagnosed every one of its in-scope rows still graded DEGRADED.

The live account that morning: 287 open ``n8n:*`` SIEM rows = 39 rows on 35 catalogue lanes (all diagnosed) + 6 of
the diagnoser's own rows + 242 rows whose lane is not in ``config/n8n_remediation_catalogue.json``. The receipt wrote
all 248 out-of-scope rows into ``skipped_reasons``, and ``run_quality.receipt_flags`` grades a lane DEGRADED whenever
its skip total exceeds what it produced — the right alarm for a cycle that quietly no-ops, the wrong one for a
population the lane can never act on.

The fix is reporting only, and it hides nothing: both halves stay in the receipt (``skipped_reasons`` for the run's
own skips, ``excluded_reasons`` for the rows outside its scope, plus ``catalogue_uncovered_rows``), and a cycle that
genuinely skips its way through the work still grades DEGRADED. Hermetic: repo files only, no DB, no model, no send.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_failure_diagnosis as L  # noqa: E402  (the CLI module: counts / _scope_receipt)
from scripts.lib import n8n_failure_diagnosis as D  # noqa: E402
from scripts.lib import run_quality as rq  # noqa: E402

SKIPPED = (
    [{"id": i, "lane": f"lane-{i}", "reason": "lane_not_in_catalogue"} for i in range(1, 243)]
    + [{"id": 500 + i, "lane": "n8n_failure_diagnosis", "reason": "own_row"} for i in range(6)]
    + [{"id": 700, "lane": "", "reason": "not_an_n8n_row"}]
    + [{"id": 800 + i, "lane": "storage-watch", "reason": "below_WARN"} for i in range(4)]
    + [{"id": 900 + i, "lane": "storage-watch", "reason": "already_diagnosed"} for i in range(3)]
)


def test_the_receipt_account_separates_out_of_scope_rows_from_the_runs_own_skips():
    scope = L._scope_receipt(SKIPPED)
    assert scope["skipped_reasons"] == {"below_WARN": 4, "already_diagnosed": 3}
    assert scope["excluded_reasons"] == {"lane_not_in_catalogue": 242, "own_row": 6, "not_an_n8n_row": 1}
    assert scope["catalogue_uncovered_rows"] == 242
    # nothing is dropped: every skipped row is still accounted for, in exactly one half
    assert sum(scope["skipped_reasons"].values()) + sum(scope["excluded_reasons"].values()) == len(SKIPPED)


def test_counts_reports_the_two_halves_separately():
    diag = {"results": [{} for _ in range(39)], "skipped": SKIPPED}
    c = L.counts(diag, [])
    assert c["eligible"] == 39
    assert c["skipped"] == 7                     # the run's own skips only
    assert c["excluded"] == 249                  # everything it was never allowed to touch
    assert c["skipped"] + c["excluded"] == len(SKIPPED)


def test_the_old_shape_graded_degraded_and_the_new_one_does_not():
    # the shape the lane wrote until 2026-11-07 — this is the regression
    old = {"ok": True, "skipped_reasons": {"lane_not_in_catalogue": 242, "own_row": 6}}
    assert rq.receipt_flags(old, 39) == ["skipped 248 items, more than it produced (39)"]

    new = {"ok": True, **L._scope_receipt(SKIPPED)}
    assert rq.receipt_flags(new, 39) == []


def test_a_cycle_that_really_skips_its_work_still_grades_degraded():
    # the alarm must keep working: an in-scope population the run left alone is a real defect
    receipt = {"ok": True, "skipped_reasons": {"below_WARN": 60}, "excluded_reasons": {"lane_not_in_catalogue": 242}}
    assert rq.receipt_flags(receipt, 39) == ["skipped 60 items, more than it produced (39)"]


def test_the_fix_grants_no_new_scope():
    # reporting changed; who may be diagnosed did not. A lane outside the catalogue is still excluded, and the
    # diagnoser still never diagnoses its own rows.
    cat = {e["lane_id"] for e in
           json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text(encoding="utf-8"))["lanes"]}
    rows = [{"id": 1, "component": "n8n:not-a-catalogue-lane", "event_type": "NO_OUTPUT",
             "severity": "CRITICAL", "message": "x"},
            {"id": 2, "component": "n8n:n8n_failure_diagnosis", "event_type": "NO_OUTPUT",
             "severity": "CRITICAL", "message": "y"},
            {"id": 3, "severity": "CRITICAL", "message": "z"}]
    ok, skipped = D.eligible(rows, cat, min_severity="WARN", done={})
    assert ok == []
    assert [s["reason"] for s in skipped] == ["lane_not_in_catalogue", "own_row", "not_an_n8n_row"]
    # every catalogue lane may still hold a real lane id (a rename would silently empty the eligible set)
    assert all("/" not in lane for lane in cat) and "storage-watch" in cat

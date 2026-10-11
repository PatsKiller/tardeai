"""approval-escalate reads a board and does not approve or send."""
from __future__ import annotations

import json

from scripts.approval_escalate import build_report, run


def test_report_names_expiring_rows_and_claims_no_authority():
    board = {
        "status": "OK",
        "expiring_count": 1,
        "expiring": [{"id": "grant-1", "kind": "grant"}],
    }
    report = build_report(board)
    assert report["expiring_ids"] == ["grant-1"]
    assert report["authority"] == "READ_ONLY_ADVISORY"
    assert "does not approve" in report["note"]


def test_dry_run_writes_nothing_and_apply_writes_a_receipt(tmp_path):
    board = {"status": "OK", "expiring": [], "expiring_count": 0}

    def loader():
        return board

    dry = run(apply=False, root=tmp_path, board_loader=loader)
    assert dry["applied"] is False
    assert not (tmp_path / "data/runtime/approval-escalate_last.json").exists()
    applied = run(apply=True, root=tmp_path, board_loader=loader)
    assert applied["applied"] is True
    body = json.loads((tmp_path / "data/runtime/approval-escalate_last.json").read_text())
    assert body["schema"] == "LaneRunReceipt@v1"
    assert body["ok_at"]
    assert body["report"]["status"] == "OK"

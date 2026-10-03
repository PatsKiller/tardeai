"""CIO Desk Outcomes / Hermes cards: count what the stores actually say.

Measured 2026-10-03 on prod:
- outcome_checkpoints.jsonl is append-only (20,637 rows for 18,004 checkpoints).
  The cockpit counted every row and filed 1,337 terminal NOT_PRICE_RESOLVABLE
  verdicts as "due", so the card read "1127 due, matured 0" while 354
  checkpoints had resolved and only 14 were waiting on data.
- 16 held theses stored by the shared spine as POPULATED graded A/PASS but sat
  outside SUBSTANTIVE_STATES, so substantive read 3/21 and research_up_thesis_flat
  fired. Graded by their own bucket it is 19/21.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib import cio_held_thesis_coverage as cov
from scripts.lib.cio_scorecard import _outcomes_tile
from scripts.lib.r17_checkpoint_binding import learning_cockpit_from_store

PAST = "2026-01-01T00:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"


def _store(root: Path, rows: list[dict]) -> None:
    p = root / "data" / "cio" / "outcome_checkpoints.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_cockpit_counts_each_checkpoint_once_by_its_latest_row(tmp_path):
    _store(tmp_path, [
        {"checkpoint_id": "a", "status": "SCHEDULED", "due_at": PAST},
        {"checkpoint_id": "a", "status": "RESOLVED", "due_at": PAST, "outcome_id": "o1"},
        {"checkpoint_id": "b", "status": "SCHEDULED", "due_at": PAST},
        {"checkpoint_id": "b", "status": "NOT_PRICE_RESOLVABLE", "due_at": PAST},
        {"checkpoint_id": "c", "status": "SCHEDULED", "due_at": PAST},
        {"checkpoint_id": "d", "status": "SCHEDULED", "due_at": FUTURE},
    ])
    s = learning_cockpit_from_store(tmp_path)
    assert s["checkpoints_n"] == 4 and s["checkpoint_rows_n"] == 6
    assert s["matured_outcomes"] == 1
    assert s["not_resolvable"] == 1
    assert s["outcomes_due"] == 1  # only c is genuinely awaiting resolution
    assert s["checkpoint_counts"]["PENDING"] == 1


def test_outcomes_tile_reads_resolved_checkpoints_as_matured(tmp_path):
    cockpit = {"outcomes_due": 14, "matured_outcomes": 354, "not_resolvable": 1337}
    tile = _outcomes_tile({"learning": {"outcomes": {"matured": 0}}, "learning_cockpit": cockpit,
                           "memory_behavior_influence": 0})
    assert tile["status"] == "working"
    metrics = {m["label"]: m["value"] for m in tile["metrics"]}
    assert metrics["Matured"] == 354 and metrics["Outcomes due"] == 14
    assert metrics["Not price-resolvable"] == 1337


def test_outcomes_tile_still_degrades_when_nothing_matures():
    cockpit = {"outcomes_due": 500, "matured_outcomes": 0, "not_resolvable": 0}
    tile = _outcomes_tile({"learning": {"outcomes": {"matured": 0}}, "learning_cockpit": cockpit,
                           "memory_behavior_influence": 0})
    assert tile["status"] == "degraded"


def _row(monkeypatch, fields: dict) -> dict:
    import scripts.lib.symbol_thesis_attach as attach

    monkeypatch.setattr(attach, "thesis_fields_for_symbol", lambda symbol, root=None: dict(fields))
    return cov.coverage_row_for_symbol("XYZ", root=Path("."))


def test_spine_populated_pass_thesis_counts_as_substantive(monkeypatch):
    row = _row(monkeypatch, {"thesis_state": "POPULATED", "substantiveness_bucket": "PASS",
                             "has_current_symbol_thesis": True})
    assert row["thesis_state"] == "CURRENT" and row["needs_substance"] is False


def test_spine_populated_thin_thesis_is_flagged_for_substance(monkeypatch):
    row = _row(monkeypatch, {"thesis_state": "POPULATED", "substantiveness_bucket": "THIN",
                             "has_current_symbol_thesis": True})
    assert row["thesis_state"] == "THIN" and row["needs_substance"] is True


def test_spine_populated_without_a_grade_is_not_promoted(monkeypatch):
    row = _row(monkeypatch, {"thesis_state": "POPULATED", "has_current_symbol_thesis": True})
    assert row["thesis_state"] == "POPULATED"

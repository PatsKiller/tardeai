"""The cio-wake-turn-effects lane must prove its run with what it PRODUCED.

Measured 2026-11-07: the lane was graded EMPTY every day for a month. Its
declared output signal was the mtime of ``data/cio/wake_turn_effects.jsonl`` —
an artifact the unit behind it (``tradeai-cio-reactive.timer``, running
``scripts/cio_reactive_cycle.py``) has never written. The only writer is
``cio_rehydrate._record_turn_effect``, reached from the defer-honored branch of
``apply_after_cycle``, and the one caller that passes a defer lesson
(``attach_operator_turn``) has no live scheduler. So the signal could not be
satisfied by any run, and the page said "ran 1 min ago and exited ok, but its
output was not written by that run" forever.

Two things are pinned here, because either one alone regresses silently:

1. the lane's signal is the unit's OWN per-run receipt, read against ``ok_at``
   (the shape LaneRunReceipt documents: "the durable artifact a dispatcher or
   the registry reads instead, as a json_key signal on ok_at");
2. the receipt carries ``produced_count``, because a receipt-only signal with
   no item count grades UNPROVEN (run_quality.grade), which is exactly the
   "exit code 0 is not evidence" defect AGENTS.md rule 8 names.

Hermetic: a synthetic cycle result and ``tmp_path``. No DB, no host state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.cio_reactive_cycle as cycle  # noqa: E402
from scripts.lib import lane_last_receipt, run_quality  # noqa: E402

LANE = "cio-wake-turn-effects"
REGISTRY = ROOT / "config" / "lane_registry.json"


def _lane_row() -> dict:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = [r for r in reg["lanes"] if r.get("lane_id") == LANE]
    assert len(rows) == 1, f"expected exactly one {LANE} row, found {len(rows)}"
    return rows[0]


def test_the_lane_signal_is_its_own_receipt_keyed_on_ok_at():
    row = _lane_row()
    sig = row["output_signal"]
    assert sig["kind"] == "json_key", sig
    assert sig["path"] == f"data/runtime/{LANE}_last.json", sig
    assert sig["key"] == "ok_at", sig
    # The signal path must be the path write_lane_receipt actually writes, or the
    # page's receipt_is_output check is false and the signal reads nothing.
    assert lane_last_receipt.receipt_path(LANE).name == Path(sig["path"]).name
    assert row["expected_cadence_hours"] <= 1.0, (
        "the unit is a 2-minute timer; a 24 h cadence calls a working lane late"
    )


def test_the_old_conditional_artifact_is_no_longer_declared_as_output():
    # The reactive cycle must not claim a file it has no code to write. This
    # assertion is the regression: it fails if someone re-points the signal at
    # wake_turn_effects.jsonl without wiring a writer into this unit.
    src = (ROOT / "scripts" / "cio_reactive_cycle.py").read_text(encoding="utf-8")
    assert "wake_turn_effects" not in src, (
        "cio_reactive_cycle.py declares no writer for wake_turn_effects, so it "
        "cannot be this lane's output proof"
    )
    assert _lane_row()["output_signal"]["path"].endswith(f"{LANE}_last.json")


def test_production_counts_name_written_rows_not_scanned_candidates():
    quiet = {
        "event_enqueued": [],
        "goal_enqueue": {"enqueued": [], "skipped_dedup": [], "blocked_not_ready": []},
        "situations": {"candidates": 22, "plans_created": [], "dedup_skipped": []},
        "curation_emitted": 0,
    }
    produced, attempted, empty_reason = cycle.production_counts(quiet)
    assert produced == 0
    # 22 candidates were examined and produced nothing: examining is not output.
    assert attempted == 0
    assert empty_reason == "no_wake_no_situation_plan_no_curation_due"
    # A benign "no_*" reason is what run_quality treats as an idle slot rather
    # than an unexplained empty one.
    assert run_quality._BENIGN_SKIP.search(empty_reason)

    busy = {
        "event_enqueued": [{"wake_job_id": "w1"}, {"wake_job_id": "w2"}],
        "goal_enqueue": {"enqueued": [{"wake_job_id": "w3"}],
                         "skipped_dedup": ["g1"], "blocked_not_ready": []},
        "situations": {"candidates": 22, "plans_created": [{"plan_id": "p1"}],
                       "dedup_skipped": ["s1", "s2"]},
        "curation_emitted": 1,
    }
    produced, attempted, empty_reason = cycle.production_counts(busy)
    assert (produced, empty_reason) == (5, None)
    assert attempted == 5 + 1 + 2

    # The live result mixes shapes: lists here, plain counts there. A len() on
    # the int raised TypeError against the 2026-11-07T02:25Z status file.
    mixed = {
        "event_enqueued": [],
        "goal_enqueue": {"enqueued": [], "blocked_not_ready": [{"goal_id": "g1"}],
                         "errors": []},
        "situations": {"candidates": 22, "plans_created": [], "dedup_skipped": 22},
        "curation_emitted": 1,
    }
    produced, attempted, empty_reason = cycle.production_counts(mixed)
    assert (produced, attempted, empty_reason) == (1, 24, None)


def test_production_counts_never_raises_on_a_missing_or_odd_result():
    for value in (None, {}, {"event_enqueued": None, "goal_enqueue": "x",
                             "situations": None, "curation_emitted": "oops"}):
        produced, attempted, empty_reason = cycle.production_counts(value)
        assert produced == 0 and attempted == 0
        assert empty_reason == "no_wake_no_situation_plan_no_curation_due"


def test_the_written_receipt_can_prove_its_count(tmp_path):
    """A v2 receipt round-trips into the count the page reads."""
    path = tmp_path / f"{LANE}_last.json"
    written = lane_last_receipt.write_lane_receipt(
        LANE, ok=True, exit_code=0, started_at="2026-11-07T02:00:00+00:00",
        script="cio_reactive_cycle.py", summary={"completed": True},
        produced_count=1, attempted_count=4,
        empty_reason=None, path=path,
    )
    assert written is not None, "receipt write failed"
    doc = json.loads(Path(written).read_text(encoding="utf-8"))
    assert doc["lane_id"] == LANE
    assert doc["ok_at"], "the declared signal key must be present"
    assert run_quality.item_count(doc) == (1, "produced_count")


def test_the_receipt_exists_for_every_real_run_and_never_for_a_dry_run():
    # A dry run returns before any receipt write; the real path computes counts
    # from the result it hands back. Source-level so the guard survives a
    # refactor of the surrounding function, and narrow enough to name the line.
    src = (ROOT / "scripts" / "cio_reactive_cycle.py").read_text(encoding="utf-8")
    main_src = src[src.index("def main("):]
    assert "production_counts(res)" in main_src
    assert "produced_count=produced" in main_src
    dry = main_src[: main_src.index("production_counts(res)")]
    assert "return 0" in dry, "the dry-run branch must return before the receipt write"

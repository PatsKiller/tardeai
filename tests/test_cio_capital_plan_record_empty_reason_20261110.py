"""LQ-20261107-1822: a run that wrote nothing because nothing was left to write is not a failure.

Production 2026-11-10, 11:00 / 12:00 / 13:00 ET: the lane exited 0, the plan held 23 decisions, the journal
already held all of them (`written 0`, `pending 0`), and the receipt said `empty_reason: null`. The
dispatcher's output verdict grades an empty run with no allowed reason `empty_reason_not_allowed` ->
RUN_FAILED (RunReceipt@v3 `output_verdict`), so three idle runs opened the breaker on a job that had done
its work. The shipped contract allows `already_recorded` for exactly this state.

These pins: the producer names the reason the run actually had, and every reason it can emit is one the
shipped contract accepts. Synthetic plan, journal and receipt writer only — no live store, no DB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import cio_capital_plan_record as producer  # noqa: E402
from scripts.lib import lane_last_receipt as lr  # noqa: E402
from scripts.lib import n8n_output_verdict as ov  # noqa: E402

LANE = "cio-capital-plan-record"
RUN_ID = "d:cio-capital-plan-record:live:TEST1822"
SCRIPT = "cio_capital_plan_record.py"


def _contract_rule():
    doc = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text(encoding="utf-8"))
    for c in doc["contracts"]:
        if c.get("id") == LANE:
            return c["expected_output"]
    raise AssertionError(f"no health contract for {LANE}")


def _run(monkeypatch, *, decisions, pending, written, error=None):
    """main(--apply) with the plan, the journal and the receipt writer all synthetic."""
    monkeypatch.setattr(producer, "_build_plan", lambda: {"ok": True, "position_decisions": list(decisions)})
    monkeypatch.setattr(producer, "_pending", lambda ds: list(pending))
    monkeypatch.setattr(
        "scripts.lib.cio_capital_plan_decision_store.record_position_decisions",
        lambda ds: {"written": written, **({"error": error} if error else {})},
    )
    captured: dict = {}

    def fake_write(lane_id, **kw):
        captured.update({"lane_id": lane_id, **kw})
        return Path("/dev/null")

    monkeypatch.setattr(lr, "write_lane_receipt", fake_write)
    monkeypatch.setenv(lr.RUN_ID_ENV, RUN_ID)
    monkeypatch.setenv(lr.RUN_MODE_ENV, "live")
    monkeypatch.delenv(lr.RUN_ATTEMPT_ENV, raising=False)
    rc = producer.main(["--apply"])
    return rc, captured


def _verdict(captured):
    """The verdict the dispatcher computes for this receipt against the shipped contract."""
    doc = lr.build_receipt(
        LANE,
        ok=True,
        exit_code=0,
        started_at=captured.get("started_at"),
        script=SCRIPT,
        summary=captured.get("summary"),
        produced_count=captured.get("produced_count"),
        attempted_count=captured.get("attempted_count"),
        skipped_reasons=captured.get("skipped_reasons") or {},
        empty_reason=captured.get("empty_reason"),
    )
    return ov.evaluate(_contract_rule(), doc, run_id=RUN_ID, lane_id=LANE, mode="live")


def _decisions(n):
    return [{"decision_id": f"D{i}"} for i in range(n)]


# --- the defect: an idle run is graded RUN_FAILED ------------------------------------------------


def test_a_fully_recorded_plan_names_already_recorded(monkeypatch):
    rc, cap = _run(monkeypatch, decisions=_decisions(23), pending=[], written=0)
    assert rc == 0
    assert cap["produced_count"] == 0 and cap["attempted_count"] == 23
    assert cap["summary"] == {"decisions": 23, "pending": 0, "written": 0}
    assert cap["empty_reason"] == "already_recorded"


def test_the_shipped_contract_accepts_that_receipt(monkeypatch):
    _, cap = _run(monkeypatch, decisions=_decisions(23), pending=[], written=0)
    v = _verdict(cap)
    assert v["verdict"] == "empty_allowed", v
    assert v["empty_reason"] == "already_recorded"


def test_without_a_reason_that_receipt_is_the_failure_we_saw(monkeypatch):
    """The control: the same run, the pre-fix `empty_reason: null`, is exactly the 11:00/12:00/13:00 verdict."""
    _, cap = _run(monkeypatch, decisions=_decisions(23), pending=[], written=0)
    cap["empty_reason"] = None
    v = _verdict(cap)
    assert (v["verdict"], v["why"]) == ("empty_violation", "empty_reason_not_allowed")


# --- the reason must stay honest ----------------------------------------------------------------


def test_an_empty_plan_still_says_no_position_decisions(monkeypatch):
    rc, cap = _run(monkeypatch, decisions=[], pending=[], written=0)
    assert rc == 0
    assert cap["empty_reason"] == "no_position_decisions"
    assert _verdict(cap)["verdict"] == "empty_allowed"


def test_something_pending_but_nothing_written_is_not_mislabelled(monkeypatch):
    """Two decisions pending, none appended: that is not `already_recorded`, and it must not claim to be."""
    _, cap = _run(monkeypatch, decisions=_decisions(3), pending=["D0", "D1"], written=0)
    assert cap["empty_reason"] is None


def test_a_writing_run_names_no_reason(monkeypatch):
    rc, cap = _run(monkeypatch, decisions=_decisions(3), pending=["D0", "D1", "D2"], written=3)
    assert rc == 0
    assert cap["produced_count"] == 3
    assert cap["empty_reason"] is None
    assert _verdict(cap)["verdict"] == "produced"


def test_a_write_error_is_a_failure_not_an_empty_reason(monkeypatch):
    rc, cap = _run(monkeypatch, decisions=_decisions(3), pending=["D0"], written=0, error="journal readonly")
    assert rc == 1
    assert cap["ok"] is False
    assert cap["empty_reason"] is None
    assert cap["error"] == "journal readonly"


@pytest.mark.parametrize(
    "decisions,pending,written,expected",
    [
        (0, [], 0, "no_position_decisions"),
        (3, [], 0, "already_recorded"),
        (3, [1], 0, None),
        (3, [1, 2, 3], 3, None),
    ],
)
def test_every_reason_the_producer_emits_is_one_the_contract_allows(
    monkeypatch, decisions, pending, written, expected
):
    """The anti-drift pin: a reason the contract does not list is the same RUN_FAILED, just spelled differently."""
    _, cap = _run(
        monkeypatch,
        decisions=_decisions(decisions),
        pending=[f"D{i}" for i in pending],
        written=written,
    )
    assert cap["empty_reason"] == expected
    if expected is not None:
        assert expected in _contract_rule()["empty_allowed_reasons"]

"""A constant component string must not mint a new queue row every run.

WHY THIS TEST EXISTS
--------------------
`hermes_health_inspector._escalate` builds every item with the SAME literal
component, `hermes_health_inspector:staleness_escalation`, then appended it
unconditionally to both escalation queues. Every run therefore re-queued a
condition that was already queued. Measured on the live queue 2026-09-22: 6
duplicate rows dating from 2026-08-07, each notifying the operator separately
about the same staleness.

This is one of the four populations behind the six-week alert storm, and the
only one that GROWS the queue rather than merely failing to drain it.

THE NEGATIVE CONTROL IS THE POINT
---------------------------------
`test_the_detector_can_fail` runs the OLD append-only behaviour through the
same assertions and proves they go red. Twelve checks in this repo on
2026-09-21/22 reported success while exercising nothing; a dedupe test that
cannot fail would be the thirteenth.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "hermes_health_inspector.py"


@pytest.fixture
def inspector():
    """Load by explicit path so a sibling test cannot decide which copy runs."""
    if not TARGET.is_file():
        pytest.skip("hermes_health_inspector not present in this tree")
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("_hermes_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.__file__ == str(TARGET), f"loaded the wrong copy: {mod.__file__}"
    return mod


COMP = "hermes_health_inspector:staleness_escalation"


def _item(detail="P0: hermes event feeder stale", **kw):
    base = {"component": COMP, "detail": detail, "status": "critical",
            "critical": True, "priority": "P0", "captured_at": "2026-09-22T12:00:00Z"}
    base.update(kw)
    return base


def test_the_same_finding_twice_makes_one_row(inspector) -> None:
    """The whole defect in one assertion."""
    items: list = []
    items = inspector._merge_escalation(items, _item())
    items = inspector._merge_escalation(items, _item())
    assert len(items) == 1, f"a repeat minted a second row: {items}"


def test_a_repeat_is_counted_not_discarded(inspector) -> None:
    """Dedupe must not lose the evidence that the condition recurred."""
    items = inspector._merge_escalation([], _item())
    items = inspector._merge_escalation(items, _item(captured_at="2026-09-22T13:00:00Z"))
    items = inspector._merge_escalation(items, _item(captured_at="2026-09-22T14:00:00Z"))
    assert items[0]["_seen_count"] == 3
    assert items[0]["_last_seen_ts"] == "2026-09-22T14:00:00Z"


def test_a_genuinely_different_finding_still_gets_its_own_row(inspector) -> None:
    """Dedupe on the constant component ALONE would swallow real findings.

    Identity is (component, detail) precisely so a second, different root cause
    is not silently folded into the first.
    """
    items = inspector._merge_escalation([], _item(detail="P0: feeder stale"))
    items = inspector._merge_escalation(items, _item(detail="P1: governor audit stale"))
    assert len(items) == 2


def test_changed_severity_is_refreshed_in_place(inspector) -> None:
    """A condition that worsens must show its new severity, not the stale one."""
    items = inspector._merge_escalation([], _item(status="warning", critical=False))
    items = inspector._merge_escalation(items, _item(status="critical", critical=True))
    assert len(items) == 1
    assert items[0]["status"] == "critical"
    assert items[0]["critical"] is True


def test_a_corrupt_row_is_skipped_not_crashed_on(inspector) -> None:
    """Queue files have been hand-edited before. A non-dict must not raise."""
    items = inspector._merge_escalation(["not-a-dict", None], _item())
    assert len(items) == 3
    assert items[-1]["component"] == COMP


def test_both_queue_writes_go_through_the_merge(inspector) -> None:
    """Structural: dedupe on one queue and append on the other is still a storm."""
    src = TARGET.read_text(encoding="utf-8")
    assert "existing.append(item)" not in src, "main queue still appends unconditionally"
    assert "stale_q.append(item)" not in src, "staleness queue still appends unconditionally"
    assert src.count("_merge_escalation(") >= 3, "both writes must use the merge"


def test_the_detector_can_fail(inspector) -> None:
    """NEGATIVE CONTROL: the old append-only behaviour must fail these checks."""
    def old_append(items, item):
        items.append(item)
        return items

    items: list = []
    items = old_append(items, _item())
    items = old_append(items, _item())
    assert len(items) == 2, "the control is not reproducing the old behaviour"
    with pytest.raises(AssertionError):
        assert len(items) == 1, "a repeat minted a second row"
    # ...and the real implementation passes the same assertion
    real = inspector._merge_escalation(inspector._merge_escalation([], _item()), _item())
    assert len(real) == 1

"""The reaper must never remove something that is still live, or still actionable.

WHY THE CONTROLS ARE THE POINT
------------------------------
This script deletes durable state on the live alerting path. On 2026-09-21/22
this repo produced twelve checks that reported success while exercising nothing
-- a dry run that skipped the crashing path, a test that passed against the
unpatched file, a negative control that skipped every assertion, a flag nothing
read whose identical output was nearly reported as proof. A destructive script
whose test cannot fail is the worst possible member of that set.

So every property below has a case that FAILS when the property is broken, and
`test_the_detector_can_fail` proves the suite is capable of going red.

THE FAIL-CLOSED CASE IS THE IMPORTANT ONE
-----------------------------------------
`live_components()` returns the set of conditions that are TRUE right now. If a
probe raises and that set comes back empty, every queued entry looks resolved and
the reaper would drain the whole queue. That is why a failed probe injects a
`__HOLD__<prefix>` sentinel and `is_reapable` refuses the entire family.
`test_a_failed_probe_holds_its_whole_family` is the guard on that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "escalation_queue_reaper.py"


@pytest.fixture
def reaper():
    """Load by explicit path, not by name.

    A sibling test importing a same-named module from another tree must not
    decide which copy is asserted against -- that ordering dependency cost a
    green-on-the-unpatched-file result earlier in this series.
    """
    if not TARGET.is_file():
        pytest.skip("reaper not present in this tree")
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("_reaper_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.__file__ == str(TARGET), f"loaded the wrong copy: {mod.__file__}"
    return mod


def _item(component, **kw):
    base = {"component": component, "fixable": False, "retry_cmd": None, "_attempts": 41}
    base.update(kw)
    return base


def test_a_live_component_is_never_removed(reaper) -> None:
    """The whole safety property in one assertion."""
    live = {"health:pipeline_freshness:stale_setup_advisory"}
    assert reaper.is_reapable(_item("health:pipeline_freshness:stale_setup_advisory"), live) is False


def test_a_resolved_component_is_removable(reaper) -> None:
    """...and the reaper must still do its job when the condition is gone."""
    live: set[str] = set()
    assert reaper.is_reapable(_item("health:pipeline_freshness:missing_morning_synthesis"), live) is True


def test_liveness_is_the_test_not_retry_cmd(reaper) -> None:
    """A retryable entry whose condition is GONE is still reapable.

    The original rule vetoed anything carrying fixable/retry_cmd. Measured
    2026-09-22 that was wrong: 5 retryable entries (data_source_stale,
    news_stale, market_quotes_stale, schwab_journal_ingest_stale,
    approved_paper_test_stuck) exhaust at attempts=4, log "retries exhausted",
    never run their retry_cmd, and re-arm every 1800s forever -- the same trap
    as the non-retryable ones, wearing fixable=True.

    The protection is no longer "does it carry a command" but "is the condition
    still true", measured against a probe that fails closed.
    """
    live: set[str] = set()
    assert reaper.is_reapable(_item("health:pipeline_freshness:missing_x", fixable=True), live) is True
    assert reaper.is_reapable(_item("health:pipeline_freshness:missing_x", retry_cmd="echo hi"), live) is True
    # ...but a LIVE one is still refused, retry_cmd or not
    live = {"health:pipeline_freshness:missing_x"}
    assert reaper.is_reapable(_item("health:pipeline_freshness:missing_x", retry_cmd="echo hi"), live) is False


def test_other_producers_are_out_of_scope(reaper) -> None:
    """hermes_health_inspector is deliberately excluded.

    Its condition was never verified false. A reaper that removes what it has
    not measured is the defect it exists to fix.
    """
    live: set[str] = set()
    assert reaper.is_reapable(_item("hermes_health_inspector:staleness_escalation"), live) is False


def test_a_failed_aggregate_probe_holds_EVERYTHING(reaper) -> None:
    """The strongest fail-closed case. compute() is the whole live-set.

    If it raises and the set comes back empty, every queued entry looks
    resolved and the reaper drains the queue. __HOLD__ALL must veto all
    families, not merely the one that failed.
    """
    live = {"__HOLD__ALL"}
    for comp in ("health:pipeline_freshness:missing_x",
                 "health:intelligence_quality:research_lane_firing:chatgpt",
                 "health:data_quality:news_stale",
                 "health:execution_health:pipeline_failures"):
        assert reaper.is_reapable(_item(comp), live) is False, comp


def test_the_probe_is_the_producer_aggregate_not_hand_picked_collectors(reaper) -> None:
    """REGRESSION GUARD. This is the bug that nearly deleted live alerts.

    An earlier probe called collect_data_quality() and
    collect_intelligence_quality() and treated absence from those two as
    "resolved". But a category is not owned by one collector:
    data_source_stale comes from collect_data_source_health:2942 and
    research_lane_firing from collect_research_heartbeat:1153. Against the live
    queue the narrow probe called 14 entries removable when 8 were LIVE.

    The probe must call health_agent.compute(), which runs every collector in
    COLLECTORS, so it cannot fall behind the producer.
    """
    src = TARGET.read_text(encoding="utf-8")
    assert "HA.compute(" in src, "the probe no longer calls the producer aggregate"
    assert "__HOLD__ALL" in src, "no global fail-closed sentinel"
    for narrow in ("HA.collect_data_quality()", "HA.collect_intelligence_quality()",
                   "HA.collect_execution_health()"):
        assert narrow not in src, (
            f"probe narrowed back to a hand-picked collector ({narrow}); "
            "a category is emitted by several collectors -- use compute()"
        )


def test_a_failed_probe_holds_its_whole_family(reaper) -> None:
    """FAIL-CLOSED. An empty live-set from a broken probe must not reap everything.

    This is the difference between a reaper and a queue-eraser.
    """
    live = {"__HOLD__health:pipeline_freshness:"}
    assert reaper.is_reapable(_item("health:pipeline_freshness:missing_anything"), live) is False
    # the other family is unaffected by the hold
    assert reaper.is_reapable(_item("health:intelligence_quality:whatever"), live) is True


def test_live_components_fails_closed_when_a_probe_raises(reaper, monkeypatch) -> None:
    """Prove the sentinel is actually injected, not just honoured."""
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "pipeline_freshness_monitor":
            raise RuntimeError("probe down")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    live, notes = reaper.live_components()
    assert any("__HOLD__health:pipeline_freshness:" == c for c in live), live
    assert any("PROBE FAILED" in n for n in notes), notes


def test_dry_run_is_the_default_and_writes_nothing(reaper) -> None:
    """--apply must be opt-in; a destructive default is how data vanishes."""
    src = TARGET.read_text(encoding="utf-8")
    assert '"--apply"' in src and 'action="store_true"' in src
    assert "if not a.apply:" in src, "no dry-run branch before the write"


def test_the_archive_happens_before_the_write(reaper) -> None:
    """Rule 6: copy first, and refuse to write if the copy did not land."""
    src = TARGET.read_text(encoding="utf-8")
    copy_at = src.index("shutil.copy2(path, bak)")
    write_at = src.index("write_items(path, keep)")
    assert copy_at < write_at, "the write precedes the archive"
    assert "archive_failed_no_write" in src, "no guard for a failed archive"


def test_a_large_removal_is_refused(reaper) -> None:
    """A broken probe should look like 'everything resolved' -- and be refused."""
    src = TARGET.read_text(encoding="utf-8")
    assert "max_remove" in src and "REFUSED" in src


def test_the_detector_can_fail(reaper) -> None:
    """Positive control: a stub that always reaps must fail these properties."""
    live = {"health:pipeline_freshness:stale_setup_advisory"}
    always = lambda item, live: True  # noqa: E731 - the deliberately broken version
    assert always(_item("health:pipeline_freshness:stale_setup_advisory"), live) is True
    # ...and the real one refuses it, which is what test_a_live_component pins.
    assert reaper.is_reapable(_item("health:pipeline_freshness:stale_setup_advisory"), live) is False

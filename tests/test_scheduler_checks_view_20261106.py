"""SchedulerChecks@v1 / SchedulerLane@v1 slices (Automation merged into Jobs & n8n, 2026-11-06). Synthetic rows only."""
from scripts.lib.scheduler_operations import checks_view, is_problem, lane_view


def _row(lane, state, **kw):
    r = {"lane_id": lane, "runtime_state": state, "health_reason": None, "slo_verdict": "NOT_MEASURED",
         "duplicate_scheduler": False, "scheduler_drift": False, "declared_in_registry": True,
         "timeline": [{"run_id": "r1"}], "scheduler_observations": [{"id": "x"}], "evidence_sources": []}
    r.update(kw)
    return r


PROJ = {"schema": "SchedulerOperations@v1", "authority": "READ_ONLY_ADVISORY", "status": "OK",
        "as_of": "2026-11-06T12:00:00Z", "source_sha": "abc", "sources": {"cron": {"measured": True}}, "rows": [
            _row("a-live", "LIVE"), _row("b-drift", "DRIFT", scheduler_drift=True),
            _row("c-orphan", "ORPHANED", declared_in_registry=False), _row("d-nm", "NOT_MEASURED", scheduler_drift=True),
            _row("e-nosig-missing", "NO_SIGNAL", health_reason="NO_SIGNAL_WITH_REASON missing; x"),
            _row("f-nosig-declared", "NO_SIGNAL", health_reason="declared: event only"),
            _row("g-dup", "LIVE", duplicate_scheduler=True), _row("h-slo", "LIVE", slo_verdict="CADENCE_LT_P95"),
            _row("i-silent", "EXPECTED_SILENT", duplicate_scheduler=True)]}


def test_problem_rule_matches_the_ui():
    got = {r["lane_id"] for r in PROJ["rows"] if is_problem(r)}
    assert got == {"b-drift", "c-orphan", "e-nosig-missing", "g-dup", "h-slo"}


def test_checks_view_is_slim_and_counts_every_row():
    v = checks_view(PROJ)
    assert v["schema"] == "SchedulerChecks@v1" and v["total"] == 9 and v["source_sha"] == "abc"
    assert [r["lane_id"] for r in v["rows"]] == ["b-drift", "c-orphan", "e-nosig-missing", "g-dup", "h-slo"]
    assert all("timeline" not in r and "scheduler_observations" not in r for r in v["rows"])
    assert v["state_counts"]["LIVE"] == 3 and v["state_counts"]["NOT_MEASURED"] == 1
    assert v["unregistered"] == 1 and v["duplicate"] == 2 and v["drift"] == 2
    assert PROJ["rows"][1]["timeline"]  # the projection itself is not mutated


def test_lane_view_returns_one_full_row_or_null():
    v = lane_view(PROJ, "b-drift")
    assert v["schema"] == "SchedulerLane@v1" and v["row"]["lane_id"] == "b-drift" and v["row"]["timeline"]
    assert lane_view(PROJ, "nope")["row"] is None
    assert checks_view({"rows": []})["rows"] == []

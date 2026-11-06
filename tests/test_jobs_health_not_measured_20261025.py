"""Jobs & health: a missed count that cannot be measured is a gap, never 0 (live audit 2026-10-25).

Synthetic lanes and receipts only; no live services, no registry or ledger reads.
"""
from datetime import datetime, timedelta, timezone

from scripts.lib import jobs_health as J

NOW = datetime(2026, 10, 23, 16, 20, tzinfo=timezone.utc)


def lane(name, **extra):
    return {"lane_id": name, "state": "ACTIVE", "expected_cadence_hours": 1 / 12,
            "scheduler": {"kind": "cron", "expression": "*/5 9-16 * * 1-5"},
            "output_signal": {"kind": "file_mtime", "path": f"logs/{name}.log"}, **extra}


def run(name, at):
    base = {"run_id": f"{name}-run", "lane_id": name, "mode": "live", "state": "RUN_DONE",
            "exit_code": 0, "finished_at": at.isoformat(), "requested_at": at.isoformat()}
    return {**base, "receipt": {**base, "schema": "RunReceipt@v3", "output_verdict": {"verdict": "produced"}}}


def build(lanes, runs=(), gaps=None):
    snapshot = {"events": [], "successes": {}, "collection_gaps": list(gaps or [])}
    return J.build({"lanes": lanes}, snapshot, list(runs), {}, now=NOW, trading_day=lambda d: d.weekday() < 5)


def test_unmeasured_jobs_make_missed_unmeasured_not_zero():
    report = build([lane("job-a"), lane("job-b", scheduler={"kind": "systemd", "expression": "fixture"}),
                    lane("job-c")], runs=[run("job-c", NOW)])
    summary = report["summary"]
    assert summary["missed"] == 0  # measured floor stays numeric for existing readers
    assert summary["not_measured"] == summary["unknown"] == 2
    assert summary["missed_measured"] is False
    assert "2 jobs not measured" in summary["gap_reasons"]["missed"]
    assert summary["gap_reasons"]["not_measured"]


def test_fully_measured_report_has_a_real_zero():
    summary = build([lane("job-c")], runs=[run("job-c", NOW)])["summary"]
    assert summary["not_measured"] == 0 and summary["missed"] == 0
    assert summary["missed_measured"] is True
    assert summary["gap_reasons"] == {"missed": None, "not_measured": None}


def test_collection_gap_also_makes_missed_unmeasured():
    summary = build([lane("job-c")], runs=[run("job-c", NOW)], gaps=["run ledger unavailable"])["summary"]
    assert summary["missed_measured"] is False
    # 2026-10-25 (batch 37): plain language, never the raw evidence code
    assert "the n8n run ledger could not be read" in summary["gap_reasons"]["missed"]


def test_missed_floor_is_kept_when_some_jobs_unmeasured():
    report = build([lane("job-m"), lane("job-u")], runs=[run("job-m", NOW - timedelta(hours=1))])
    summary = report["summary"]
    assert summary["missed"] == 1 and summary["not_measured"] == 1
    assert summary["missed_measured"] is False

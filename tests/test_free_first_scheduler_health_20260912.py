"""A health predicate that cannot go unhealthy is not a health predicate.

Reproduced live on 2026-09-12T04:30Z, served SHA eb648174a:

    systemd:  tradeai-free-first-circulation.service
              failed (Result: timeout), killed 17 minutes earlier
    receipt:  finished_at 2026-09-07T14:38:14Z  (4.4 days old)
              source_sha deda1e1ae4            (not the served SHA)
    verdict:  healthy = TRUE

`last_ok = bool(rec) and paid == 0 and rec.get("overlap") is not True` asks
three questions -- does a receipt file parse, did it spend nothing, did it not
overlap -- and not one of them can ever become false again once a good receipt
has been written. The service has been SIGTERM'd at its 900s start timeout on
every run since 2026-09-08 (93 consecutive), and the predicate reported healthy
through all of it while printing the stale timestamp and the wrong SHA in its
own output.

`paid == 0` is worse than merely insufficient: it makes a completely dead
service score as maximally healthy, because a dead service spends nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.free_first_scheduler_health import timer_health

SERVED_SHA = "eb648174aebc75d0e34eb105b8ff54925efccc7b"
PRIOR_SHA = "deda1e1ae40515b6879225555b0f808b943bf98b"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_receipt(root, *, finished_at, source_sha=SERVED_SHA, paid=0, overlap=False):
    d = root / "data" / "cio"
    d.mkdir(parents=True, exist_ok=True)
    (d / "free_first_last_run.json").write_text(
        json.dumps(
            {
                "schema": "FreeFirstCirculationReport@v1",
                "mode": "FREE_FIRST_ONLY",
                "as_of": finished_at,
                "finished_at": finished_at,
                "source_sha": source_sha,
                "run_id": "test-run",
                "paid_dispatch_entered": paid,
                "overlap": overlap,
                "fresh_no_change": 120,
            }
        )
    )


def test_a_fresh_run_on_the_served_sha_is_healthy(tmp_path):
    _write_receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=20)))
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA)
    assert out["healthy"] is True
    assert out["unhealthy_reasons"] == []


def test_the_live_outage_is_reported_unhealthy(tmp_path):
    """The exact live state: 4.4-day-old receipt, prior SHA, zero spend."""
    _write_receipt(
        tmp_path,
        finished_at="2026-09-07T14:38:14+00:00",
        source_sha=PRIOR_SHA,
        paid=0,
    )
    now = datetime(2026, 9, 12, 4, 30, tzinfo=timezone.utc)
    out = timer_health(
        tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA, now=now
    )
    assert out["healthy"] is False, "a 4.4-day-old receipt on a prior SHA is not health"
    assert "receipt_stale" in out["unhealthy_reasons"]
    assert "receipt_from_prior_epoch" in out["unhealthy_reasons"]
    assert out["receipt_age_hours"] == pytest.approx(109.9, abs=0.5)


def test_zero_spend_is_not_evidence_of_health(tmp_path):
    """A dead service spends nothing. Absence of spend must never be the thing
    that makes a verdict positive."""
    _write_receipt(
        tmp_path, finished_at="2026-09-07T14:38:14+00:00", source_sha=SERVED_SHA, paid=0
    )
    now = datetime(2026, 9, 12, 4, 30, tzinfo=timezone.utc)
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA, now=now)
    assert out["paid_dispatch_count"] == 0
    assert out["healthy"] is False


def test_a_missing_receipt_is_unhealthy_not_merely_falsy(tmp_path):
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA)
    assert out["healthy"] is False
    assert "no_receipt" in out["unhealthy_reasons"]


def test_a_failing_systemd_unit_overrides_a_fresh_receipt(tmp_path):
    """The receipt is written on success, so a run that is SIGTERM'd leaves the
    previous good receipt in place. Unit state must be able to say otherwise."""
    _write_receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)))
    out = timer_health(
        tmp_path,
        expected_cadence_hours=1.0,
        served_sha=SERVED_SHA,
        timer_show={"ActiveState": "failed", "Result": "timeout"},
    )
    assert out["healthy"] is False
    assert "unit_failed" in out["unhealthy_reasons"]


def test_overlap_and_paid_dispatch_still_refuse(tmp_path):
    fresh = _iso(datetime.now(timezone.utc) - timedelta(minutes=10))
    _write_receipt(tmp_path, finished_at=fresh, overlap=True)
    assert "overlapped" in timer_health(
        tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA
    )["unhealthy_reasons"]

    _write_receipt(tmp_path, finished_at=fresh, paid=3)
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA)
    assert "paid_dispatch_in_free_only_mode" in out["unhealthy_reasons"]


def test_unknown_served_sha_does_not_manufacture_an_epoch_failure(tmp_path):
    """When the caller cannot supply the served SHA, epoch agreement is simply
    unproven -- it must not be reported as either pass or fail."""
    _write_receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)))
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=None)
    assert "receipt_from_prior_epoch" not in out["unhealthy_reasons"]
    assert out["epoch_agreement"] == "UNPROVEN"


def test_an_unparseable_timestamp_is_unhealthy_rather_than_assumed_fresh(tmp_path):
    _write_receipt(tmp_path, finished_at="not-a-timestamp")
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA)
    assert out["healthy"] is False
    assert "receipt_timestamp_unreadable" in out["unhealthy_reasons"]


def test_a_recorded_failure_supplies_the_diagnosis(tmp_path):
    """Staleness says the lane stopped; the failure receipt says why."""
    from datetime import datetime, timedelta, timezone
    import json as _json

    _write_receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(hours=6)))
    (tmp_path / "data" / "cio" / "free_first_last_failure.json").write_text(
        _json.dumps(
            {
                "schema": "FreeFirstCirculationFailure@v1",
                "finished_at": _iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
                "error_class": "SystemExit",
                "error_message": "terminated",
            }
        )
    )
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA)
    assert out["healthy"] is False
    assert "last_run_failed" in out["unhealthy_reasons"]
    assert out["last_failure"]["error_class"] == "SystemExit"


def test_a_failure_older_than_the_last_success_is_not_reported_as_current(tmp_path):
    """A lane that recovered must not be held against an old failure file."""
    from datetime import datetime, timedelta, timezone
    import json as _json

    (tmp_path / "data" / "cio").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "cio" / "free_first_last_failure.json").write_text(
        _json.dumps(
            {
                "finished_at": _iso(datetime.now(timezone.utc) - timedelta(hours=3)),
                "error_class": "SystemExit",
            }
        )
    )
    _write_receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)))
    out = timer_health(tmp_path, expected_cadence_hours=1.0, served_sha=SERVED_SHA)
    assert "last_run_failed" not in out["unhealthy_reasons"]
    assert out["healthy"] is True
    assert out["last_failure"] is None

"""Weekly disk cleanup notify — summary formatting (offline)."""
from __future__ import annotations

import scripts.weekly_disk_cleanup_notify as w


def test_build_telegram_includes_disk_and_steps():
    summary = {
        "ok": True,
        "ts": "2026-09-18T12:00:00+00:00",
        "disk_before": {"free_gb": 80.0, "used_pct": 82.0, "free_pct": 18.0, "level": "ok"},
        "disk_after": {"free_gb": 95.0, "used_pct": 79.0, "free_pct": 21.0, "level": "ok"},
        "steps": [
            {"name": "disk_hygiene", "ok": True, "detail": "releases=1 reclaim=10.0 GB"},
            {"name": "librarian_retention", "ok": True, "detail": "affected=10"},
            {"name": "db_retention", "ok": True, "detail": "rows=100"},
        ],
        "bytes_reclaimed_est": 10_000_000_000,
        "db_rows_deleted": 100,
        "librarian_affected": 10,
    }
    msg = w.build_telegram(summary)
    assert "Weekly disk cleanup" in msg
    assert "80.0G → *95.0G*" in msg
    assert "disk_hygiene: OK" in msg
    assert "librarian_retention: OK" in msg
    assert "db_retention: OK" in msg


def test_build_telegram_flags_failure():
    summary = {
        "ok": False,
        "ts": "2026-09-18T12:00:00+00:00",
        "disk_before": {"free_gb": 10.0, "used_pct": 97.0, "free_pct": 3.0, "level": "critical"},
        "disk_after": {"free_gb": 10.0, "used_pct": 97.0, "free_pct": 3.0, "level": "critical"},
        "steps": [{"name": "librarian_retention", "ok": False, "detail": "connection refused"}],
        "bytes_reclaimed_est": 0,
        "db_rows_deleted": 0,
        "librarian_affected": 0,
    }
    msg = w.build_telegram(summary)
    assert "FAIL" in msg
    assert "One or more steps failed" in msg

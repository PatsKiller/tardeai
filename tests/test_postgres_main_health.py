"""Unit tests for disk floors + postgres connect classification (2026-09-18)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.postgres_main_health import (  # noqa: E402
    classify_pg_connect_error,
    evaluate_disk_usage,
    restart_safe,
)


def test_disk_critical_inclusive_free_pct():
    # 468G disk, exactly 10% free → critical (old code used used>90 only and missed ==10%)
    total = 468 * (1024**3)
    free = int(total * 0.10)
    used = total - free
    v = evaluate_disk_usage(total_bytes=total, used_bytes=used, free_bytes=free)
    assert v.severity == "critical"
    assert v.finding_type == "disk_critical"


def test_disk_warn_by_free_gb_floor():
    # free_pct above crit/warn % floors, but free_GB under warn_gb (40) → warning only
    total = 200 * (1024**3)
    free = 35 * (1024**3)  # 17.5% free, 35GB
    used = total - free
    v = evaluate_disk_usage(total_bytes=total, used_bytes=used, free_bytes=free)
    assert v.severity == "warning"
    assert v.finding_type == "disk_low"
    assert 15 < v.free_gb < 40


def test_disk_ok_above_floors():
    total = 468 * (1024**3)
    free = 80 * (1024**3)
    used = total - free
    v = evaluate_disk_usage(total_bytes=total, used_bytes=used, free_bytes=free)
    assert v.severity is None
    assert v.finding_type is None


def test_classify_connection_refused():
    err = 'connection to server at "127.0.0.1", port 5432 failed: Connection refused'
    assert classify_pg_connect_error(err) == "postgres_main_down"


def test_classify_slots_exhausted():
    err = "FATAL: remaining connection slots are reserved"
    assert classify_pg_connect_error(err) == "slots_exhausted"


def test_classify_auth_failed():
    err = 'password authentication failed for user "trade_ai"'
    assert classify_pg_connect_error(err) == "auth_failed"


def test_restart_safe_refuses_low_disk():
    ok, reason = restart_safe(free_pct=5.0, free_gb=8.0)
    assert ok is False
    assert "restart floor" in reason


def test_restart_safe_allows_healthy_disk():
    ok, reason = restart_safe(free_pct=12.0, free_gb=20.0)
    assert ok is True

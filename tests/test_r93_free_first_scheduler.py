"""Scheduler units, lock, zero-paid contract for FREE_FIRST_ONLY circulation."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.free_first_refresh import (
    LOCK_PATH,
    OVERLAP_EXIT,
    PAID_PROVIDER_DISPATCH_ALLOWED,
    acquire_lock,
    release_lock,
)
from scripts.lib.evidence_refresh_job import dispatch_paid_provider, reset_paid_dispatch_probe
from scripts.lib.free_first_scheduler_health import timer_health

ROOT = Path(__file__).resolve().parents[1]
UNIT_DIR = ROOT / "config/systemd/user"
SERVICE = (UNIT_DIR / "tradeai-free-first-circulation.service").read_text()
TIMER = (UNIT_DIR / "tradeai-free-first-circulation.timer").read_text()
WRAPPER = (ROOT / "scripts/run_free_first_circulation.sh").read_text()


def test_paid_dispatch_unreachable_from_free_first_mode():
    assert PAID_PROVIDER_DISPATCH_ALLOWED is False
    reset_paid_dispatch_probe()
    with pytest.raises(RuntimeError, match="PAID_DISPATCH_FORBIDDEN"):
        dispatch_paid_provider(state="PLANNED", mode="FREE_FIRST_ONLY")
    with pytest.raises(RuntimeError, match="PAID_DISPATCH_FORBIDDEN"):
        dispatch_paid_provider(state="LLM_ELIGIBLE_NOT_AUTHORIZED", mode="FREE_FIRST_ONLY")


def test_service_is_oneshot_current_pinned_circulate():
    assert "Type=oneshot" in SERVICE
    assert "WorkingDirectory=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT" in SERVICE
    assert "run_free_first_circulation.sh" in SERVICE
    assert "--circulate" in WRAPPER
    assert "--json" in WRAPPER
    assert "Environment=HERMES_BACKEND=" not in SERVICE
    assert "--backend" not in SERVICE
    assert "--backend" not in WRAPPER
    assert "deepseek" not in SERVICE.lower()
    assert "MEMORY_BEHAVIOR_INFLUENCE=0" in SERVICE
    # Host-proven singleton: Python fcntl in free_first_refresh.py + Type=oneshot.
    # Outer systemd flock on the same path double-locks and exits 75 — do not reintroduce.
    assert "flock -n -E 75" not in SERVICE
    assert "Do not wrap ExecStart in flock" in SERVICE
    assert "/tmp/tradeai_free_first_circulation.lock" in (ROOT / "scripts/free_first_refresh.py").read_text()
    assert "Restart=always" not in SERVICE


def test_timer_hourly_not_price_loop():
    assert "Persistent=true" in TIMER
    assert "*:23:00 America/New_York" in TIMER
    assert "*:0/15" not in TIMER
    assert "OnUnitActiveSec=5min" not in TIMER
    assert "Unit=tradeai-free-first-circulation.service" in TIMER


def test_lock_contention_returns_overlap(tmp_path, monkeypatch):
    lock = str(tmp_path / "circ.lock")
    monkeypatch.setattr("scripts.free_first_refresh.LOCK_PATH", lock)
    fd, overlap = acquire_lock(lock)
    assert overlap is None and fd is not None
    fd2, overlap2 = acquire_lock(lock)
    assert fd2 is None
    assert overlap2["overlap"] is True
    assert overlap2["paid_dispatch_entered"] == 0
    release_lock(fd)


def _free_first_receipt(tmp_path, finished_at: str, *, source_sha: str = "abc"):
    rec = {
        "mode": "FREE_FIRST_ONLY",
        "source_sha": source_sha,
        "run_id": "r1",
        "finished_at": finished_at,
        "paid_dispatch_entered": 0,
        "fresh_no_change": 120,
    }
    path = tmp_path / "data/cio/free_first_last_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


def test_health_receipt_no_llm_required(tmp_path):
    """A FRESH_NO_CHANGE run that made no paid call is healthy.

    The timestamp is now generated relative to the run instead of being the
    fixed 2026-08-24 literal this test used to carry. That literal was the
    reason the test kept passing while the lane was dead: timer_health had no
    freshness condition, so a receipt could age indefinitely and still score
    healthy. The scenario under test -- no LLM required is not unhealthy --
    is unchanged; only its staleness is.
    """
    from datetime import datetime, timedelta, timezone

    fresh = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    _free_first_receipt(tmp_path, fresh)
    h = timer_health(tmp_path)
    assert h["healthy"] is True
    assert h["unhealthy_reasons"] == []
    assert h["paid_dispatch_count"] == 0
    assert "LLM" not in (h.get("note") or "") or "not" in h["note"].lower()


def test_health_receipt_that_stopped_being_written_is_not_healthy(tmp_path):
    """The same receipt, left to age, must flip. Without this the suite cannot
    tell a working lane from one that stopped on 2026-09-07."""
    _free_first_receipt(tmp_path, "2026-08-24T01:00:00+00:00")
    h = timer_health(tmp_path)
    assert h["healthy"] is False
    assert "receipt_stale" in h["unhealthy_reasons"]


def test_wrapper_does_not_invent_paid_flags():
    assert "--circulate" in WRAPPER
    assert "--max-searx 1" in WRAPPER
    assert "PAID_AUTHORIZED" not in WRAPPER
    assert os.getenv("MEMORY_BEHAVIOR_INFLUENCE", "0") == "0"
    assert OVERLAP_EXIT == 75
    assert LOCK_PATH.endswith("tradeai_free_first_circulation.lock")

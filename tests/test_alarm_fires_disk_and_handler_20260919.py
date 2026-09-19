"""C1 firing coverage for weekly disk cleanup + telegram command handler notify.

Main landed these send_telegram sites without COVERS. This module observes the
transport and declares the exact sites so alarm_coverage cannot grow silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = [
    "scripts/weekly_disk_cleanup_notify.py:285",
    "scripts/telegram_command_handler.py:103",
    "scripts/telegram_command_handler.py:793",
]


@pytest.fixture
def capture_transport(monkeypatch):
    captured: list[tuple] = []

    def _send(msg, *a, **k):
        captured.append((msg, dict(k)))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", _send)
    return captured


def test_weekly_disk_cleanup_notify_reaches_transport(capture_transport, monkeypatch, tmp_path):
    import weekly_disk_cleanup_notify as w

    monkeypatch.setattr(w, "ROOT", tmp_path)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    disk = {"free_gb": 80.0, "used_pct": 82.0, "free_pct": 18.0, "level": "ok"}
    monkeypatch.setattr(w, "_disk", lambda: dict(disk))
    monkeypatch.setattr(
        w,
        "_clean_preclean_dirs",
        lambda dry_run=True: {"ok": True, "deleted": [], "bytes_reclaimed_est": 0},
    )

    def _run_json(argv, timeout=60):
        joined = " ".join(str(a) for a in argv)
        if "db_retention" in joined:
            return True, "Total would delete: 0 rows"
        return True, {
            "ok": True,
            "total_affected": 0,
            "deleted": [],
            "bytes_reclaimed_est": 0,
            "releases_result": {"deleted": [], "bytes_reclaimed_est": 0},
            "backups_result": {"deleted": [], "bytes_reclaimed_est": 0},
        }

    monkeypatch.setattr(w, "_run_json", _run_json)
    summary = w.run(apply=False, notify=True)
    assert summary.get("telegram") == "accepted"
    assert capture_transport, "transport never called"
    assert any("Weekly disk cleanup" in m for m, _ in capture_transport)


def test_telegram_command_handler_send_wrapper_fires(capture_transport):
    import telegram_command_handler as tch

    assert tch._send_telegram("C1 probe: command handler wrapper") is True
    assert capture_transport and "C1 probe: command handler wrapper" in capture_transport[0][0]


def test_telegram_command_handler_notify_both_fires(capture_transport):
    import telegram_command_handler as tch

    tch._notify_both("C1 probe: notify both")
    assert capture_transport and "C1 probe: notify both" in capture_transport[0][0]

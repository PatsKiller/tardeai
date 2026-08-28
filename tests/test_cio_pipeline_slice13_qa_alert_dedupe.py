"""Slice 13: critical QA uses existing ops alert with 24h dedupe."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_level_qa as qa  # noqa: E402


def _violation():
    return {"group": "core_compounders", "actual": 86.1, "hard_cap": 60.0, "severity": "critical"}


def test_second_alert_within_24h_is_suppressed(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    dest = tmp_path / "d.json"
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    result = {"group_cap_violations": [_violation()], "qa_summary": "ok"}
    assert qa.alert_critical_violations(result, dedupe_path=dest, now=now) is True
    assert len(calls) == 1
    assert qa.alert_critical_violations(result, dedupe_path=dest, now=now + timedelta(hours=1)) is False
    assert len(calls) == 1


def test_alert_after_24h_sends_again(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    dest = tmp_path / "d.json"
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    result = {"group_cap_violations": [_violation()], "qa_summary": "ok"}
    assert qa.alert_critical_violations(result, dedupe_path=dest, now=now) is True
    assert qa.alert_critical_violations(result, dedupe_path=dest, now=now + timedelta(hours=25)) is True
    assert len(calls) == 2

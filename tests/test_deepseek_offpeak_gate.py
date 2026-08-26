"""Official vs operator bulk DeepSeek peak gates."""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.deepseek_offpeak import (
    is_deepseek_peak_utc,
    should_official_peak_skip,
    should_peak_skip,
    _cli,
)


def _utc(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 21, h, m, tzinfo=timezone.utc)


def test_official_peak_windows():
    assert is_deepseek_peak_utc(_utc(1, 0)) is True
    assert is_deepseek_peak_utc(_utc(3, 59)) is True
    assert is_deepseek_peak_utc(_utc(4, 0)) is False
    assert is_deepseek_peak_utc(_utc(6, 0)) is True
    assert is_deepseek_peak_utc(_utc(9, 59)) is True
    assert is_deepseek_peak_utc(_utc(10, 0)) is False
    assert is_deepseek_peak_utc(_utc(16, 0)) is False


def test_gate_official_skips_only_utc_peak(monkeypatch):
    monkeypatch.delenv("HERMES_ALLOW_DEEPSEEK_PEAK", raising=False)
    assert should_official_peak_skip(_utc(2)) is True
    assert should_official_peak_skip(_utc(16)) is False


def test_operator_bulk_gate_skips_outside_10_21_et(monkeypatch):
    monkeypatch.delenv("HERMES_ALLOW_DEEPSEEK_PEAK", raising=False)
    # 07:00 ET = 11:00 UTC in August (EDT) — official off-peak, outside 10-21 ET bulk
    seven_et = datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc)
    assert is_deepseek_peak_utc(seven_et) is False
    assert should_peak_skip(seven_et) is True
    assert should_official_peak_skip(seven_et) is False


def test_cli_gate_official(monkeypatch):
    monkeypatch.setenv("TRADEAI_OFFPEAK_NOW_UTC", "2026-08-21T02:00:00+00:00")
    assert _cli(["--gate-official"]) == 10
    monkeypatch.setenv("TRADEAI_OFFPEAK_NOW_UTC", "2026-08-21T16:00:00+00:00")
    assert _cli(["--gate-official"]) == 0

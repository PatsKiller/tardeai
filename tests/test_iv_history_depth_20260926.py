"""IV rank from history needs depth and span (2026-09-26).

XAR had 5 readings from one week (31.7-33.5%); today's 29.9% ranked -95 -> 0 and
the funnel refused it "IV rank proxy 0". No DB: _execute is stubbed.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import options_engine as oe  # noqa: E402


def _stub(monkeypatch, rows):
    monkeypatch.setitem(sys.modules, "db_adapter",
                        types.SimpleNamespace(USE_DB=True, _execute=lambda *a, **k: rows))
    monkeypatch.setattr(oe, "_DESK_CFG", {"iv_history_min_samples": 60, "iv_history_min_span_days": 90})


def _rows(n, days, lo=20.0, hi=40.0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"iv_pct": lo + (hi - lo) * i / max(n - 1, 1), "captured_at": t0 + timedelta(days=days * i / max(n - 1, 1))}
            for i in range(n)]


def test_one_week_of_readings_is_not_a_52_week_rank(monkeypatch):
    _stub(monkeypatch, _rows(5, 4, 31.7, 33.5))
    assert oe._iv_rank_from_history("XAR", 29.94) is None


def test_deep_long_history_is_used(monkeypatch):
    _stub(monkeypatch, _rows(120, 300))
    assert oe._iv_rank_from_history("XAR", 30.0) == 50.0


def test_many_readings_over_a_short_span_are_not_enough(monkeypatch):
    _stub(monkeypatch, _rows(200, 20))
    assert oe._iv_rank_from_history("XAR", 30.0) is None


def test_thresholds_live_in_config():
    text = (ROOT / "assets" / "portfolio_intent.yaml").read_text(encoding="utf-8")
    assert "  iv_history_min_samples:" in text and "  iv_history_min_span_days:" in text

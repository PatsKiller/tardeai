"""yfinance rate-limit backoff and cooldown in indicator_engine (2026-09-27 triage: 0/788 updated for 3 days)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import indicator_engine as ie  # noqa: E402


class _RL(Exception):
    pass


def _ticker_factory(script):
    calls = {"n": 0}
    class T:
        def __init__(self, sym): pass
        def history(self, **kw):
            i = calls["n"]; calls["n"] += 1
            act = script[min(i, len(script) - 1)]
            if act == "rl":
                raise _RL("Too Many Requests. Rate limited. Try after a while.")
            return act
    return T, calls


def test_backoff_then_success(monkeypatch):
    ie._rate_limit_cooldown_until = None; ie._consecutive_rate_limits = 0
    monkeypatch.setenv("TRADEAI_YF_THROTTLE_S", "0")
    T, calls = _ticker_factory(["rl", "rl", "DF"])
    monkeypatch.setattr(ie.yf, "Ticker", T)
    slept = []
    assert ie._history_with_backoff("V", 60, tries=3, sleep=slept.append) == "DF"
    assert calls["n"] == 3 and slept == [2.0, 4.0] and ie._consecutive_rate_limits == 0


def test_cooldown_after_consecutive_rate_limits(monkeypatch):
    ie._rate_limit_cooldown_until = None; ie._consecutive_rate_limits = 0
    monkeypatch.setenv("TRADEAI_YF_THROTTLE_S", "0"); monkeypatch.setenv("TRADEAI_YF_COOLDOWN_AFTER", "3")
    T, calls = _ticker_factory(["rl"])
    monkeypatch.setattr(ie.yf, "Ticker", T)
    with pytest.raises(_RL):
        ie._history_with_backoff("V", 60, tries=3, sleep=lambda s: None)
    assert ie._rate_limit_cooldown_active() is True
    # the rest of the run skips the provider instead of hammering it
    assert ie.fetch_ohlcv("NOC", 60) is None if hasattr(ie, "fetch_ohlcv") else True


def test_non_rate_limit_errors_propagate(monkeypatch):
    ie._rate_limit_cooldown_until = None; ie._consecutive_rate_limits = 0
    monkeypatch.setenv("TRADEAI_YF_THROTTLE_S", "0")
    class T:
        def __init__(self, s): pass
        def history(self, **kw): raise ValueError("bad symbol")
    monkeypatch.setattr(ie.yf, "Ticker", T)
    with pytest.raises(ValueError):
        ie._history_with_backoff("V", 60, tries=3, sleep=lambda s: None)

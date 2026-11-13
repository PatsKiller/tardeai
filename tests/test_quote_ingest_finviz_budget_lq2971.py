"""LQ-20261107-2971: the finviz fallback tier of the intraday quote ingest is wall-clock bounded.

On 2026-11-13 pid 2716491 (``--quotes``, started 09:45:01) was still alive at 10:04: the Alpaca batch had
committed at 09:45:03, then ~179 missed symbols went one by one through the global 2.5 s Finviz throttle
(>= 7.5 min uncontended, unbounded under contention) and held the cron flock past the 10:00 slot.
Hermetic: no network, no database, no sleeping; the clock and the throttle are fakes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as ingest  # noqa: E402


class _Conn:
    def cursor(self):
        return self

    def commit(self):
        pass

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def harness(monkeypatch):
    clock = Clock()
    asked: list[str] = []
    monkeypatch.setattr(ingest, "_monotonic", clock)
    monkeypatch.setattr(ingest, "CONNECTION_LOST_ERRORS", ())
    monkeypatch.setattr(ingest, "_get_conn", lambda role="generic": _Conn())
    monkeypatch.setattr(ingest.time, "sleep", lambda s: None)

    class Rc:
        rows_accepted = 1

    monkeypatch.setattr(ingest, "write_market_quotes", lambda cur, rows, source: Rc())

    def quote(sym, deadline=None):
        if deadline is not None and clock.t + 2.5 > deadline:  # the real throttle refuses past the deadline
            raise TimeoutError("Finviz request deferred: cooldown exceeds caller deadline")
        clock.t += 2.5
        asked.append(sym)
        return {}

    monkeypatch.setattr(ingest, "_finviz_quote", quote)
    return clock, asked


def test_a_179_symbol_walk_stops_at_the_budget_and_defers_the_tail(harness):
    clock, asked = harness
    syms = [f"S{i}" for i in range(179)]
    out = ingest.ingest_finviz_quotes(syms, budget_s=100)
    assert len(asked) == 40 and clock.t == 100  # 100 s / 2.5 s, not 179 * 2.5 = 447 s
    assert out["deferred"] == syms[40:]
    assert not set(out["missing"]) & set(out["deferred"])  # never asked is not "finviz has no quote"
    assert set(out["missing"]) == set(syms[:40])


def test_default_budget_is_under_ten_minutes_and_below_the_slot():
    assert 0 < ingest.FINVIZ_TIER_BUDGET_S <= 600 < 900


def test_an_unbounded_walk_would_overrun_the_slot(harness):
    clock, asked = harness
    ingest.ingest_finviz_quotes([f"S{i}" for i in range(179)], budget_s=10_000)
    assert clock.t > 15 * 60 * 0.45  # 447 s: the measured floor the budget cuts


def test_deferred_symbols_are_reported_as_tier_unavailable_not_no_quote(harness, monkeypatch):
    clock, asked = harness
    monkeypatch.setattr(ingest, "FINVIZ_TIER_BUDGET_S", 10)
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda symbols=None: {"fetched": 1, "missing": [f"M{i}" for i in range(10)]})
    out = ingest.ingest_quotes(["OK"] + [f"M{i}" for i in range(10)])
    assert len(out["unpriced"]["tier_unavailable"]) == 6  # 4 asked in 10 s, 6 deferred
    assert len(out["unpriced"]["no_quote"]) == 4
    assert out["alpaca"] == 1


def test_the_start_rotates_so_the_tail_is_not_starved():
    syms = list("ABCDE")
    assert ingest._rotate(syms, 0) == syms
    assert ingest._rotate(syms, 2) == list("CDEAB")
    assert ingest._rotate(syms, 7) == ingest._rotate(syms, 2)
    assert sorted(ingest._rotate(syms, 3)) == syms and ingest._rotate([], 3) == []


def test_ingest_quotes_hands_the_tier_a_rotated_list(monkeypatch):
    seen = {}
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes", lambda s=None: {"fetched": 0, "missing": ["A", "B", "C"]})
    monkeypatch.setattr(ingest, "ingest_finviz_quotes",
                        lambda s=None, budget_s=None: seen.setdefault("s", s) and {"fetched": 0, "missing": s})
    monkeypatch.setattr(ingest.time, "time", lambda: 900 * 4)  # slot 4 -> start at 4 % 3 = 1
    ingest.ingest_quotes(["A", "B", "C"])
    assert seen["s"] == ["B", "C", "A"]


def test_alpaca_commits_before_the_finviz_tier_starts(monkeypatch):
    order = []
    monkeypatch.setattr(ingest, "ingest_alpaca_quotes",
                        lambda s=None: order.append("alpaca-done") or {"fetched": 1, "missing": ["M"]})
    monkeypatch.setattr(ingest, "ingest_finviz_quotes",
                        lambda s=None, budget_s=None: order.append("finviz") or {"fetched": 0, "missing": []})
    ingest.ingest_quotes(["OK", "M"])
    assert order == ["alpaca-done", "finviz"]


def test_finviz_get_passes_the_deadline_to_the_throttle(monkeypatch):
    import types
    import finviz_http
    import finviz_throttle
    got = {}
    monkeypatch.setattr(finviz_throttle, "acquire", lambda **k: got.update(k) or 0)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: types.SimpleNamespace(status_code=200, headers={}))
    finviz_http.finviz_get("https://finviz.com/x", deadline_monotonic=123.0)
    assert got["deadline_monotonic"] == 123.0
    got.clear()
    finviz_http.finviz_get("https://finviz.com/x")
    assert "deadline_monotonic" not in got  # legacy callers unchanged


def test_an_expired_deadline_sends_no_request(monkeypatch, tmp_path):
    import finviz_http
    import finviz_throttle
    import requests
    monkeypatch.setattr(finviz_throttle, "_LOCK", tmp_path / "l")
    monkeypatch.setattr(finviz_throttle, "_STATE", tmp_path / "s.json")
    sent = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: sent.append(a))
    import time
    with pytest.raises(TimeoutError):
        finviz_http.finviz_get("https://finviz.com/x", deadline_monotonic=time.monotonic() - 1)
    assert sent == []


def test_a_throttle_refusal_defers_it_and_every_later_symbol_without_asking_again(monkeypatch):
    """The throttle refuses (cooldown past the deadline) while the clock is still inside the budget."""
    asked = []
    monkeypatch.setattr(ingest, "_monotonic", lambda: 0.0)
    monkeypatch.setattr(ingest, "CONNECTION_LOST_ERRORS", ())
    monkeypatch.setattr(ingest, "_get_conn", lambda role="generic": _Conn())
    monkeypatch.setattr(ingest.time, "sleep", lambda s: None)

    def quote(sym, deadline=None):
        asked.append(sym)
        if sym == "S2":
            raise TimeoutError("Finviz request deferred: cooldown exceeds caller deadline")
        return {}

    monkeypatch.setattr(ingest, "_finviz_quote", quote)
    out = ingest.ingest_finviz_quotes(["S0", "S1", "S2", "S3", "S4"], budget_s=100)
    assert asked == ["S0", "S1", "S2"]  # nothing is asked after the refusal
    assert out["missing"] == ["S0", "S1"] and out["deferred"] == ["S2", "S3", "S4"]


def test_a_spent_clock_stops_the_walk_even_if_the_provider_would_answer(monkeypatch):
    t = {"v": 0.0}
    asked = []
    monkeypatch.setattr(ingest, "_monotonic", lambda: t["v"])
    monkeypatch.setattr(ingest, "CONNECTION_LOST_ERRORS", ())
    monkeypatch.setattr(ingest, "_get_conn", lambda role="generic": _Conn())
    monkeypatch.setattr(ingest.time, "sleep", lambda s: None)

    def quote(sym, deadline=None):
        asked.append(sym)
        t["v"] += 60
        return {}

    monkeypatch.setattr(ingest, "_finviz_quote", quote)
    out = ingest.ingest_finviz_quotes(["A", "B", "C", "D"], budget_s=100)
    assert asked == ["A", "B"] and out["deferred"] == ["C", "D"]


def test__finviz_quote_forwards_its_deadline_to_the_throttled_get(monkeypatch):
    seen = {}

    def fake_get(url, **k):
        seen.update(k)
        raise TimeoutError("x")

    monkeypatch.setattr(ingest, "finviz_get", fake_get)
    with pytest.raises(TimeoutError):
        ingest._finviz_quote("ZQA", 42.0)
    assert seen["deadline_monotonic"] == 42.0
    seen.clear()
    with pytest.raises(TimeoutError):
        ingest._finviz_quote("ZQA")
    assert "deadline_monotonic" not in seen

#!/usr/bin/env python3
"""Server-side fire-performance reducer + live-mark resolver + active/history split."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.fire_performance import (  # noqa: E402
    compute_fire_performance, FirePerfConfig, FirePerfTracker,
    FIRED_FRESH, ACTIVE_OBSERVATION, STOP_TOUCHED, TARGET_TOUCHED, EXPIRED,
    OUTCOME_RESOLVED, DATA_STALE)
from active_trader.live_mark import LiveMarkResolver, Mark, SRC_MOOMOO, SRC_APPROVED  # noqa: E402
from active_trader.fire_performance_api import build_fire_performance  # noqa: E402

CFG = FirePerfConfig(fresh_fire_seconds=60, active_observation_minutes=30, mark_stale_after_ms=6000)
FIRE = {"fire_id": "f1", "symbol": "AAPL", "fired_at": "2026-07-28T14:00:00+00:00",
        "fire_price": 100.0, "stop_ref": 99.0, "primary_setup_id": "L2_MOMENTUM",
        "l2_state_at_fire": "T2"}


def _perf(now_iso, **kw):
    base = dict(current_bid=None, current_ask=None, current_last=None, mark_source="moomoo",
                mark_at_iso=now_iso, now_iso=now_iso, cfg=CFG)
    base.update(kw)
    return compute_fire_performance(FIRE, **base)


# ── immutable fire price ─────────────────────────────────────────────────────
def test_fire_price_and_time_are_immutable():
    p = _perf("2026-07-28T14:00:30+00:00", current_last=105.0)
    assert p["fire_price"] == 100.0 and p["fired_at"] == "2026-07-28T14:00:00+00:00"

def test_current_price_updates_independently_of_entry():
    p = _perf("2026-07-28T14:00:30+00:00", current_last=101.5)
    assert p["current_last"] == 101.5 and p["fire_price"] == 100.0


# ── change / MFE / MAE / current-R ───────────────────────────────────────────
def test_change_and_r_multiple():
    p = _perf("2026-07-28T14:00:30+00:00", current_last=101.0)
    assert p["change_from_fire"] == pytest.approx(1.0)
    assert p["change_from_fire_pct"] == pytest.approx(1.0)
    assert p["risk_per_share"] == pytest.approx(1.0)
    assert p["current_r_multiple"] == pytest.approx(1.0)   # +1.00 on 1.00 risk = 1R

def test_mfe_mae_from_running_extremes():
    p = compute_fire_performance(FIRE, current_bid=None, current_ask=None, current_last=100.5,
                                 mark_source="m", mark_at_iso="2026-07-28T14:00:30+00:00",
                                 now_iso="2026-07-28T14:00:30+00:00", cfg=CFG,
                                 prior_high=103.0, prior_low=98.5)
    assert p["high_since_fire"] == 103.0 and p["low_since_fire"] == 98.5
    assert p["mfe_since_fire"] == pytest.approx(3.0) and p["mae_since_fire"] == pytest.approx(-1.5)


# ── lifecycle states ─────────────────────────────────────────────────────────
def test_fresh_then_active_then_expired():
    assert _perf("2026-07-28T14:00:30+00:00", current_last=100.2)["lifecycle_state"] == FIRED_FRESH
    assert _perf("2026-07-28T14:10:00+00:00", current_last=100.2)["lifecycle_state"] == ACTIVE_OBSERVATION
    assert _perf("2026-07-28T15:00:00+00:00", current_last=100.2)["lifecycle_state"] == EXPIRED

def test_stop_touched_from_low():
    p = compute_fire_performance(FIRE, current_bid=None, current_ask=None, current_last=99.5,
                                 mark_source="m", mark_at_iso="2026-07-28T14:05:00+00:00",
                                 now_iso="2026-07-28T14:05:00+00:00", cfg=CFG, prior_low=98.9)
    assert p["hit_stop"] is True and p["lifecycle_state"] == STOP_TOUCHED

def test_target_touched_1r():
    p = compute_fire_performance(FIRE, current_bid=None, current_ask=None, current_last=100.5,
                                 mark_source="m", mark_at_iso="2026-07-28T14:05:00+00:00",
                                 now_iso="2026-07-28T14:05:00+00:00", cfg=CFG, prior_high=101.0)
    assert p["hit_1r"] is True and p["lifecycle_state"] == TARGET_TOUCHED

def test_stale_mark_never_appears_live():
    # mark_at 20s stale (> 6000ms) → DATA_STALE, not a live movement colour
    p = _perf("2026-07-28T14:00:30+00:00", current_last=100.2,
              mark_at_iso="2026-07-28T14:00:10+00:00")
    assert p["mark_stale"] is True and p["lifecycle_state"] == DATA_STALE

def test_no_mark_is_stale_not_fabricated():
    p = _perf("2026-07-28T14:00:30+00:00", current_last=None)
    assert p["current_last"] is None and p["mark_stale"] is True

def test_finalized_outcome_never_overwritten():
    p = compute_fire_performance(FIRE, current_bid=None, current_ask=None, current_last=200.0,
                                 mark_source="m", mark_at_iso="2026-07-28T14:00:30+00:00",
                                 now_iso="2026-07-28T14:00:30+00:00", cfg=CFG,
                                 finalized_outcome="WIN_1R")
    assert p["outcome_state"] == OUTCOME_RESOLVED and p["lifecycle_state"] == OUTCOME_RESOLVED


# ── live-mark resolver: explicit priority, no averaging ──────────────────────
class _GW:
    class _Q:
        def __init__(s, bid, ask, last): s.bid, s.ask, s.last, s.provider_at = bid, ask, last, "pq"
    def __init__(self, quote=None): self._q = quote
    def latest_quote(self, sym): return self._q
    def latest_book(self, sym): return None

def test_moomoo_marked_uses_gateway_not_approved():
    gw = _GW(_GW._Q(100.0, 100.1, 100.05))
    calls = []
    def approved(s): calls.append(s); return {"bid": 1, "ask": 2, "last": 1.5, "at": "x"}
    r = LiveMarkResolver(gateway=gw, is_moomoo_marked=lambda s: True, approved_provider=approved)
    m = r.resolve("AAPL")
    assert m.source == SRC_MOOMOO and m.last == 100.05 and calls == []   # approved NOT consulted

def test_non_moomoo_uses_approved_provider():
    gw = _GW(_GW._Q(1, 2, 1.5))
    r = LiveMarkResolver(gateway=gw, is_moomoo_marked=lambda s: False,
                         approved_provider=lambda s: {"bid": 50.0, "ask": 50.2, "last": 50.1, "at": "y"})
    m = r.resolve("TSLA")
    assert m.source == SRC_APPROVED and m.last == 50.1

def test_no_source_returns_unavailable_not_price():
    r = LiveMarkResolver(gateway=None, is_moomoo_marked=lambda s: False, approved_provider=lambda s: None)
    m = r.resolve("NVDA")
    assert m.available is False and m.last is None and m.source is None


# ── active/history split ─────────────────────────────────────────────────────
def test_build_splits_active_and_history():
    fires = [
        {"fire_id": "a", "symbol": "AAA", "fired_at": "2026-07-28T13:50:00+00:00",
         "fire_price": 10.0, "stop_ref": 9.0},   # >30min old → history
        {"fire_id": "b", "symbol": "BBB", "fired_at": "2026-07-28T14:29:30+00:00",
         "fire_price": 20.0, "stop_ref": 19.0},  # recent → active
    ]
    class R:
        def resolve(self, sym):
            return Mark(sym, None, None, 10.5 if sym == "AAA" else 20.5, "m",
                        "2026-07-28T14:29:45+00:00", True)
    tracker = FirePerfTracker(CFG)
    out = build_fire_performance(fires, resolver=R(), tracker=tracker,
                                 now_iso="2026-07-28T14:29:50+00:00")
    assert out["active_count"] == 1 and out["history_count"] == 1
    assert out["active_fires"][0]["symbol"] == "BBB"
    assert out["fire_history"][0]["symbol"] == "AAA"
    assert out["write"] is False and out["order_path"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

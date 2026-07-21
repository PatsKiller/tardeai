#!/usr/bin/env python3
"""Packet invalidation — a packet is current only when its INPUTS are unchanged.

The batch skipped on a bare "younger than 12h" rule, so a fresh catalyst, a
volume-confirmed move, an ownership change or an earnings update on a two-hour-old
packet was silently missed. A packet is now regenerated when ANY material input
changed, and the exact reason is recorded. Price is a separate governed drift
check (it always moves), never part of the discrete hash.

Pure: no network, no database.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import packet_invalidation as inv  # noqa: E402

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
GEN = (NOW - timedelta(hours=2)).isoformat()   # 2h old — within TTL


def _packet(**over):
    p = {
        "symbol": "TEST", "packet_version": inv.CURRENT_PACKET_VERSION,
        "price_used": 100.0, "source_commit_sha": "abc123",
        "fundamentals_as_of": "2026-07-20T06:00:00",
        "event_state": {"earnings": {"state": "SCHEDULED", "date": "2026-08-12"}},
        "ownership": {"held": False, "shares": 0},
        "evaluated_at": GEN,
    }
    p.update(over)
    return p


def _current(**over):
    c = {
        "symbol": "TEST", "current_price": 100.0,
        "event_state": "SCHEDULED", "event_date": "2026-08-12",
        "held": False, "shares": 0,
        "fundamentals_as_of": "2026-07-20T06:00:00",
        "latest_catalyst_at": None,
    }
    c.update(over)
    return c


# ── the fresh case: nothing changed ───────────────────────────────────────────

def test_unchanged_inputs_within_ttl_is_fresh():
    inval, reason = inv.evaluate_invalidation(_packet(), _current(), generated_at=GEN, now=NOW)
    assert inval is False and reason == "current"


def test_tiny_price_tick_alone_does_not_invalidate():
    """Price always moves — a sub-threshold tick must not force a regen."""
    inval, _ = inv.evaluate_invalidation(_packet(), _current(current_price=101.5),
                                         generated_at=GEN, price_drift_pct=3.0, now=NOW)
    assert inval is False


# ── each material change invalidates, with a named reason ─────────────────────

def test_ttl_exceeded():
    old = (NOW - timedelta(hours=30)).isoformat()
    inval, reason = inv.evaluate_invalidation(_packet(evaluated_at=old), _current(),
                                              generated_at=old, now=NOW)
    assert inval and "ttl_exceeded" in reason


def test_packet_version_bump_invalidates():
    inval, reason = inv.evaluate_invalidation(_packet(packet_version="0.9-old"), _current(),
                                              generated_at=GEN, now=NOW)
    assert inval and "packet_version" in reason


def test_event_date_change_invalidates():
    inval, reason = inv.evaluate_invalidation(_packet(), _current(event_date="2026-09-01"),
                                              generated_at=GEN, now=NOW)
    assert inval and "event_date changed" in reason


def test_event_state_change_invalidates():
    inval, reason = inv.evaluate_invalidation(_packet(), _current(event_state="NONE_CONFIRMED"),
                                              generated_at=GEN, now=NOW)
    assert inval and "event_state changed" in reason


def test_ownership_flip_invalidates():
    inval, reason = inv.evaluate_invalidation(_packet(), _current(held=True, shares=100),
                                              generated_at=GEN, now=NOW)
    assert inval and ("held changed" in reason or "shares_bucket changed" in reason)


def test_fundamentals_change_invalidates():
    inval, reason = inv.evaluate_invalidation(
        _packet(), _current(fundamentals_as_of="2026-07-21T06:00:00"), generated_at=GEN, now=NOW)
    assert inval and "fundamentals_as_of changed" in reason


def test_material_price_drift_invalidates():
    inval, reason = inv.evaluate_invalidation(_packet(), _current(current_price=110.0),
                                              generated_at=GEN, price_drift_pct=3.0, now=NOW)
    assert inval and "material_price_drift" in reason


def test_fresh_catalyst_after_packet_invalidates():
    cat = (NOW - timedelta(hours=1)).isoformat()   # after the 2h-old packet
    inval, reason = inv.evaluate_invalidation(_packet(), _current(latest_catalyst_at=cat),
                                              generated_at=GEN, now=NOW)
    assert inval and "fresh_catalyst" in reason


def test_old_catalyst_before_packet_does_not_invalidate():
    cat = (NOW - timedelta(hours=5)).isoformat()   # before the 2h-old packet
    inval, _ = inv.evaluate_invalidation(_packet(), _current(latest_catalyst_at=cat),
                                         generated_at=GEN, now=NOW)
    assert inval is False


# ── price is not in the discrete hash ─────────────────────────────────────────

def test_price_is_not_in_the_material_hash():
    a = inv.fields_from_packet(_packet(price_used=100.0))
    b = inv.fields_from_packet(_packet(price_used=250.0))
    assert inv.material_hash(a) == inv.material_hash(b), "price must not be in the discrete hash"


def test_fractional_share_drift_does_not_invalidate():
    """Reinvestment fractions must not force a regen; a whole-share change does."""
    inval, _ = inv.evaluate_invalidation(_packet(ownership={"held": True, "shares": 100.0}),
                                         _current(held=True, shares=100.3), generated_at=GEN, now=NOW)
    assert inval is False


# ── the batch consumes it ─────────────────────────────────────────────────────

def test_batch_uses_classify_freshness_not_ttl_only():
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    assert "classify_freshness" in src
    run = src[src.index("def run("):src.index("_write_status(summary)")]
    assert "classify_freshness" in run and "regenerate_reasons" in run

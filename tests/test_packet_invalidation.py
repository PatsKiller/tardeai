#!/usr/bin/env python3
"""Packet invalidation — a packet is current only when its SOURCE inputs match.

A hash from an already-persisted packet proves identity, not currency. The
canonical snapshot builder reads current source truth; compare_packet_inputs
tells whether the packet still matches it, and names the exact section that
changed. Price is a separate governed drift check (it always moves), never in the
discrete hash.

Pure: snapshots and packets are constructed in-memory; no DB, no network.
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


def _snapshot(**over):
    s = {
        "symbol": "TEST", "packet_version": inv.CURRENT_PACKET_VERSION,
        "policy_version": inv.POLICY_VERSION, "source_commit_sha": "abc123",
        "market": {"price": 100.0, "price_as_of": "x",
                   "technical_content_hash": "TECH0"},
        "fundamentals": {"provider": "finviz_enrichment", "fetched_at": "2026-07-20T06:00:00",
                         "content_hash": "FUND0", "coverage_count": 18},
        "events": {"earnings_state": "SCHEDULED", "earnings_date": "2026-08-12",
                   "event_content_hash": "EV0", "latest_catalyst_at": None, "catalyst_ids": []},
        "ownership": {"held": False, "shares": 0, "ownership_content_hash": "OWN0"},
        "proposal_state": {"open_proposal_ids": [], "content_hash": "PROP0"},
        "options": {"chain_as_of": None, "chain_content_hash": None},
    }
    for k, v in over.items():
        if isinstance(v, dict) and k in s:
            s[k] = {**s[k], **v}
        else:
            s[k] = v
    s["input_hash"] = inv.compute_input_hash(s)
    return s


def _packet(snapshot=None, **over):
    snap = snapshot or _snapshot()
    p = {
        "symbol": "TEST", "packet_version": inv.CURRENT_PACKET_VERSION,
        "price_used": snap["market"]["price"], "evaluated_at": GEN,
        "input_snapshot": snap, "input_hash": snap["input_hash"],
        "event_state": {"earnings": {"state": snap["events"]["earnings_state"],
                                     "date": snap["events"]["earnings_date"]}},
        "ownership": {"held": snap["ownership"]["held"], "shares": snap["ownership"]["shares"]},
        "fundamentals_as_of": snap["fundamentals"]["fetched_at"],
    }
    p.update(over)
    return p


# ── fresh: nothing changed ────────────────────────────────────────────────────

def test_unchanged_inputs_within_ttl_matches():
    r = inv.compare_packet_inputs(_packet(), _snapshot(), generated_at=GEN, now=NOW)
    assert r["inputs_match"] is True and r["invalidation_reasons"] == []


def test_tiny_price_tick_alone_does_not_invalidate():
    r = inv.compare_packet_inputs(_packet(), _snapshot(market={"price": 101.5}),
                                  generated_at=GEN, price_drift_pct=5.0, now=NOW)
    assert r["inputs_match"] is True


def test_enrichment_timestamp_churn_is_not_technicals_changed():
    """last_enriched_at moving without RSI/chg/rvol band shift must not REFRESH."""
    # Old-style hash that baked in as_of (simulates pre-fix packets)
    old_h = inv._h({"rsi": None, "as_of": "2026-07-21T10:00:00+00:00"})
    new_h = inv.technical_content_hash(rsi=None, change_pct=None, rvol=None)
    pkt = _packet(snapshot=_snapshot(market={
        "price": 100.0, "technical_content_hash": old_h, "technical_as_of": "2026-07-21T10:00:00+00:00",
    }))
    cur = _snapshot(market={
        "price": 100.0, "technical_content_hash": new_h,
        "technical_as_of": "2026-07-21T11:30:00+00:00",  # enrich tick
        "rsi": None, "change_pct": None, "rvol": None,
    })
    r = inv.compare_packet_inputs(pkt, cur, generated_at=GEN, now=NOW)
    assert "TECHNICALS_CHANGED" not in r["invalidation_reasons"]
    assert r["inputs_match"] is True


def test_material_rsi_band_shift_is_technicals_changed():
    old_h = inv.technical_content_hash(rsi=40, change_pct=0, rvol=1.0)
    new_h = inv.technical_content_hash(rsi=55, change_pct=0, rvol=1.0)
    assert old_h != new_h
    pkt = _packet(snapshot=_snapshot(market={
        "price": 100.0, "technical_content_hash": old_h, "rsi": 40, "change_pct": 0, "rvol": 1.0,
        "technical_as_of": GEN,
    }))
    cur = _snapshot(market={
        "price": 100.0, "technical_content_hash": new_h, "rsi": 55, "change_pct": 0, "rvol": 1.0,
        "technical_as_of": GEN,
    })
    r = inv.compare_packet_inputs(pkt, cur, generated_at=GEN, now=NOW)
    assert "TECHNICALS_CHANGED" in r["invalidation_reasons"]


def test_rth_ttl_is_shorter_than_overnight():
    # Noon ET on a weekday in July ≈ RTH
    rth = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)  # 12:00 ET
    off = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)   # 22:00 ET prior
    assert inv.effective_ttl_hours(rth) <= inv.effective_ttl_hours(off)
    assert inv.is_us_cash_rth(rth) is True
    assert inv.is_us_cash_rth(off) is False
    assert inv.effective_ttl_hours(rth) == 4.0
    assert inv.effective_ttl_hours(off) == 12.0


def test_rth_ttl_expired_at_five_hours():
    """5h-old packet during cash session → TTL_EXPIRED (few-hour rating refresh)."""
    rth = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)
    gen = (rth - timedelta(hours=5)).isoformat()
    r = inv.compare_packet_inputs(
        _packet(evaluated_at=gen), _snapshot(), generated_at=gen, now=rth)
    assert "TTL_EXPIRED" in r["invalidation_reasons"]
    assert r["ttl_hours_applied"] == 4.0
    assert r.get("packet_age_hours", 0) >= 5.0
    assert r.get("rth") is True


def test_batch_fresh_hours_defaults_to_rth_aware():
    import shadow_batch_generator as bg
    rth = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)
    off = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    assert bg._effective_fresh_hours(None, now=rth) == 4.0
    assert bg._effective_fresh_hours(None, now=off) == 12.0
    assert bg._effective_fresh_hours(8.0, now=rth) == 8.0


# ── each material change invalidates with a NAMED reason ──────────────────────

def test_ttl_expired():
    old = (NOW - timedelta(hours=30)).isoformat()
    r = inv.compare_packet_inputs(_packet(evaluated_at=old), _snapshot(), generated_at=old, now=NOW)
    assert "TTL_EXPIRED" in r["invalidation_reasons"]


def test_packet_version_change():
    p = _packet(packet_version="0.9-old")
    r = inv.compare_packet_inputs(p, _snapshot(), generated_at=GEN, now=NOW)
    assert "PACKET_VERSION_CHANGED" in r["invalidation_reasons"]


def test_earnings_change():
    r = inv.compare_packet_inputs(_packet(), _snapshot(events={"earnings_date": "2026-09-01",
                                                               "event_content_hash": "EV_NEW"}),
                                  generated_at=GEN, now=NOW)
    assert "EARNINGS_CHANGED" in r["invalidation_reasons"]


def test_ownership_change():
    r = inv.compare_packet_inputs(_packet(), _snapshot(ownership={"held": True, "shares": 100,
                                                                  "ownership_content_hash": "OWN_NEW"}),
                                  generated_at=GEN, now=NOW)
    assert "OWNERSHIP_CHANGED" in r["invalidation_reasons"]


def test_fundamentals_change():
    r = inv.compare_packet_inputs(_packet(), _snapshot(fundamentals={"content_hash": "FUND_NEW"}),
                                  generated_at=GEN, now=NOW)
    assert "FUNDAMENTALS_CHANGED" in r["invalidation_reasons"]


def test_technicals_change():
    r = inv.compare_packet_inputs(_packet(), _snapshot(market={"technical_content_hash": "TECH_NEW"}),
                                  generated_at=GEN, now=NOW)
    assert "TECHNICALS_CHANGED" in r["invalidation_reasons"]


def test_proposal_state_change():
    r = inv.compare_packet_inputs(_packet(), _snapshot(proposal_state={"open_proposal_ids": ["p1"],
                                                                       "content_hash": "PROP_NEW"}),
                                  generated_at=GEN, now=NOW)
    assert "PROPOSAL_STATE_CHANGED" in r["invalidation_reasons"]


def test_material_price_drift():
    r = inv.compare_packet_inputs(_packet(), _snapshot(market={"price": 110.0}),
                                  generated_at=GEN, price_drift_pct=3.0, now=NOW)
    assert "PRICE_DRIFT" in r["invalidation_reasons"]


def test_fresh_catalyst_after_packet():
    cat = (NOW - timedelta(hours=1)).isoformat()
    r = inv.compare_packet_inputs(_packet(), _snapshot(events={"latest_catalyst_at": cat}),
                                  generated_at=GEN, now=NOW)
    assert "NEW_CATALYST" in r["invalidation_reasons"]


def test_old_catalyst_before_packet_does_not_invalidate():
    cat = (NOW - timedelta(hours=5)).isoformat()
    r = inv.compare_packet_inputs(_packet(), _snapshot(events={"latest_catalyst_at": cat}),
                                  generated_at=GEN, now=NOW)
    assert r["inputs_match"] is True


# ── price and fractional shares excluded from the discrete hash ───────────────

def test_price_is_not_in_the_input_hash():
    assert inv.compute_input_hash(_snapshot(market={"price": 100.0})) == \
           inv.compute_input_hash(_snapshot(market={"price": 250.0}))


def test_model_conclusions_never_enter_the_hash():
    """Sanity: the hash is over section content hashes, never a thesis/verdict."""
    a = inv.compute_input_hash(_snapshot())
    # adding a model field to the snapshot must not change the hash
    b = inv.compute_input_hash({**_snapshot(), "thesis_state": "STRONG_CONVICTION",
                                "action": "PROPOSE_ENTRY"})
    assert a == b


def test_legacy_packet_without_snapshot_uses_fallback():
    """Older packets carry no input_snapshot — comparison falls back to their
    coarse fields, never crashes."""
    legacy = {"symbol": "TEST", "packet_version": inv.CURRENT_PACKET_VERSION,
              "price_used": 100.0, "evaluated_at": GEN,
              "event_state": {"earnings": {"state": "SCHEDULED", "date": "2026-08-12"}},
              "ownership": {"held": False, "shares": 0},
              "fundamentals_as_of": "2026-07-20T06:00:00"}
    r = inv.compare_packet_inputs(legacy, _snapshot(events={"earnings_date": "2026-09-01"}),
                                  generated_at=GEN, now=NOW)
    assert "EARNINGS_CHANGED" in r["invalidation_reasons"]


# ── the batch consumes it ─────────────────────────────────────────────────────

def test_batch_uses_classify_freshness_with_full_contract():
    import shadow_batch_generator as bg
    src = Path(bg.__file__).read_text()
    assert "classify_freshness" in src
    cf = src[src.index("def classify_freshness"):src.index("def _generate_one")]
    assert "build_current_input_snapshot" in cf and "compare_packet_inputs" in cf


def test_reason_codes_are_the_canonical_enum():
    for code in ("TTL_EXPIRED", "PRICE_DRIFT", "NEW_CATALYST", "EARNINGS_CHANGED",
                 "OWNERSHIP_CHANGED", "FUNDAMENTALS_CHANGED", "TECHNICALS_CHANGED",
                 "PROPOSAL_STATE_CHANGED", "OPTIONS_CHAIN_STALE", "PACKET_VERSION_CHANGED",
                 "INPUT_HASH_MISMATCH"):
        assert code in inv.REASONS

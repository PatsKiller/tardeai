#!/usr/bin/env python3
"""M3-S5.5 — observation fabric tests (deterministic; no network, no secrets).

Covers: bounded concurrency cap, timeout isolation, no-retry-on-auth, deterministic ordering,
circuit breaker; arbitration (fresh>stale, delayed downgrade, IEX≠consolidated, SOURCE_CONFLICT,
feed-match, broker facts excluded from market signal); provider capabilities (Moomoo scaffold→no T2,
Yahoo degraded, Alpaca T1=IEX_ONLY); fabric flag-off reproduces current path; contract has no secrets.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "market_observations"))

import observation as obs                      # noqa: E402
from observation import (make_observation, ObservationType as OT, EntitlementState as ES,        # noqa: E402
                         FreshnessState as FS, QualityState as QS, DataTier as DT)
import concurrency as cc                        # noqa: E402
from concurrency import Task, ConcurrencyLimits, BoundedRunner, AuthError, EntitlementError, TransientError  # noqa: E402
import arbitration as arb                       # noqa: E402
from arbitration import select_market_source, select_broker_fact, require_feed_match, AuthorityPolicy  # noqa: E402
import providers as prov                        # noqa: E402
from fabric import MultiSourceFabric, is_enabled  # noqa: E402

TS = "2026-07-27T20:00:00Z"


def _bar(source, symbol="AAPL", close=100.0, feed="iex", delayed=False,
         fresh=FS.FRESH, ent=ES.IEX_ONLY, tier=DT.T0):
    return make_observation(source_system=source, symbol=symbol, observation_type=OT.BAR,
                            payload={"close": close, "c": close}, provider_at=TS, received_at=TS,
                            normalized_at=TS, entitlement_state=ent, freshness_state=fresh,
                            feed=feed, delayed=delayed, data_tier=tier, quality_state=QS.OK)


# ── observation contract ────────────────────────────────────────────
def test_house_envelope_field_names():
    o = _bar("alpaca")
    env = o.to_house_envelope()
    for k in ("source_system", "source_record_id", "symbol_or_entity", "observed_at", "provider_at",
              "received_at", "normalized_at", "source_version", "source_hash", "quality_state",
              "freshness_state", "entitlement_state", "sequence_id", "payload_ref"):
        assert k in env

def test_market_signal_vs_broker_state_partition():
    assert _bar("alpaca").is_market_signal()
    acct = make_observation(source_system="schwab", symbol="AAPL", observation_type=OT.ACCOUNT_FACT,
                            payload={"cash": 1}, provider_at=TS, received_at=TS, normalized_at=TS,
                            entitlement_state=ES.AVAILABLE_REALTIME)
    assert acct.is_broker_state() and not acct.is_market_signal()

def test_no_secret_fields_in_contract():
    env = _bar("alpaca").to_house_envelope()
    blob = str(env).lower()
    for bad in ("secret", "apca-api", "token", "password", "authorization", "api_key"):
        assert bad not in blob


# ── concurrency ─────────────────────────────────────────────────────
def _limits(**kw):
    base = dict(global_max=3, per_provider_max={"p": 3}, task_timeout_s=0.5, max_retries=2,
                retry_base_s=0.001, retry_jitter_s=0.0, breaker_threshold=2, breaker_cooldown_s=5)
    base.update(kw)
    return ConcurrencyLimits(**base)

def test_concurrency_never_exceeds_cap():
    active = {"n": 0, "max": 0}
    async def fn():
        active["n"] += 1; active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0.02); active["n"] -= 1
        return _bar("alpaca")
    tasks = [Task("p", f"k{i}", fn) for i in range(12)]
    runner = BoundedRunner(_limits(global_max=3, per_provider_max={"p": 3}))
    res = asyncio.run(runner.run(tasks))
    assert runner.max_concurrency <= 3 and active["max"] <= 3
    assert all(r is not None for r in res)

def test_timeout_does_not_block_healthy_providers():
    async def slow(): await asyncio.sleep(5); return _bar("slow")
    async def fast(): return _bar("alpaca")
    tasks = [Task("slowp", "s", slow), Task("p", "f", fast)]
    lim = _limits(per_provider_max={"slowp": 1, "p": 1}, task_timeout_s=0.1)
    res, runner = cc.run_bounded(tasks, lim)
    assert res[1] is not None            # healthy provider returned
    assert res[0] is None                # slow one timed out (independent)
    assert runner.counters["slowp"].timeout >= 1

def test_auth_rejection_not_retried():
    async def auth_fail(): raise AuthError("nope")
    res, runner = cc.run_bounded([Task("p", "a", auth_fail)], _limits())
    assert res[0] is None
    assert runner.counters["p"].throttled == 1 and runner.counters["p"].retry == 0

def test_transient_is_retried_then_fails():
    state = {"n": 0}
    async def flaky(): state["n"] += 1; raise TransientError("x")
    res, runner = cc.run_bounded([Task("p", "t", flaky)], _limits(max_retries=2))
    assert res[0] is None and runner.counters["p"].retry == 2 and state["n"] == 3

def test_deterministic_result_ordering():
    async def make(i):
        await asyncio.sleep((5 - i) * 0.005)   # later tasks finish first
        return _bar("alpaca", close=float(i))
    tasks = [Task("p", f"k{i}", (lambda i=i: make(i))) for i in range(5)]
    res, _ = cc.run_bounded(tasks, _limits(global_max=5, per_provider_max={"p": 5}))
    assert [r.payload_ref["close"] for r in res] == [0.0, 1.0, 2.0, 3.0, 4.0]

def test_circuit_breaker_opens_and_skips():
    async def fail(): raise TransientError("boom")
    # per-provider cap 1 → sequential → breaker (threshold 2) opens before the 3rd
    tasks = [Task("p", f"k{i}", fail) for i in range(3)]
    res, runner = cc.run_bounded(tasks, _limits(per_provider_max={"p": 1}, max_retries=0, breaker_threshold=2))
    assert runner.counters["p"].breaker_skipped >= 1


# ── arbitration ─────────────────────────────────────────────────────
def test_fresh_beats_stale():
    fresh = _bar("alpaca", close=100, fresh=FS.FRESH)
    stale = _bar("yahoo", close=101, fresh=FS.STALE, ent=ES.AVAILABLE_HISTORICAL, delayed=True)
    r = select_market_source(OT.BAR, [stale, fresh])
    assert r.selected_source == "alpaca"

def test_delayed_data_visibly_downgraded():
    delayed = _bar("yahoo", fresh=FS.FRESH, ent=ES.AVAILABLE_DELAYED, delayed=True)
    r = select_market_source(OT.BAR, [delayed])
    assert r.tier_downgraded and "delayed" in r.tier_downgraded

def test_iex_quote_not_labeled_consolidated_sip():
    iexq = make_observation(source_system="alpaca", symbol="AAPL", observation_type=OT.QUOTE,
                            payload={"bid": 99.9, "ask": 100.1}, provider_at=TS, received_at=TS,
                            normalized_at=TS, entitlement_state=ES.IEX_ONLY, freshness_state=FS.FRESH,
                            feed="iex", data_tier=DT.T1_VENUE)
    r = select_market_source(OT.QUOTE, [iexq])
    assert r.tier == DT.T1_VENUE.value and r.tier != DT.T1.value
    assert r.tier_downgraded and "venue_partial" in r.tier_downgraded

def test_source_conflict_on_fresh_price_disagreement():
    a = _bar("alpaca", close=100.0, fresh=FS.FRESH)
    # a fresh peer on the SAME type disagreeing by >50bps; give it an eligible source (yahoo in BAR policy)
    b = _bar("yahoo", close=101.0, fresh=FS.FRESH, ent=ES.AVAILABLE_DELAYED, delayed=False)
    r = select_market_source(OT.BAR, [a, b])
    assert r.conflict == "SOURCE_CONFLICT" and r.directive and "lower_dcf" in r.directive["action"]

def test_no_conflict_when_prices_agree():
    a = _bar("alpaca", close=100.0); b = _bar("yahoo", close=100.02, ent=ES.AVAILABLE_DELAYED)
    assert select_market_source(OT.BAR, [a, b]).conflict is None

def test_feed_match_required_for_rvol():
    require_feed_match("iex", "iex")                 # ok
    with pytest.raises(ValueError):
        require_feed_match("iex", "sip")

def test_broker_facts_excluded_from_market_source():
    acct = make_observation(source_system="schwab", symbol="AAPL", observation_type=OT.ACCOUNT_FACT,
                            payload={"cash": 1}, provider_at=TS, received_at=TS, normalized_at=TS,
                            entitlement_state=ES.AVAILABLE_REALTIME)
    # account facts are not a BAR/market-signal source → not selectable as market source
    r = select_market_source(OT.BAR, [acct])
    assert r.selected is None

def test_broker_owns_only_its_resource():
    schwab = make_observation(source_system="schwab", symbol="AAPL", observation_type=OT.POSITION_FACT,
                              payload={"qty": 10}, provider_at=TS, received_at=TS, normalized_at=TS,
                              entitlement_state=ES.AVAILABLE_REALTIME)
    r = select_broker_fact(OT.POSITION_FACT, "schwab", [schwab])
    assert r.selected_source == "schwab"
    r2 = select_broker_fact(OT.POSITION_FACT, "alpaca", [schwab])   # schwab not owner of alpaca resource
    assert r2.selected is None


# ── providers / capabilities ────────────────────────────────────────
def test_moomoo_scaffold_only_no_t2():
    cap = prov.capability("moomoo", OT.ORDER_BOOK)
    assert cap.entitlement == ES.SCAFFOLD_ONLY
    # scaffold-only never selected as an order-book (T2) source
    scaffold = make_observation(source_system="moomoo", symbol="AAPL", observation_type=OT.ORDER_BOOK,
                                payload={}, provider_at=TS, received_at=TS, normalized_at=TS,
                                entitlement_state=ES.SCAFFOLD_ONLY)
    assert select_market_source(OT.ORDER_BOOK, [scaffold]).selected is None

def test_moomoo_sequence_gap_rejects_t2_snapshot():
    # a scaffold/gap T2 observation must not be accepted; entitlement gate already blocks scaffold,
    # and a sequence gap is represented as UNRESOLVED entitlement → rejected
    gap = make_observation(source_system="moomoo", symbol="AAPL", observation_type=OT.ORDER_BOOK,
                           payload={}, provider_at=TS, received_at=TS, normalized_at=TS,
                           entitlement_state=ES.UNRESOLVED, sequence_id=None)
    assert select_market_source(OT.ORDER_BOOK, [gap]).selected is None

def test_yahoo_bar_is_degraded_historical():
    cap = prov.capability("yahoo", OT.BAR)
    assert cap.entitlement == ES.AVAILABLE_HISTORICAL and "UNSUITABLE" in cap.note

def test_alpaca_t1_classification_is_iex_only():
    assert prov.ALPACA_T1_CLASSIFICATION == "T1_IEX_ONLY"
    assert prov.capability("alpaca", OT.TRADE).entitlement == ES.IEX_ONLY
    assert prov.capability("alpaca", OT.QUOTE).entitlement == ES.IEX_ONLY


# ── fabric flag gating ──────────────────────────────────────────────
def test_flag_off_reproduces_current_path():
    fab = MultiSourceFabric({"multi_source": {"enabled": False}})
    assert fab.acquire_bar_snapshot(["AAPL"]) == {}     # off → no fabric output, caller keeps T0 path
    assert is_enabled({"multi_source": {"enabled": False}}) is False

def test_flag_on_with_synthetic_provider_arbitrates():
    class FakeAlpaca(prov.ProviderAdapter):
        name = "alpaca"
        async def fetch_bar(self, symbol, now_iso):
            return _bar("alpaca", symbol=symbol, close=123.0)
    fab = MultiSourceFabric({"multi_source": {"enabled": True}}, providers=[FakeAlpaca()])
    snap = fab.acquire_bar_snapshot(["AAPL"])
    assert snap["AAPL"]["selected"]["payload_ref"]["close"] == 123.0
    assert snap["AAPL"]["provenance"]["selected_source"] == "alpaca"

def test_capability_matrix_shape():
    m = MultiSourceFabric({}).capability_matrix()
    assert set(m) == {"alpaca", "yahoo", "schwab", "moomoo"}
    assert m["moomoo"]["order_book"]["entitlement"] == "SCAFFOLD_ONLY"


# ── S5 trigger-R diagnostics (pure r_quality) ───────────────────────
sys.path.insert(0, str(ROOT / "scripts"))
from scalp_trigger_r_diagnostics import r_quality  # noqa: E402

def test_r_quality_normal():
    q = r_quality(entry=100.0, r_dollars=0.5, spread_bps=20, tick=0.01, assumed_slippage_bps=40)
    assert q["valid"] and q["r_bps"] == pytest.approx(50.0)
    assert q["tick_to_r"] == pytest.approx(0.02)
    assert q["spread_to_r"] == pytest.approx(0.4) and q["slippage_to_r"] == pytest.approx(0.8)
    assert not q["r_below_1_tick"]

def test_r_quality_tiny_R_flags_below_tick():
    # CRNX-style: R ≈ $0.004, smaller than a $0.01 tick → operationally meaningless
    q = r_quality(entry=100.0, r_dollars=0.004, spread_bps=None, tick=0.01, assumed_slippage_bps=40)
    assert q["r_below_1_tick"] and q["tick_to_r"] > 1.0
    assert q["slippage_to_r"] > 1.0            # assumed slippage exceeds the whole R

def test_r_quality_invalid_nonpositive():
    assert r_quality(100.0, 0.0, 10, 0.01, 40) == {"valid": False}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

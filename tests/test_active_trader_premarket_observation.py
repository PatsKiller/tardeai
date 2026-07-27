"""Stage 5 harness — observation core tests: windows, metrics, cross-checks, verdicts,
state machine, extended-hours request, AST prohibition, storage/replay. Deterministic."""
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader import premarket_observation as po  # noqa: E402

TZ = ZoneInfo("America/New_York")
BASE = dt.date(2026, 7, 24)


def at(hh, mm, ss=0):
    return dt.datetime.combine(BASE, dt.time(hh, mm, ss), TZ)


def ev(stream, symbol, hh, mm, ss=0, *, role="BASELINE", fresh=True, cached=False,
       stale=False, gap=po.GapKind.NONE.value, server=True, levels=None, bid=None, ask=None,
       bsize=None, asize=None, last=None, market_state=None, queue="HEALTHY"):
    bids = asks = None
    if levels:
        bids = [((bid or 10.0) - 0.01 * i, 100.0) for i in range(levels)]
        asks = [((ask or 10.02) + 0.01 * i, 100.0) for i in range(levels)]
    fs = po.Freshness.CACHED_FIRST_PUSH.value if cached else (po.Freshness.STALE.value if stale else po.Freshness.FRESH.value)
    return po.ObservationEvent(
        observation_session_id="t", symbol=symbol, symbol_role=role, stream=stream,
        receive_ts=at(hh, mm, ss),
        provider_timestamp=("2026-07-24T%02d:%02d:%02dZ" % (hh, mm, ss)) if server else None,
        server_bid_timestamp=("x" if server else None),
        cached_first_push=cached, freshness_state=fs, gap_state=gap, queue_state=queue,
        market_state=market_state, bid=bid, ask=ask, bid_size=bsize, ask_size=asize,
        bids=bids, asks=asks, last=last)


def book_stream(symbol, start, end, *, step=30, role="BASELINE", levels=2, server=True):
    """Fresh 2-level ORDER_BOOK events from start..end (HH,MM tuples) at `step`s spacing, inclusive."""
    out = []
    s0 = start[0] * 3600 + start[1] * 60
    s1 = end[0] * 3600 + end[1] * 60 + (end[2] if len(end) > 2 else 0)
    t = s0
    i = 0
    while t <= s1:
        hh, rem = divmod(int(t), 3600)
        mm, ss = divmod(rem, 60)
        # jitter price so successive books differ (not identical/stale)
        out.append(ev("ORDER_BOOK", symbol, hh, mm, ss, role=role, levels=levels,
                      bid=10.00 + (i % 3) * 0.01, ask=10.02 + (i % 3) * 0.01,
                      bsize=100.0, asize=100.0, server=server))
        t += step
        i += 1
    return out


# ---- windows ---------------------------------------------------------------

def test_window_boundaries():
    assert po.window_for(at(7, 0)) == po.Window.P1
    assert po.window_for(at(7, 59, 59)) == po.Window.P1
    assert po.window_for(at(8, 0)) == po.Window.P2
    assert po.window_for(at(9, 20)) == po.Window.P3
    assert po.window_for(at(9, 30)) == po.Window.R1
    assert po.window_for(at(9, 45)) == po.Window.R2
    assert po.window_for(at(10, 5)) == po.Window.R2       # capture endpoint inclusive
    assert po.window_for(at(6, 59, 59)) == po.Window.OUTSIDE
    assert po.window_for(at(10, 6)) == po.Window.OUTSIDE


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        po.et_seconds(dt.datetime(2026, 7, 24, 9, 0))     # naive


def test_freshness_flags():
    assert ev("QUOTE", "US.AAPL", 8, 0).fresh
    assert not ev("QUOTE", "US.AAPL", 8, 0, cached=True).fresh
    assert not ev("QUOTE", "US.AAPL", 8, 0, stale=True).fresh


# ---- duration accounting ---------------------------------------------------

def test_rth_35_minutes_passes_3459_fails():
    sym = "US.AAPL"
    full = book_stream(sym, (9, 30), (10, 5, 0))          # 09:30:00..10:05:00 -> 35:00
    assert po.longest_continuous_minutes(full, *po.RTH_REGION, symbol=sym) == pytest.approx(35.0, abs=0.02)
    short = book_stream(sym, (9, 30), (10, 4, 30))         # 34:30
    assert po.longest_continuous_minutes(short, *po.RTH_REGION, symbol=sym) < 35.0


def test_gap_and_startup_exclusion():
    sym = "US.AAPL"
    evs = [ev("ORDER_BOOK", sym, 9, 30, 0, levels=2, bid=10, ask=10.02, bsize=100, asize=100),
           ev("ORDER_BOOK", sym, 9, 33, 0, levels=2, bid=10, ask=10.02, bsize=100, asize=100)]  # 180s gap>60
    assert po.accepted_minutes(evs, *po.RTH_REGION, symbol=sym) == 0.0     # >60s gap not counted


# ---- metrics ---------------------------------------------------------------

def test_two_sided_book_metrics():
    sym = "US.MOVR"
    evs = [ev("ORDER_BOOK", sym, 8, 30, s, levels=2, bid=10.00, ask=10.02, bsize=100, asize=80)
           for s in (0, 30)] + [ev("ORDER_BOOK", sym, 8, 31, 0, levels=2, bid=10.00, ask=10.02, bsize=100, asize=80)]
    m = po.level2_metrics(evs, sym, po.Window.P2)
    assert m.bid_level_count == 2 and m.ask_level_count == 2
    assert m.top_bid == 10.00 and m.top_ask == 10.02 and m.spread == pytest.approx(2.0)
    assert m.displayed_bid_depth == 200.0 and m.data_quality == "OK"
    assert m.top_imbalance is not None and m.inference_label == po.INFERENCE_LABEL


def test_one_sided_and_locked_and_unchanged():
    sym = "US.X"
    one = [ev("ORDER_BOOK", sym, 8, 30, 0, bid=10.0, bsize=100)]        # ask side empty
    assert po.level2_metrics(one, sym, po.Window.P2).data_quality in ("ONE_SIDED_OR_EMPTY", "OK")
    locked = [ev("ORDER_BOOK", sym, 8, 30, 0, bid=10.05, ask=10.00, bsize=1, asize=1),
              ev("ORDER_BOOK", sym, 8, 30, 30, bid=10.05, ask=10.00, bsize=1, asize=1)]
    lm = po.level2_metrics(locked, sym, po.Window.P2)
    assert lm.locked_crossed_count == 2
    assert lm.identical_book_duration_s and lm.identical_book_duration_s >= 30  # unchanged snapshots


def test_replenishment_cancellation_inferred_and_labeled():
    sym = "US.Y"
    evs = [ev("ORDER_BOOK", sym, 8, 30, 0, levels=2, bid=10, ask=10.02, bsize=100, asize=100),
           ev("ORDER_BOOK", sym, 8, 30, 30, levels=2, bid=10, ask=10.02, bsize=100, asize=100)]
    m = po.level2_metrics(evs, sym, po.Window.P2)
    assert m.replenishment_estimate is not None and m.cancellation_pressure_estimate is not None
    assert m.inference_label == "INFERRED_FROM_AGGREGATED_BOOK_SNAPSHOTS"


def test_window_partitioning():
    sym = "US.AAPL"
    evs = [ev("ORDER_BOOK", sym, 7, 30, bid=10, ask=10.02, bsize=1, asize=1),
           ev("ORDER_BOOK", sym, 8, 30, bid=10, ask=10.02, bsize=1, asize=1)]
    assert po.level2_metrics(evs, sym, po.Window.P1).callbacks == 1
    assert po.level2_metrics(evs, sym, po.Window.P2).callbacks == 1


# ---- cross-checks ----------------------------------------------------------

def test_cross_checks_extended_hours_present_and_absent():
    sym = "US.AAPL"
    with_eh = [ev("K_1M", sym, 8, 0), ev("TICKER", sym, 8, 0, last=10.0),
               ev("ORDER_BOOK", sym, 8, 0, bid=10, ask=10.02, bsize=1, asize=1),
               ev("QUOTE", sym, 8, 0, bid=10, ask=10.02)]
    xc = po.cross_checks(with_eh, sym)
    assert xc["k1m_premarket_timestamps"] == po.CrossOutcome.MATCH.value
    assert xc["ticker_premarket_timestamps"] == po.CrossOutcome.MATCH.value
    no_eh = [ev("ORDER_BOOK", sym, 9, 35, bid=10, ask=10.02, bsize=1, asize=1)]
    xc2 = po.cross_checks(no_eh, sym)
    assert xc2["k1m_premarket_timestamps"] == po.CrossOutcome.MISSING_EXTENDED_HOURS.value


def test_open_transition_detected():
    sym = "US.AAPL"
    evs = [ev("ORDER_BOOK", sym, 9, 20, bid=10, ask=10.02, bsize=1, asize=1, market_state="PRE_MARKET_END"),
           ev("ORDER_BOOK", sym, 9, 35, bid=10, ask=10.02, bsize=1, asize=1, market_state="MARKET")]
    assert po.cross_checks(evs, sym)["market_state_transition_at_0930"] is True


# ---- verdicts --------------------------------------------------------------

def _full_counted_events(sym, role="REPRESENTATIVE"):
    return (book_stream(sym, (7, 0), (9, 29, 30), role=role)
            + book_stream(sym, (9, 30), (10, 5, 0), role=role))


def test_representative_active_book_provisional_pass():
    sym = "US.MOVR"
    v = po.evaluate(_full_counted_events(sym), symbols=[sym, "US.AAPL"],
                    representative=sym, rank_available=True)
    assert v.premarket_transport == "PASS"
    assert v.rth_continuous_capture == "PASS"
    assert v.level2_momentum_suitability == "PROVISIONAL_PASS"
    assert v.session_counted is True


def test_aapl_only_insufficient_suitability():
    v = po.evaluate(_full_counted_events("US.AAPL", role="BASELINE"),
                    symbols=["US.AAPL"], representative=None, rank_available=False)
    assert v.premarket_transport == "PASS" and v.rth_continuous_capture == "PASS"
    assert v.level2_momentum_suitability == "INSUFFICIENT_EVIDENCE"   # AAPL alone can't validate L2


def test_no_premarket_book_despite_active_tape_fails():
    sym = "US.AAPL"
    tape = [ev("QUOTE", sym, h, m, bid=10, ask=10.02) for h in (7, 8, 9) for m in (0, 30)]
    tape += [ev("TICKER", sym, 8, 0, last=10.0)]
    v = po.evaluate(tape, symbols=[sym], representative=None, rank_available=False)
    assert v.premarket_transport == "FAIL"
    assert any("ORDER_BOOK produced no fresh premarket callback" in c for c in v.critical_failures)


def test_entitlement_unavailable_insufficient():
    v = po.evaluate([], symbols=["US.AAPL"], representative=None, rank_available=False,
                    entitlement_ok=False)
    assert v.premarket_transport == "INSUFFICIENT_EVIDENCE"


def test_replay_equality_and_policy_emitted():
    sym = "US.MOVR"
    evs = _full_counted_events(sym)
    a = po.evaluate(evs, symbols=[sym], representative=sym).as_dict()
    b = po.evaluate(evs, symbols=[sym], representative=sym).as_dict()
    assert a == b and a["policy"]["version"] == "verdict-policy-1"


# ---- extended-hours subscription request -----------------------------------

def test_extended_hours_request_exact_sdk_args():
    req = po.ExtendedHoursSubscriptionRequest()
    assert req.sdk_version == "10.9.6908"
    k = req.spec_for("K_1M"); t = req.spec_for("TICKER")
    assert k.extended_time is True and k.session == "ALL"
    assert t.extended_time is True and t.session == "ALL"
    ob = req.spec_for("ORDER_BOOK")
    assert ob.session is None and ob.is_detailed_orderbook is True and ob.extended_time is False
    q = req.spec_for("QUOTE")
    assert q.extended_time is False and q.session is None


def test_subscription_success_not_freshness():
    # a first push is cached and therefore not fresh even though the subscribe "succeeded"
    e = ev("ORDER_BOOK", "US.AAPL", 8, 0, cached=True, bid=10, ask=10.02, bsize=1, asize=1)
    assert e.fresh is False


# ---- state machine ---------------------------------------------------------

def test_state_machine_idempotent_and_illegal():
    c = po.ObservationController(clock=lambda: at(6, 55))
    assert c.transition(po.ControllerState.PREFLIGHT) == po.ControllerState.PREFLIGHT
    assert c.transition(po.ControllerState.PREFLIGHT) == po.ControllerState.PREFLIGHT  # idempotent
    with pytest.raises(po.ObservationControllerError):
        c.transition(po.ControllerState.CAPTURING_RTH)   # illegal skip


def test_state_machine_no_retry_after_fail_and_teardown_from_any_state():
    c = po.ObservationController(clock=lambda: at(7, 0))
    c.transition(po.ControllerState.PREFLIGHT)
    c.transition(po.ControllerState.WAITING_FOR_0700)
    c.transition(po.ControllerState.CONNECTING)
    c.fail("agreement/security failure")
    assert c.state == po.ControllerState.FAIL
    # no path back to CONNECTING (no live retry)
    with pytest.raises(po.ObservationControllerError):
        c.transition(po.ControllerState.CONNECTING)
    assert c.teardown() == po.ControllerState.COMPLETE


def test_teardown_reachable_from_created():
    c = po.ObservationController(clock=lambda: at(6, 55))
    assert c.teardown() == po.ControllerState.COMPLETE
    assert c.teardown() == po.ControllerState.COMPLETE     # idempotent


# ---- storage / replay integration (pyarrow) --------------------------------

def test_wal_parquet_roundtrip(tmp_path):
    pytest.importorskip("pyarrow")
    from active_trader.moomoo import replay as rp
    wal = tmp_path / "seg.wal"
    w = rp.WALWriter(wal)
    for i in range(5):
        w.append({"gateway_receive_timestamp": f"2026-07-24T13:0{i}:00Z", "i": i})
    w.close()
    assert len(list(rp.wal_read(wal))) == 5
    res = rp.compact_to_parquet(wal, tmp_path / "seg.parquet")
    assert res.verified and res.row_count == 5 and res.wal_sha256


# ---- security --------------------------------------------------------------

def test_live_sink_wal_roundtrip(tmp_path):
    from active_trader import premarket_observation_live as live
    sink = live._Sink("s1", tmp_path / "s1.wal", {"US.AAPL": "BASELINE"})
    sink.push("ORDER_BOOK", "US.AAPL", {"bid": 10.0, "ask": 10.02, "bid_size": 100, "ask_size": 90,
                                        "bids": [(10.0, 100), (9.99, 50)], "asks": [(10.02, 90)]})
    sink.push("ORDER_BOOK", "US.AAPL", {"bid": 10.01, "ask": 10.03, "bids": [(10.01, 80)], "asks": [(10.03, 70)]})
    sink.push("TICKER", "US.AAPL", {"last": 10.01, "trade_size": 5})
    sink.close()
    evs = live.events_from_wal(tmp_path / "s1.wal")
    assert len(evs) == 3
    bk = [e for e in evs if e.stream == "ORDER_BOOK"]
    assert bk[0].bid == 10.0 and bk[0].ask == 10.02 and len(bk[0].bids) == 2
    assert bk[0].symbol_role == "BASELINE"
    assert bk[0].cached_first_push is True and bk[1].cached_first_push is False   # first push cached


def test_ast_no_trade_methods_in_harness():
    from active_trader.moomoo.ast_guard import scan_source
    root = Path(__file__).resolve().parents[1] / "scripts" / "active_trader"
    findings = 0
    for name in ("premarket_observation.py", "premarket_symbol_selector.py",
                 "market_calendar.py", "premarket_observation_schedule.py",
                 "premarket_observation_live.py"):
        findings += len(scan_source((root / name).read_text(), name))
    findings += len(scan_source(
        (Path(__file__).resolve().parents[1] / "scripts" / "run_active_trader_premarket_observation.py").read_text(),
        "run_root"))
    assert findings == 0


def test_no_trade_or_network_symbols_in_core():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "active_trader" / "premarket_observation.py").read_text()
    for banned in ("OpenSecTradeContext", "TradeContext", "unlock_trade", "place_order",
                   "requests.", "socket.socket", "get_acc_list"):
        assert banned not in src

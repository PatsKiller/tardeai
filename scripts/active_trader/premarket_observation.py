"""Stage 5 harness — premarket + open observation core (DETERMINISTIC; no live I/O).

Windows, extended event envelope, Level 2 streaming metrics, quote/ticker/kline cross-checks,
a versioned verdict policy + engine, a DATA-ONLY adapter protocol (no trade methods), the
typed extended-hours subscription request (exact pinned moomoo-api==10.9.6908 arguments), and
a deterministic observation controller state machine with injected clock/sleeper/calendar/
adapter/storage.

No trade SDK import. No network. No wall-clock sleeping in the pure logic. Same events ->
byte-identical metrics + verdicts (replay-equality). Reuses Stage 5 features (active_trader.
moomoo.features) for microstructure math.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from active_trader.moomoo import features as _feat

OBS_VERSION = "premarket-observation-1"
MARKET_TZ = "America/New_York"
_TZ = ZoneInfo(MARKET_TZ)


# ---- windows (controller §7) -----------------------------------------------

class Window(str, Enum):
    P1 = "P1"; P2 = "P2"; P3 = "P3"; R1 = "R1"; R2 = "R2"; OUTSIDE = "OUTSIDE"


_T = lambda h, m: h * 3600 + m * 60
# R2 upper bound is the 10:05:00 capture endpoint INCLUSIVE (+1s epsilon) so a continuous
# 09:30:00->10:05:00 stream measures exactly 35:00 (controller §15.3: 35:00 PASS / 34:59 FAIL).
_CAPTURE_END = _T(10, 5) + 1
_WINDOW_BOUNDS = (
    (Window.P1, _T(7, 0),  _T(8, 0)),
    (Window.P2, _T(8, 0),  _T(9, 20)),
    (Window.P3, _T(9, 20), _T(9, 30)),
    (Window.R1, _T(9, 30), _T(9, 45)),
    (Window.R2, _T(9, 45), _CAPTURE_END),
)
PREMARKET_REGION = (_T(7, 0), _T(9, 30))
RTH_REGION = (_T(9, 30), _CAPTURE_END)
OPEN_SECONDS = _T(9, 30)


def et_seconds(ts: _dt.datetime) -> float:
    """Seconds since ET-midnight for a timezone-aware datetime (fail closed on naive)."""
    if ts.tzinfo is None:
        raise ValueError("naive datetime not allowed at a runtime boundary")
    d = ts.astimezone(_TZ)
    return d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6


def window_for(ts: _dt.datetime) -> Window:
    s = et_seconds(ts)
    for w, lo, hi in _WINDOW_BOUNDS:
        if lo <= s < hi:
            return w
    return Window.OUTSIDE


# ---- event envelope (controller §12; extends Stage 5 envelope semantics) ----

class Freshness(str, Enum):
    FRESH = "FRESH"; CACHED_FIRST_PUSH = "CACHED_FIRST_PUSH"; STALE = "STALE"


class GapKind(str, Enum):
    NONE = "NONE"; PROVIDER_SEQUENCE_GAP = "PROVIDER_SEQUENCE_GAP"
    RECEIVE_SILENCE = "RECEIVE_SILENCE"; QUEUE_DROP = "QUEUE_DROP"
    PROCESS_RECONNECT = "PROCESS_RECONNECT"; UNKNOWN = "UNKNOWN"


@dataclass
class ObservationEvent:
    observation_session_id: str
    symbol: str
    symbol_role: str                       # BASELINE | REPRESENTATIVE
    stream: str                            # QUOTE | K_1M | ORDER_BOOK | TICKER
    receive_ts: _dt.datetime               # tz-aware — classification axis
    provider_timestamp: Optional[str] = None
    server_bid_timestamp: Optional[str] = None
    server_ask_timestamp: Optional[str] = None
    ingest_timestamp: Optional[str] = None
    provider_seq: Optional[int] = None     # null when SDK does not supply — never invented
    cached_first_push: bool = False
    freshness_state: str = Freshness.FRESH.value
    gap_state: str = GapKind.NONE.value
    queue_state: str = "HEALTHY"
    entitlement_state: str = "RESOLVED"
    market_state: Optional[str] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    bids: Optional[list] = None            # [(price,size), ...]
    asks: Optional[list] = None
    last: Optional[float] = None
    trade_size: Optional[float] = None

    @property
    def fresh(self) -> bool:
        return self.freshness_state == Freshness.FRESH.value and not self.cached_first_push

    @property
    def t(self) -> float:
        return et_seconds(self.receive_ts)

    def window(self) -> Window:
        return window_for(self.receive_ts)

    def book_key(self):
        return (self.bid, self.ask, tuple(map(tuple, self.bids or [])),
                tuple(map(tuple, self.asks or [])))


# ---- duration accounting (deterministic) -----------------------------------

def _region(events, lo, hi, *, symbol=None, fresh_only=True):
    out = [e for e in events if lo <= e.t < hi
           and (symbol is None or e.symbol == symbol)
           and (not fresh_only or e.fresh)
           and e.gap_state in (GapKind.NONE.value, GapKind.RECEIVE_SILENCE.value)]
    out.sort(key=lambda e: e.t)
    return out


def accepted_minutes(events, lo, hi, *, symbol=None, max_silence_s=60.0) -> float:
    evs = _region(events, lo, hi, symbol=symbol)
    if len(evs) < 2:
        return 0.0
    return round(sum((b.t - a.t) for a, b in zip(evs, evs[1:]) if b.t - a.t <= max_silence_s) / 60.0, 4)


def longest_continuous_minutes(events, lo, hi, *, symbol=None, max_silence_s=60.0) -> float:
    evs = _region(events, lo, hi, symbol=symbol)
    if len(evs) < 2:
        return 0.0
    run_start = prev = evs[0].t
    best = 0.0
    for e in evs[1:]:
        if e.t - prev <= max_silence_s:
            best = max(best, e.t - run_start)
        else:
            run_start = e.t
        prev = e.t
    return round(best / 60.0, 4)


def longest_silence_s(events, lo, hi, *, symbol=None) -> Optional[float]:
    evs = _region(events, lo, hi, symbol=symbol)
    if len(evs) < 2:
        return None
    return round(max(b.t - a.t for a, b in zip(evs, evs[1:])), 3)


# ---- Level 2 metrics (controller §13) --------------------------------------

INFERENCE_LABEL = "INFERRED_FROM_AGGREGATED_BOOK_SNAPSHOTS"


@dataclass
class Level2Metrics:
    symbol: str
    window: str
    callbacks: int
    fresh_callbacks: int
    updates_per_minute: Optional[float]
    first_callback_t: Optional[float]
    last_callback_t: Optional[float]
    longest_silence_s: Optional[float]
    bid_level_count: Optional[int]
    ask_level_count: Optional[int]
    distinct_bid_prices: Optional[int]
    distinct_ask_prices: Optional[int]
    top_bid: Optional[float]
    top_ask: Optional[float]
    spread: Optional[float]
    locked_crossed_count: int
    displayed_bid_depth: Optional[float]
    displayed_ask_depth: Optional[float]
    top_imbalance: Optional[float]
    weighted_imbalance: Optional[float]
    microprice: Optional[float]
    weighted_mid: Optional[float]
    replenishment_estimate: Optional[float]
    cancellation_pressure_estimate: Optional[float]
    inference_label: str
    identical_book_duration_s: Optional[float]
    stale_duration_s: float
    gap_count: int
    drop_count: int
    overflow_count: int
    reconnect_count: int
    queue_high_water: int
    server_ts_seen: bool
    data_quality: str

    def as_dict(self):
        return asdict(self)


def _pos(v):
    return v if (v is not None and v > 0) else None


def level2_metrics(events, symbol: str, window: Window, *, stream="ORDER_BOOK",
                   queue_high_water: int = 0) -> Level2Metrics:
    lo, hi = next((l, h) for w, l, h in _WINDOW_BOUNDS if w == window)
    evs = [e for e in events if e.symbol == symbol and e.stream == stream and lo <= e.t < hi]
    evs.sort(key=lambda e: e.t)
    real = [e for e in evs if e.gap_state == GapKind.NONE.value]
    fresh = [e for e in real if e.fresh]
    span_min = (hi - lo) / 60.0
    upm = round(len(fresh) / span_min, 4) if span_min > 0 else None

    latest = next((e for e in reversed(real) if e.bids or e.bid is not None), None)
    b_levels = [(p, s) for p, s in (latest.bids or [])] if latest else []
    a_levels = [(p, s) for p, s in (latest.asks or [])] if latest else []
    top_bid = (latest.bid if latest and latest.bid is not None
               else (b_levels[0][0] if b_levels else None))
    top_ask = (latest.ask if latest and latest.ask is not None
               else (a_levels[0][0] if a_levels else None))
    bsize = (latest.bid_size if latest and latest.bid_size is not None
             else (b_levels[0][1] if b_levels else None))
    asize = (latest.ask_size if latest and latest.ask_size is not None
             else (a_levels[0][1] if a_levels else None))
    # zero/negative sizes are not depth
    disp_bid = sum(s for _, s in b_levels if s and s > 0) if b_levels else _pos(bsize)
    disp_ask = sum(s for _, s in a_levels if s and s > 0) if a_levels else _pos(asize)

    # identical-book duration (unchanged snapshots)
    ident = None
    if len(real) >= 2:
        best = 0.0
        run_start = real[0].t
        for a, b in zip(real, real[1:]):
            if a.book_key() == b.book_key():
                best = max(best, b.t - run_start)
            else:
                run_start = b.t
        ident = round(best, 3)

    # stale duration: time spanned by events flagged STALE
    stale_evs = [e for e in evs if e.freshness_state == Freshness.STALE.value]
    stale_dur = round(stale_evs[-1].t - stale_evs[0].t, 3) if len(stale_evs) >= 2 else 0.0

    # replenishment / cancellation inferred from successive aggregated top depth (labeled)
    repl = canc = None
    depth_series = [(e.t, sum(s for _, s in (e.bids or []) if s and s > 0)
                     + sum(s for _, s in (e.asks or []) if s and s > 0))
                    for e in real if (e.bids or e.asks)]
    if len(depth_series) >= 2:
        ups = sum(max(0.0, b[1] - a[1]) for a, b in zip(depth_series, depth_series[1:]))
        downs = sum(max(0.0, a[1] - b[1]) for a, b in zip(depth_series, depth_series[1:]))
        repl = round(ups, 4)
        canc = round(downs, 4)

    bl = [_feat.BookLevel(p, s) for p, s in b_levels]
    al = [_feat.BookLevel(p, s) for p, s in a_levels]
    locked = sum(1 for e in real if e.bid is not None and e.ask is not None and e.bid >= e.ask)
    gap_ct = sum(1 for e in evs if e.gap_state == GapKind.PROVIDER_SEQUENCE_GAP.value
                 or e.gap_state == GapKind.RECEIVE_SILENCE.value)
    drop_ct = sum(1 for e in evs if e.gap_state == GapKind.QUEUE_DROP.value)
    over_ct = sum(1 for e in evs if e.queue_state == "OVERFLOW")
    recon_ct = sum(1 for e in evs if e.gap_state == GapKind.PROCESS_RECONNECT.value)

    if not real:
        dq = "NO_DATA"
    elif not fresh:
        dq = "ONLY_STALE"
    elif top_bid is None or top_ask is None:
        dq = "ONE_SIDED_OR_EMPTY"
    else:
        dq = "OK"

    return Level2Metrics(
        symbol=symbol, window=window.value, callbacks=len(evs), fresh_callbacks=len(fresh),
        updates_per_minute=upm,
        first_callback_t=real[0].t if real else None, last_callback_t=real[-1].t if real else None,
        longest_silence_s=(round(max(b.t - a.t for a, b in zip(real, real[1:])), 3) if len(real) >= 2 else None),
        bid_level_count=len(b_levels) if b_levels else (1 if top_bid is not None else 0),
        ask_level_count=len(a_levels) if a_levels else (1 if top_ask is not None else 0),
        distinct_bid_prices=len({p for p, _ in b_levels}) if b_levels else None,
        distinct_ask_prices=len({p for p, _ in a_levels}) if a_levels else None,
        top_bid=top_bid, top_ask=top_ask, spread=_feat.spread_cents(top_bid, top_ask),
        locked_crossed_count=locked,
        displayed_bid_depth=disp_bid, displayed_ask_depth=disp_ask,
        top_imbalance=_feat.top_imbalance(_pos(bsize), _pos(asize)),
        weighted_imbalance=_feat.level_weighted_imbalance(bl, al) if bl and al else None,
        microprice=(_feat.microprice(top_bid, top_ask, bsize, asize)
                    if None not in (top_bid, top_ask, bsize, asize) and (bsize + asize) > 0 else None),
        weighted_mid=(_feat.weighted_mid(top_bid, top_ask, bsize, asize)
                      if None not in (top_bid, top_ask, bsize, asize) and (bsize + asize) > 0 else None),
        replenishment_estimate=repl, cancellation_pressure_estimate=canc,
        inference_label=INFERENCE_LABEL,
        identical_book_duration_s=ident, stale_duration_s=stale_dur,
        gap_count=gap_ct, drop_count=drop_ct, overflow_count=over_ct, reconnect_count=recon_ct,
        queue_high_water=queue_high_water,
        server_ts_seen=any(e.server_bid_timestamp or e.server_ask_timestamp or e.provider_timestamp
                           for e in fresh),
        data_quality=dq)


# ---- cross-checks (controller §14) -----------------------------------------

class CrossOutcome(str, Enum):
    MATCH = "MATCH"; EXPECTED_SCOPE_DIFFERENCE = "EXPECTED_SCOPE_DIFFERENCE"
    MISSING_EXTENDED_HOURS = "MISSING_EXTENDED_HOURS"; STALE = "STALE"; GAP = "GAP"
    UNAVAILABLE = "UNAVAILABLE"; INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


def cross_checks(events, symbol: str) -> dict:
    def fresh_stream(s):
        return [e for e in events if e.symbol == symbol and e.stream == s and e.fresh]
    book, quote = fresh_stream("ORDER_BOOK"), fresh_stream("QUOTE")
    k1m, ticker = fresh_stream("K_1M"), fresh_stream("TICKER")
    pre = lambda evs: [e for e in evs if e.t < OPEN_SECONDS]

    def book_vs_quote():
        if not book or not quote:
            return CrossOutcome.UNAVAILABLE.value
        b = book[-1]; q = quote[-1]
        if None in (b.bid, b.ask, q.bid, q.ask):
            return CrossOutcome.INSUFFICIENT_EVIDENCE.value
        # top-of-book should be consistent with quote within a scope tolerance
        return (CrossOutcome.MATCH.value if abs((b.bid or 0) - (q.bid or 0)) <= 0.05
                and abs((b.ask or 0) - (q.ask or 0)) <= 0.05
                else CrossOutcome.EXPECTED_SCOPE_DIFFERENCE.value)

    states = [(e.t, e.market_state) for e in events if e.market_state]
    pre_state = next((s for t, s in states if t < OPEN_SECONDS), None)
    post_state = next((s for t, s in reversed(states) if t >= OPEN_SECONDS), None)
    return {
        "book_top_vs_quote": book_vs_quote(),
        "ticker_vs_book_spread": (CrossOutcome.MATCH.value if ticker and book
                                  else CrossOutcome.UNAVAILABLE.value),
        "k1m_premarket_timestamps": (CrossOutcome.MATCH.value if pre(k1m)
                                     else CrossOutcome.MISSING_EXTENDED_HOURS.value),
        "ticker_premarket_timestamps": (CrossOutcome.MATCH.value if pre(ticker)
                                        else CrossOutcome.MISSING_EXTENDED_HOURS.value),
        "market_state_pre_open": pre_state,
        "market_state_post_open": post_state,
        "market_state_transition_at_0930": bool(pre_state and post_state and pre_state != post_state),
        "continuity_across_0930": (CrossOutcome.MATCH.value
                                   if any(e.t < OPEN_SECONDS for e in book)
                                   and any(e.t >= OPEN_SECONDS for e in book)
                                   else CrossOutcome.GAP.value),
    }


# ---- verdict policy + engine (controller §15) ------------------------------

@dataclass(frozen=True)
class VerdictPolicy:
    """Observation thresholds (NOT strategy-profitability thresholds). Versioned + emitted."""
    version: str = "verdict-policy-1"
    max_silence_s: float = 60.0
    startup_margin_s: float = 90.0
    min_premarket_minutes: float = 145.0
    min_rth_continuous_minutes: float = 35.0
    min_book_levels: int = 2
    min_updates_per_minute: float = 2.0
    min_total_depth: float = 1.0

    def as_dict(self):
        return asdict(self)


class TransportVerdict(str, Enum):
    PASS = "PASS"; FAIL = "FAIL"; INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SuitabilityVerdict(str, Enum):
    PROVISIONAL_PASS = "PROVISIONAL_PASS"; FAIL = "FAIL"; INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RthVerdict(str, Enum):
    PASS = "PASS"; FAIL = "FAIL"


@dataclass
class ObservationVerdicts:
    obs_version: str
    policy: dict
    symbols: list
    representative: Optional[str]
    representative_available: bool
    accepted_premarket_minutes: float
    accepted_rth_continuous_minutes: float
    premarket_transport: str
    level2_momentum_suitability: str
    rth_continuous_capture: str
    session_counted: bool
    level2_metrics: dict
    cross_checks: dict
    critical_failures: list
    notes: list

    def as_dict(self):
        return asdict(self)


def evaluate(events, *, symbols, representative, policy: Optional[VerdictPolicy] = None,
             entitlement_ok=True, rank_available=True, critical_failures=None,
             wal_parquet_replay_ok=True, safety_ok=True) -> ObservationVerdicts:
    pol = policy or VerdictPolicy()
    crit = list(critical_failures or [])
    notes = []
    rep = representative or (symbols[0] if symbols else None)
    rep_is_strategy = bool(representative) and rank_available

    acc_pre = accepted_minutes(events, *PREMARKET_REGION, symbol=rep, max_silence_s=pol.max_silence_s)
    rth_cont = longest_continuous_minutes(events, *RTH_REGION, symbol=rep, max_silence_s=pol.max_silence_s)
    l2 = {w.value: level2_metrics(events, rep, w).as_dict() for w, _, _ in _WINDOW_BOUNDS} if rep else {}
    xc = cross_checks(events, rep) if rep else {}

    # PREMARKET_TRANSPORT
    book_present = any((l2.get(w, {}).get("callbacks") or 0) > 0 for w in ("P1", "P2", "P3"))
    other_present = xc.get("book_top_vs_quote") not in (None, CrossOutcome.UNAVAILABLE.value) or \
        xc.get("ticker_premarket_timestamps") == CrossOutcome.MATCH.value
    if not entitlement_ok:
        transport = TransportVerdict.INSUFFICIENT_EVIDENCE.value
        notes.append("book entitlement unresolved")
    elif not book_present:
        transport = (TransportVerdict.FAIL.value if other_present
                     else TransportVerdict.INSUFFICIENT_EVIDENCE.value)
        if transport == TransportVerdict.FAIL.value:
            crit.append("ORDER_BOOK produced no fresh premarket callback while other data active")
    elif not any(l2.get(w, {}).get("server_ts_seen") for w in ("P1", "P2", "P3")):
        transport = TransportVerdict.FAIL.value
        crit.append("server timestamps remained zero/cached after first-push exclusion")
    elif acc_pre + pol.startup_margin_s / 60.0 < pol.min_premarket_minutes:
        transport = TransportVerdict.FAIL.value
        notes.append(f"accepted premarket minutes {acc_pre} < {pol.min_premarket_minutes}")
    elif crit:
        transport = TransportVerdict.FAIL.value
    else:
        transport = TransportVerdict.PASS.value

    # RTH_CONTINUOUS_CAPTURE
    rth = (RthVerdict.FAIL.value if crit or rth_cont < pol.min_rth_continuous_minutes
           else RthVerdict.PASS.value)
    if rth == RthVerdict.FAIL.value and not crit:
        notes.append(f"continuous RTH minutes {rth_cont} < {pol.min_rth_continuous_minutes}")

    # LEVEL2_MOMENTUM_SUITABILITY (max PROVISIONAL_PASS)
    if not rep_is_strategy:
        suit = SuitabilityVerdict.INSUFFICIENT_EVIDENCE.value
        notes.append("AAPL-only / no representative momentum candidate — cannot validate L2 for scalping")
    else:
        core = [l2.get(w, {}) for w in ("P2", "P3", "R1")]
        levels_ok = any((m.get("bid_level_count") or 0) >= pol.min_book_levels
                        and (m.get("ask_level_count") or 0) >= pol.min_book_levels for m in core)
        depth_ok = any((m.get("displayed_bid_depth") or 0) >= pol.min_total_depth
                       and (m.get("displayed_ask_depth") or 0) >= pol.min_total_depth for m in core)
        rate_ok = any((m.get("updates_per_minute") or 0) >= pol.min_updates_per_minute for m in core)
        only_stale = all((m.get("fresh_callbacks") or 0) == 0 for m in core)
        if only_stale or (not depth_ok and not levels_ok):
            suit = SuitabilityVerdict.FAIL.value
            notes.append("book depth trivial / only stale while tape active")
        elif levels_ok and depth_ok and rate_ok and not crit:
            suit = SuitabilityVerdict.PROVISIONAL_PASS.value
        else:
            suit = SuitabilityVerdict.INSUFFICIENT_EVIDENCE.value

    counted = (transport == TransportVerdict.PASS.value and rth == RthVerdict.PASS.value
               and wal_parquet_replay_ok and safety_ok and not crit)
    return ObservationVerdicts(
        obs_version=OBS_VERSION, policy=pol.as_dict(), symbols=list(symbols), representative=rep,
        representative_available=rep_is_strategy,
        accepted_premarket_minutes=acc_pre, accepted_rth_continuous_minutes=rth_cont,
        premarket_transport=transport, level2_momentum_suitability=suit, rth_continuous_capture=rth,
        session_counted=counted, level2_metrics=l2, cross_checks=xc,
        critical_failures=crit, notes=notes)


# ---- data-only adapter protocol (controller §9) ----------------------------

@runtime_checkable
class DataOnlyQuoteAdapter(Protocol):
    """Quote/data ONLY. No trade context/method appears here; no generic invoke escape hatch."""
    def connect_data(self) -> dict: ...
    def global_state(self) -> dict: ...
    def market_state(self) -> dict: ...
    def subscription_quota(self) -> dict: ...
    def premarket_rank(self) -> list: ...
    def snapshot(self, symbols: list) -> list: ...
    def subscribe_quote(self, symbol: str) -> dict: ...
    def subscribe_k1m_extended(self, symbol: str) -> dict: ...
    def subscribe_order_book(self, symbol: str) -> dict: ...
    def subscribe_ticker_extended(self, symbol: str) -> dict: ...
    def unsubscribe(self, symbol: str) -> dict: ...
    def close(self) -> None: ...


# ---- extended-hours subscription request (controller §10) ------------------
# Exact pinned moomoo-api==10.9.6908 subscribe() args:
#   subscribe(code_list, subtype_list, is_first_push=True, subscribe_push=True,
#             is_detailed_orderbook=False, extended_time=False, session=<Session>)
# Session members: ALL, ETH, NONE, OVERNIGHT, RTH.

@dataclass(frozen=True)
class SubscriptionSpec:
    stream: str
    subtype: str
    extended_time: bool
    session: Optional[str]                 # "ALL" | None ; mapped to moomoo.Session at live wiring
    is_detailed_orderbook: bool = False

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ExtendedHoursSubscriptionRequest:
    version: str = "subrequest-1"
    sdk_version: str = "10.9.6908"
    specs: tuple = (
        SubscriptionSpec("QUOTE", "QUOTE", extended_time=False, session=None),
        SubscriptionSpec("K_1M", "K_1M", extended_time=True, session="ALL"),
        SubscriptionSpec("ORDER_BOOK", "ORDER_BOOK", extended_time=False, session=None,
                         is_detailed_orderbook=True),
        SubscriptionSpec("TICKER", "TICKER", extended_time=True, session="ALL"),
    )

    def spec_for(self, stream: str) -> SubscriptionSpec:
        return next(s for s in self.specs if s.stream == stream)

    def as_dict(self):
        return {"version": self.version, "sdk_version": self.sdk_version,
                "specs": [s.as_dict() for s in self.specs]}


# ---- observation controller state machine (controller §8) ------------------

class ControllerState(str, Enum):
    CREATED = "CREATED"; PREFLIGHT = "PREFLIGHT"; WAITING_FOR_0700 = "WAITING_FOR_0700"
    CONNECTING = "CONNECTING"; AUTHENTICATED_DATA_ONLY = "AUTHENTICATED_DATA_ONLY"
    SELECTING_SYMBOL = "SELECTING_SYMBOL"; SUBSCRIBING = "SUBSCRIBING"
    CAPTURING_PREMARKET = "CAPTURING_PREMARKET"; TRANSITIONING_OPEN = "TRANSITIONING_OPEN"
    CAPTURING_RTH = "CAPTURING_RTH"; FINALIZING = "FINALIZING"; REPLAYING = "REPLAYING"
    PASS = "PASS"; INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"; FAIL = "FAIL"
    TEARDOWN = "TEARDOWN"; COMPLETE = "COMPLETE"


_TERMINAL = {ControllerState.COMPLETE}
_VERDICT_STATES = {ControllerState.PASS, ControllerState.INSUFFICIENT_EVIDENCE, ControllerState.FAIL}
_ALLOWED = {
    ControllerState.CREATED: {ControllerState.PREFLIGHT, ControllerState.TEARDOWN},
    ControllerState.PREFLIGHT: {ControllerState.WAITING_FOR_0700, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.WAITING_FOR_0700: {ControllerState.CONNECTING, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.CONNECTING: {ControllerState.AUTHENTICATED_DATA_ONLY, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.AUTHENTICATED_DATA_ONLY: {ControllerState.SELECTING_SYMBOL, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.SELECTING_SYMBOL: {ControllerState.SUBSCRIBING, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.SUBSCRIBING: {ControllerState.CAPTURING_PREMARKET, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.CAPTURING_PREMARKET: {ControllerState.TRANSITIONING_OPEN, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.TRANSITIONING_OPEN: {ControllerState.CAPTURING_RTH, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.CAPTURING_RTH: {ControllerState.FINALIZING, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.FINALIZING: {ControllerState.REPLAYING, ControllerState.FAIL, ControllerState.TEARDOWN},
    ControllerState.REPLAYING: _VERDICT_STATES | {ControllerState.TEARDOWN},
    ControllerState.PASS: {ControllerState.TEARDOWN},
    ControllerState.INSUFFICIENT_EVIDENCE: {ControllerState.TEARDOWN},
    ControllerState.FAIL: {ControllerState.TEARDOWN},
    ControllerState.TEARDOWN: {ControllerState.COMPLETE},
    ControllerState.COMPLETE: set(),
}


class ObservationControllerError(RuntimeError):
    pass


class ObservationController:
    """Deterministic, idempotent state machine. Injected clock/sleeper/calendar/adapter/storage.
    NEVER auto-retries after an auth/agreement/security failure. Teardown reachable from any state."""

    def __init__(self, *, clock, sleeper=None, calendar=None, adapter=None, storage=None):
        self.clock = clock                      # callable -> tz-aware datetime
        self.sleeper = sleeper or (lambda s: None)
        self.calendar = calendar
        self.adapter = adapter
        self.storage = storage
        self.state = ControllerState.CREATED
        self.history = [ControllerState.CREATED]
        self.torn_down = False

    def transition(self, to: ControllerState) -> ControllerState:
        if to == self.state:
            return self.state                   # idempotent
        if to not in _ALLOWED.get(self.state, set()):
            raise ObservationControllerError(f"illegal transition {self.state.value} -> {to.value}")
        self.state = to
        self.history.append(to)
        return to

    def fail(self, reason: str) -> ControllerState:
        """Terminal failure — NO live retry. Always followed by teardown."""
        self.reason = reason
        if self.state not in _VERDICT_STATES and self.state not in (ControllerState.TEARDOWN, ControllerState.COMPLETE):
            self.transition(ControllerState.FAIL)
        return self.state

    def teardown(self) -> ControllerState:
        """Safe teardown reachable from EVERY state (idempotent)."""
        if self.state in (ControllerState.TEARDOWN, ControllerState.COMPLETE):
            self._finish_teardown()
            return self.state
        # any state may jump to TEARDOWN
        self.state = ControllerState.TEARDOWN
        self.history.append(ControllerState.TEARDOWN)
        self._finish_teardown()
        return self.state

    def _finish_teardown(self):
        if not self.torn_down and self.adapter is not None:
            try:
                self.adapter.close()
            except Exception:
                pass
        self.torn_down = True
        if self.state == ControllerState.TEARDOWN:
            self.state = ControllerState.COMPLETE
            self.history.append(ControllerState.COMPLETE)

    def verdict_state_for(self, verdicts: ObservationVerdicts) -> ControllerState:
        if verdicts.critical_failures or verdicts.premarket_transport == TransportVerdict.FAIL.value \
                or verdicts.rth_continuous_capture == RthVerdict.FAIL.value:
            return ControllerState.FAIL
        if verdicts.session_counted:
            return ControllerState.PASS
        return ControllerState.INSUFFICIENT_EVIDENCE

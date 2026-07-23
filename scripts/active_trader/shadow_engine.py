"""Active Trader Stage 9 — deterministic SHADOW decision engine.

Prime, fire, RES (resilience), RRS (resistance), runner, journal. Shadow-only:
no order, no broker call, no production notification. Deterministic, versioned,
no LLM, no lookahead, replayable. Inputs are fixtures/replay feature snapshots.

Stage 5 five-RTH-session data gate is PENDING — this engine is implemented and
tested against fixtures/replay only. It is NOT promoted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

ENGINE_VERSION = "shadow-engine-1"
RES_VERSION = "res-1"
RRS_VERSION = "rrs-1"


# ---------------------------------------------------------------- inputs

@dataclass(frozen=True)
class DecisionInput:
    """A point-in-time feature snapshot (from Stage 5 replay/features or a fixture).
    Only fields observed AT OR BEFORE as_of may be present — the caller guarantees no
    lookahead; the engine additionally refuses any field flagged future."""
    symbol: str
    as_of_ns: int
    candidate_state: str = "IN_SCOPE"     # IN_SCOPE / WAIT / NO_GO / BLOCKED
    price: Optional[float] = None
    vwap: Optional[float] = None
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    rvol: Optional[float] = None
    spread_bps: Optional[float] = None
    float_shares: Optional[float] = None
    halt_state: str = "NONE"              # NONE / HALTED / LULD
    catalyst_present: bool = False
    capability_ok: bool = True
    risk_ok: bool = True
    data_state: str = "HEALTHY"          # HEALTHY / AGING / STALE / SEQUENCE_GAP / QUEUE_OVERFLOW
    # microstructure (may be None before Stage 5 data)
    integrated_ofi: Optional[float] = None
    tape_aggressor_buy: Optional[float] = None
    bid_replenish: Optional[float] = None
    ask_replenish: Optional[float] = None
    reclaim_speed: Optional[float] = None
    higher_low: Optional[bool] = None
    failed_breakouts: Optional[int] = None
    # explicit future-leak guard: caller must never set this true
    contains_future_data: bool = False


# ---------------------------------------------------------------- prime / fire

class PrimeState(str, Enum):
    NOT_PRIMED = "NOT_PRIMED"
    PRIMED = "PRIMED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FireState(str, Enum):
    NO_FIRE = "NO_FIRE"
    FIRE_SHADOW = "FIRE_SHADOW"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    STALE = "STALE"
    DATA_GAP = "DATA_GAP"


@dataclass(frozen=True)
class Decision:
    state: str
    version: str
    reason_trace: tuple


def _no_lookahead(inp: DecisionInput):
    if inp.contains_future_data:
        raise ValueError("lookahead: input flagged as containing future data")


def evaluate_prime(inp: DecisionInput) -> Decision:
    _no_lookahead(inp)
    trace = []
    if inp.data_state in ("STALE", "SEQUENCE_GAP", "QUEUE_OVERFLOW"):
        return Decision(PrimeState.STALE.value, ENGINE_VERSION, (f"data:{inp.data_state}",))
    if inp.candidate_state in ("NO_GO", "BLOCKED") or inp.halt_state in ("HALTED", "LULD"):
        return Decision(PrimeState.BLOCKED.value, ENGINE_VERSION,
                        (f"candidate:{inp.candidate_state}", f"halt:{inp.halt_state}"))
    if not inp.capability_ok or not inp.risk_ok:
        return Decision(PrimeState.BLOCKED.value, ENGINE_VERSION,
                        (f"capability_ok:{inp.capability_ok}", f"risk_ok:{inp.risk_ok}"))
    required = (inp.price, inp.vwap, inp.rvol, inp.spread_bps)
    if any(v is None for v in required):
        return Decision(PrimeState.INSUFFICIENT_DATA.value, ENGINE_VERSION,
                        ("missing: price/vwap/rvol/spread",))
    # deterministic seed gates (unvalidated defaults; shadow only)
    trace.append(f"price_vs_vwap:{inp.price >= inp.vwap}")
    trace.append(f"rvol:{inp.rvol}")
    trace.append(f"spread_bps:{inp.spread_bps}")
    primed = (inp.candidate_state == "IN_SCOPE" and inp.price >= inp.vwap
              and inp.rvol >= 3.0 and inp.spread_bps <= 20.0)
    return Decision(PrimeState.PRIMED.value if primed else PrimeState.NOT_PRIMED.value,
                    ENGINE_VERSION, tuple(trace))


def evaluate_fire(inp: DecisionInput, prime: Decision) -> Decision:
    _no_lookahead(inp)
    if inp.data_state in ("SEQUENCE_GAP", "QUEUE_OVERFLOW"):
        return Decision(FireState.DATA_GAP.value, ENGINE_VERSION, (f"data:{inp.data_state}",))
    if inp.data_state == "STALE":
        return Decision(FireState.STALE.value, ENGINE_VERSION, ("data:STALE",))
    if prime.state != PrimeState.PRIMED.value:
        return Decision(FireState.NO_FIRE.value, ENGINE_VERSION, (f"prime:{prime.state}",))
    if inp.halt_state in ("HALTED", "LULD") or not inp.capability_ok or not inp.risk_ok:
        return Decision(FireState.BLOCKED.value, ENGINE_VERSION, ("halt/cap/risk block",))
    micro = (inp.integrated_ofi, inp.tape_aggressor_buy)
    if any(v is None for v in micro):
        # no microstructure (pre-Stage-5 data) → cannot fire, but not an error
        return Decision(FireState.NO_FIRE.value, ENGINE_VERSION, ("microstructure unavailable",))
    trace = (f"break_high:{inp.session_high is not None and inp.price >= inp.session_high}",
             f"ofi:{inp.integrated_ofi}", f"tape_buy:{inp.tape_aggressor_buy}")
    fire = (inp.session_high is not None and inp.price >= inp.session_high
            and inp.integrated_ofi > 0 and inp.tape_aggressor_buy >= 0.58)
    return Decision(FireState.FIRE_SHADOW.value if fire else FireState.NO_FIRE.value,
                    ENGINE_VERSION, trace)


# ---------------------------------------------------------------- RES / RRS

@dataclass(frozen=True)
class Score:
    value: Optional[float]
    version: str
    confidence: str                      # HIGH / MEDIUM / LOW / INSUFFICIENT
    components: dict


def _score(components: dict, version: str) -> Score:
    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        return Score(None, version, "INSUFFICIENT", components)
    total = sum(present.values())
    total = max(0.0, min(100.0, total))
    conf = "HIGH" if len(present) >= max(1, int(0.75 * len(components))) else \
        ("MEDIUM" if len(present) >= max(1, int(0.4 * len(components))) else "LOW")
    return Score(round(total, 3), version, conf, components)


def resilience_score(inp: DecisionInput) -> Score:
    _no_lookahead(inp)
    c = {
        "vwap_hold": 12.0 if (inp.price is not None and inp.vwap is not None and inp.price >= inp.vwap) else None,
        "higher_low": 12.0 if inp.higher_low else (0.0 if inp.higher_low is False else None),
        "reclaim_speed": (min(10.0, inp.reclaim_speed) if inp.reclaim_speed is not None else None),
        "bid_replenish": (min(10.0, inp.bid_replenish) if inp.bid_replenish is not None else None),
        "integrated_ofi": (12.0 if (inp.integrated_ofi is not None and inp.integrated_ofi > 0) else
                           (0.0 if inp.integrated_ofi is not None else None)),
        "tape_response": (10.0 * inp.tape_aggressor_buy if inp.tape_aggressor_buy is not None else None),
        "spread_recovery": (6.0 if (inp.spread_bps is not None and inp.spread_bps <= 20) else
                            (0.0 if inp.spread_bps is not None else None)),
        "volume_continuation": (min(8.0, inp.rvol) if inp.rvol is not None else None),
    }
    return _score(c, RES_VERSION)


def resistance_score(inp: DecisionInput) -> Score:
    _no_lookahead(inp)
    c = {
        "failed_breakouts": (min(12.0, 4.0 * inp.failed_breakouts) if inp.failed_breakouts is not None else None),
        "ask_replenish": (min(12.0, inp.ask_replenish) if inp.ask_replenish is not None else None),
        "negative_ofi": (12.0 if (inp.integrated_ofi is not None and inp.integrated_ofi < 0) else
                        (0.0 if inp.integrated_ofi is not None else None)),
        "sell_aggressor": (10.0 * (1 - inp.tape_aggressor_buy) if inp.tape_aggressor_buy is not None else None),
        "spread_expansion": (7.0 if (inp.spread_bps is not None and inp.spread_bps > 20) else
                            (0.0 if inp.spread_bps is not None else None)),
        "at_resistance": (10.0 if (inp.price is not None and inp.session_high is not None
                                   and inp.price >= inp.session_high) else
                         (0.0 if inp.price is not None and inp.session_high is not None else None)),
    }
    return _score(c, RRS_VERSION)


# ---------------------------------------------------------------- runner

class RunnerState(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    ACTIVE = "ACTIVE"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    INVALIDATED = "INVALIDATED"
    DATA_BLOCKED = "DATA_BLOCKED"


def runner_state(inp: DecisionInput, res: Score, rrs: Score, *, currently_active: bool = False) -> Decision:
    _no_lookahead(inp)
    if inp.data_state in ("STALE", "SEQUENCE_GAP", "QUEUE_OVERFLOW"):
        return Decision(RunnerState.DATA_BLOCKED.value, ENGINE_VERSION, (f"data:{inp.data_state}",))
    if res.value is None or rrs.value is None:
        return Decision(RunnerState.NOT_ELIGIBLE.value, ENGINE_VERSION, ("scores insufficient",))
    if rrs.value >= 80 or (inp.halt_state in ("HALTED", "LULD")):
        return Decision(RunnerState.EXIT.value, ENGINE_VERSION,
                        (f"rrs:{rrs.value}", f"halt:{inp.halt_state}"))
    if res.value < 50:
        return Decision((RunnerState.INVALIDATED if currently_active else RunnerState.NOT_ELIGIBLE).value,
                        ENGINE_VERSION, (f"res:{res.value}",))
    if res.value >= 75 and rrs.value <= 35:
        return Decision((RunnerState.ACTIVE if currently_active else RunnerState.ELIGIBLE).value,
                        ENGINE_VERSION, (f"res:{res.value}", f"rrs:{rrs.value}"))
    if rrs.value > 60:
        return Decision(RunnerState.REDUCE.value, ENGINE_VERSION, (f"rrs:{rrs.value}",))
    return Decision((RunnerState.ACTIVE if currently_active else RunnerState.ELIGIBLE).value,
                    ENGINE_VERSION, ("demand intact",))


# ---------------------------------------------------------------- journal

def journal_events(symbol: str, prime: Decision, fire: Decision, res: Score, rrs: Score,
                   runner: Decision) -> list[dict]:
    """Append-only shadow journal events with explicit synthetic/replay provenance."""
    def ev(t, payload):
        return {"event_type": t, "symbol": symbol, "provenance": "SHADOW_FIXTURE_OR_REPLAY",
                "engine_version": ENGINE_VERSION, "payload": payload}
    return [
        ev("prime_evaluated", {"state": prime.state, "trace": list(prime.reason_trace)}),
        ev("fire_evaluated", {"state": fire.state, "trace": list(fire.reason_trace)}),
        ev("res_scored", {"value": res.value, "confidence": res.confidence, "version": res.version}),
        ev("rrs_scored", {"value": rrs.value, "confidence": rrs.confidence, "version": rrs.version}),
        ev("runner_evaluated", {"state": runner.state, "trace": list(runner.reason_trace)}),
    ]


def run_shadow(inp: DecisionInput, *, currently_active: bool = False) -> dict:
    """Full deterministic pass. No broker, no order — shadow only."""
    prime = evaluate_prime(inp)
    fire = evaluate_fire(inp, prime)
    res = resilience_score(inp)
    rrs = resistance_score(inp)
    runner = runner_state(inp, res, rrs, currently_active=currently_active)
    return {"prime": prime, "fire": fire, "res": res, "rrs": rrs, "runner": runner,
            "journal": journal_events(inp.symbol, prime, fire, res, rrs, runner)}

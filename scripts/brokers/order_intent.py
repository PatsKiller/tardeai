"""Canonical broker-agnostic order-intent model (ADR-B2).

Written to the richest VERIFIED broker surface (Schwab SDK schema) so the model never migrates when a broker
is added. Pure data + validation + serde — NO broker I/O lives here. See docs/brokers/canonical-order-model.md.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class EntryMethod(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    MARKET_ON_CLOSE = "MARKET_ON_CLOSE"
    LIMIT_ON_CLOSE = "LIMIT_ON_CLOSE"


class TIF(str, Enum):
    DAY = "DAY"
    GTC = "GTC"
    FOK = "FOK"
    IOC = "IOC"
    EOW = "EOW"
    EOM = "EOM"


class SessionPolicy(str, Enum):
    NORMAL = "NORMAL"
    AM = "AM"
    PM = "PM"
    SEAMLESS = "SEAMLESS"


class AssetType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"          # model-only this phase (capability-blocked)


class IntentState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    TRANSLATED = "TRANSLATED"
    BLOCKED = "BLOCKED"
    SUBMITTED_PENDING = "SUBMITTED_PENDING"   # unreachable for Schwab this phase
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class PriceLinkBasis(str, Enum):
    LAST = "LAST"
    BID = "BID"
    ASK = "ASK"
    MARK = "MARK"


class PriceLinkType(str, Enum):
    VALUE = "VALUE"
    PERCENT = "PERCENT"
    TICK = "TICK"


class StopFailPolicy(str, Enum):
    CLOSE_POSITION = "CLOSE_POSITION"   # preserves the Alpaca contract (unhedged => close)
    ALERT_ONLY = "ALERT_ONLY"


@dataclass
class PriceLink:
    basis: PriceLinkBasis
    type: PriceLinkType
    offset: float


@dataclass
class TrailConfig:
    basis: PriceLinkBasis
    type: PriceLinkType
    offset: float


@dataclass
class StopSpec:
    price: Optional[float] = None
    trail: Optional[TrailConfig] = None


@dataclass
class TargetSpec:
    price: float
    qty_pct: float = 100.0


@dataclass
class ExitPolicy:
    stop: Optional[StopSpec] = None
    targets: list[TargetSpec] = field(default_factory=list)
    oco: bool = True
    on_stop_place_failure: StopFailPolicy = StopFailPolicy.CLOSE_POSITION


@dataclass
class LadderLeg:
    entry_price: float
    qty_pct: float


@dataclass
class LadderConfig:
    legs: list[LadderLeg]
    cancel_policy: str = "ALL_ON_STOP"     # ALL_ON_STOP | INDEPENDENT


@dataclass
class EntrySpec:
    method: EntryMethod = EntryMethod.LIMIT
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    entry_range: Optional[dict] = None      # {"low": x, "high": y} — product concept
    price_link: Optional[PriceLink] = None  # bid-style entries (Schwab-representable)


@dataclass
class Quantity:
    qty: Optional[float] = None
    notional: Optional[float] = None
    contracts: Optional[int] = None


@dataclass
class RiskSettings:
    risk_reward: Optional[float] = None
    max_dollar_risk: Optional[float] = None
    position_size_usd: Optional[float] = None
    sizing_basis: str = "shares"


@dataclass
class Instrument:
    symbol: str
    asset_type: AssetType = AssetType.EQUITY
    option_legs: list[dict] = field(default_factory=list)   # model-only this phase


@dataclass
class IntentMeta:
    strategy_id: Optional[str] = None
    proposal_id: Optional[int] = None
    thesis: Optional[str] = None
    signal_evidence: Optional[dict] = None
    created_by: str = "operator"


@dataclass
class OrderIntent:
    instrument: Instrument
    direction: Direction
    entry: EntrySpec
    quantity: Quantity
    broker: str = "schwab"
    account_key: Optional[str] = None
    tif: TIF = TIF.DAY
    session: SessionPolicy = SessionPolicy.NORMAL
    exit_policy: ExitPolicy = field(default_factory=ExitPolicy)
    ladder: Optional[LadderConfig] = None
    risk: RiskSettings = field(default_factory=RiskSettings)
    meta: IntentMeta = field(default_factory=IntentMeta)
    state: IntentState = IntentState.DRAFT
    intent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ── serde ───────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        def enc(o):
            if isinstance(o, Enum):
                return o.value
            if isinstance(o, Decimal):
                return float(o)
            raise TypeError(type(o))
        return json.loads(json.dumps(asdict(self), default=enc))

    @classmethod
    def from_dict(cls, d: dict) -> "OrderIntent":
        d = dict(d)
        d["instrument"] = Instrument(symbol=d["instrument"]["symbol"],
                                     asset_type=AssetType(d["instrument"].get("asset_type", "EQUITY")),
                                     option_legs=d["instrument"].get("option_legs") or [])
        d["direction"] = Direction(d["direction"])
        e = d.get("entry") or {}
        pl = e.get("price_link")
        d["entry"] = EntrySpec(method=EntryMethod(e.get("method", "LIMIT")),
                               limit_price=e.get("limit_price"), stop_price=e.get("stop_price"),
                               entry_range=e.get("entry_range"),
                               price_link=PriceLink(PriceLinkBasis(pl["basis"]), PriceLinkType(pl["type"]),
                                                    float(pl["offset"])) if pl else None)
        q = d.get("quantity") or {}
        d["quantity"] = Quantity(qty=q.get("qty"), notional=q.get("notional"), contracts=q.get("contracts"))
        d["tif"] = TIF(d.get("tif", "DAY"))
        d["session"] = SessionPolicy(d.get("session", "NORMAL"))
        xp = d.get("exit_policy") or {}
        st = xp.get("stop")
        stop = None
        if st:
            tr = st.get("trail")
            stop = StopSpec(price=st.get("price"),
                            trail=TrailConfig(PriceLinkBasis(tr["basis"]), PriceLinkType(tr["type"]),
                                              float(tr["offset"])) if tr else None)
        d["exit_policy"] = ExitPolicy(
            stop=stop,
            targets=[TargetSpec(price=t["price"], qty_pct=t.get("qty_pct", 100.0))
                     for t in (xp.get("targets") or [])],
            oco=xp.get("oco", True),
            on_stop_place_failure=StopFailPolicy(xp.get("on_stop_place_failure", "CLOSE_POSITION")))
        la = d.get("ladder")
        d["ladder"] = (LadderConfig(legs=[LadderLeg(l["entry_price"], l["qty_pct"]) for l in la["legs"]],
                                    cancel_policy=la.get("cancel_policy", "ALL_ON_STOP")) if la else None)
        r = d.get("risk") or {}
        d["risk"] = RiskSettings(risk_reward=r.get("risk_reward"), max_dollar_risk=r.get("max_dollar_risk"),
                                 position_size_usd=r.get("position_size_usd"),
                                 sizing_basis=r.get("sizing_basis", "shares"))
        m = d.get("meta") or {}
        d["meta"] = IntentMeta(strategy_id=m.get("strategy_id"), proposal_id=m.get("proposal_id"),
                               thesis=m.get("thesis"), signal_evidence=m.get("signal_evidence"),
                               created_by=m.get("created_by", "operator"))
        d["state"] = IntentState(d.get("state", "DRAFT"))
        return cls(**d)


# ── validation ──────────────────────────────────────────────────────────────
@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def validate(intent: OrderIntent) -> ValidationResult:
    """Deterministic structural validation — broker-agnostic. Capability checks live in capabilities.py."""
    errs: list[str] = []
    warns: list[str] = []
    e, xp, q = intent.entry, intent.exit_policy, intent.quantity

    # exactly one quantity basis
    bases = [b for b in (q.qty, q.notional, q.contracts) if b]
    if len(bases) != 1:
        errs.append("quantity: exactly one of qty/notional/contracts must be set")
    if q.qty is not None and q.qty <= 0:
        errs.append("quantity.qty must be > 0")

    # entry coherence
    if e.method in (EntryMethod.LIMIT, EntryMethod.STOP_LIMIT, EntryMethod.LIMIT_ON_CLOSE) \
            and not e.limit_price and not e.price_link and not e.entry_range:
        errs.append(f"entry.method={e.method.value} requires limit_price, price_link or entry_range")
    if e.method in (EntryMethod.STOP, EntryMethod.STOP_LIMIT) and not e.stop_price:
        errs.append(f"entry.method={e.method.value} requires stop_price")
    if e.entry_range:
        if e.method != EntryMethod.LIMIT:
            errs.append("entry_range requires method=LIMIT")
        elif not (e.entry_range.get("low") and e.entry_range.get("high")
                  and e.entry_range["low"] < e.entry_range["high"]):
            errs.append("entry_range requires low < high")

    # exit ordering (longs: stop < entry-ref < targets; shorts inverted)
    ref = e.limit_price or e.stop_price or (e.entry_range or {}).get("high")
    if xp.stop and xp.stop.price and ref:
        if intent.direction == Direction.LONG and not xp.stop.price < ref:
            errs.append(f"stop {xp.stop.price} must be below entry {ref} for LONG")
        if intent.direction == Direction.SHORT and not xp.stop.price > ref:
            errs.append(f"stop {xp.stop.price} must be above entry {ref} for SHORT")
    for t in xp.targets:
        if ref:
            if intent.direction == Direction.LONG and not t.price > ref:
                errs.append(f"target {t.price} must be above entry {ref} for LONG")
            if intent.direction == Direction.SHORT and not t.price < ref:
                errs.append(f"target {t.price} must be below entry {ref} for SHORT")
    if xp.targets:
        s = sum(t.qty_pct for t in xp.targets)
        if abs(s - 100.0) > 0.01:
            errs.append(f"target qty_pct must sum to 100 (got {s})")
    if xp.oco and not (xp.stop and xp.targets):
        warns.append("oco=true but exits incomplete (need stop AND >=1 target) — treated as non-OCO")

    # trailing
    tr = xp.stop.trail if xp.stop else None
    if tr and not (tr.offset and tr.offset > 0):
        errs.append("trailing stop requires offset > 0")

    # ladder
    if intent.ladder:
        ls = sum(l.qty_pct for l in intent.ladder.legs)
        if abs(ls - 100.0) > 0.01:
            errs.append(f"ladder qty_pct must sum to 100 (got {ls})")
        if len(intent.ladder.legs) < 2:
            errs.append("ladder requires >= 2 legs")

    # options: model-only this phase
    if intent.instrument.asset_type == AssetType.OPTION or intent.instrument.option_legs:
        errs.append("BLOCKED_CAPABILITY: options intents are model-only this phase (operator decision 2026-06-11)")

    return ValidationResult(ok=not errs, errors=errs, warnings=warns)

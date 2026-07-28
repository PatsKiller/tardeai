"""Active Trader P4 — deterministic internal execution path (SIMULATION ONLY).

This module is the internal decision + dispatch pipeline for a FIRED setup. It is
**100% inert**: the only "adapter" it can reach is a pure in-process simulator that
returns a fake fill. There is NO live broker adapter import here, no order-submit call,
no live second-factor step, no live secret read, no network. It cannot move real money.

Pipeline for one FIRED setup event::

    FIRED event
      -> event/hash validation
      -> session-authorization validation
      -> account-capability validation      (broker_capabilities.is_execution_eligible)
      -> quote/book/tape freshness validation
      -> universal-gate validation
      -> server-side quantity + risk calculation
      -> immutable OrderIntent
      -> idempotency check   (session_id, event_id)
      -> SIMULATION adapter dispatch
      -> simulated ack
      -> protection confirmation
      -> reconciliation
      -> journal

An :class:`OrderIntent` is created ONLY when ALL of these hold:

  * ``setup_state == FIRED``
  * ``gate_decision == PASS``
  * data is not stale (quote/book/tape within freshness budget)
  * required T2 evidence is present when the setup needs it
  * session is ACTIVE and in-envelope (account + symbol authorized, risk within limits)
  * the setup event's registry hash matches the expected registry hash
  * the kill switch is off
  * the entry cutoff has not passed

Any other condition returns a typed :class:`Refusal` with a reason — NEVER an intent.
Entry is price-controlled (limit) ONLY; a market entry is refused. Idempotency is keyed
on ``(session_id, event_id)`` so a duplicated event can never create a second intent.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

from active_trader import broker_capabilities as caps

# ONE shared pure stop-reference validator (Defect 2) — no duplication across the three call sites.
# Imported defensively so this inert module never hard-fails if the scripts path is not wired.
try:
    from scalp_execution_gate import validate_stop_reference as _validate_stop_reference
except Exception:  # pragma: no cover - import-path fallback only
    try:
        from scripts.scalp_execution_gate import validate_stop_reference as _validate_stop_reference
    except Exception:
        _validate_stop_reference = None

CONTRACT = "active-trader-sim-execution-v1"

# ── setup states ───────────────────────────────────────────────────────────────
STATE_FIRED = "FIRED"

# ── gate decisions ─────────────────────────────────────────────────────────────
GATE_PASS = "PASS"

# ── refusal reason codes (typed, exhaustive) ───────────────────────────────────
R_NOT_FIRED = "setup_not_fired"
R_EVENT_INVALID = "event_invalid"
R_HASH_MISMATCH = "registry_hash_mismatch"
R_KILL_SWITCH = "kill_switch_engaged"
R_SESSION_INACTIVE = "session_not_active"
R_ENTRY_CUTOFF = "entry_cutoff_passed"
R_ACCOUNT_UNAUTHORIZED = "account_not_authorized"
R_SYMBOL_UNAUTHORIZED = "symbol_not_authorized"
R_CAPABILITY_INELIGIBLE = "account_not_execution_eligible"
R_DATA_STALE = "market_data_stale"
R_GATE_VETO = "universal_gate_veto"
R_MISSING_T2 = "required_t2_evidence_missing"
R_MARKET_FORBIDDEN = "market_entry_forbidden"
R_RISK_BREACH = "risk_envelope_breach"
R_STOP_INVALID = "stop_reference_below_noise_floor"
R_DUPLICATE = "duplicate_event_idempotent"

# stages (for observability / journal)
STAGE_EVENT = "event_hash"
STAGE_SESSION = "session_authorization"
STAGE_CAPABILITY = "account_capability"
STAGE_FRESHNESS = "data_freshness"
STAGE_GATE = "universal_gate"
STAGE_RISK = "quantity_risk"
STAGE_IDEMPOTENCY = "idempotency"
STAGE_DISPATCH = "sim_dispatch"

# adapter identity — there is no live adapter; this string is the ONLY dispatch target.
SIM_ADAPTER = "SIMULATION"

DEFAULT_FRESHNESS = {
    "max_quote_age_s": 5.0,
    "max_book_age_s": 5.0,
    "max_tape_age_s": 10.0,
}


# ── typed results ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Refusal:
    ok: bool
    stage: str
    reason_code: str
    message: str
    session_id: str
    event_id: str
    contract: str = CONTRACT

    @property
    def is_intent(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    session_id: str
    event_id: str
    account_id: str
    broker: str
    environment: str
    symbol: str
    side: str
    order_type: str            # always "limit" — price-controlled only
    limit_price: float
    stop_price: float
    quantity: int
    risk_amount: float
    registry_hash: str
    created_at: Optional[float]
    simulated: bool = True     # HARD: intents from this path are simulation-only
    contract: str = CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimFill:
    fill_id: str
    intent_id: str
    status: str
    filled_qty: int
    fill_price: float
    ts: Optional[float]
    adapter: str = SIM_ADAPTER
    simulated: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionOutcome:
    ok: bool
    intent: Optional[OrderIntent]
    fill: Optional[SimFill]
    protection: Optional[dict[str, Any]]
    reconciliation: Optional[dict[str, Any]]
    journal_entry: Optional[dict[str, Any]]
    contract: str = CONTRACT

    @property
    def is_intent(self) -> bool:
        return self.intent is not None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["intent"] = self.intent.to_dict() if self.intent else None
        d["fill"] = self.fill.to_dict() if self.fill else None
        return d


# ── helpers ────────────────────────────────────────────────────────────────────

def _s(v: Any) -> str:
    return str(v or "").strip()


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _refuse(stage: str, code: str, msg: str, session_id: str, event_id: str) -> Refusal:
    return Refusal(False, stage, code, msg, str(session_id), str(event_id))


def _idem_key(session_id: str, event_id: str) -> str:
    return f"{session_id}::{event_id}"


def _intent_id(session_id: str, event_id: str, registry_hash: str) -> str:
    raw = f"{session_id}|{event_id}|{registry_hash}".encode("utf-8")
    return "intent_" + hashlib.sha256(raw).hexdigest()[:16]


def _simulate_fill(intent: OrderIntent, now: Optional[float]) -> SimFill:
    """Pure simulator. A marketable price-controlled entry fills at its limit price.

    This is the ENTIRE 'adapter'. No live client, no network, no order submission.
    """
    raw = f"{intent.intent_id}|fill".encode("utf-8")
    fill_id = "simfill_" + hashlib.sha256(raw).hexdigest()[:16]
    return SimFill(
        fill_id=fill_id,
        intent_id=intent.intent_id,
        status="filled_sim",
        filled_qty=intent.quantity,
        fill_price=intent.limit_price,
        ts=now,
    )


class SimExecutionEngine:
    """Stateful pipeline holder: in-memory journal + idempotency ledger.

    Deterministic. Holds NO broker client. The only dispatch target is the pure
    :func:`_simulate_fill` simulator.
    """

    def __init__(self) -> None:
        self._journal: list[dict[str, Any]] = []
        self._by_key: dict[str, str] = {}  # (session::event) -> intent_id

    # -- introspection ----------------------------------------------------------
    @property
    def journal(self) -> list[dict[str, Any]]:
        return list(self._journal)

    def intents(self) -> list[dict[str, Any]]:
        return [e for e in self._journal if e.get("kind") == "intent"]

    def intent_count(self) -> int:
        return len(self.intents())

    # -- main entrypoint ---------------------------------------------------------
    def process(
        self,
        event: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionOutcome | Refusal:
        event = event if isinstance(event, Mapping) else {}
        context = context if isinstance(context, Mapping) else {}

        session_id = _s(event.get("session_id"))
        event_id = _s(event.get("event_id"))
        symbol = _s(event.get("symbol")).upper()

        # ── STAGE 1: event / hash validation ──────────────────────────────────
        if _s(event.get("setup_state")).upper() != STATE_FIRED:
            return _refuse(STAGE_EVENT, R_NOT_FIRED,
                           "setup_state is not FIRED", session_id, event_id)
        if not session_id or not event_id or not symbol:
            return _refuse(STAGE_EVENT, R_EVENT_INVALID,
                           "event missing session_id/event_id/symbol", session_id, event_id)

        session = context.get("session")
        session = session if isinstance(session, Mapping) else {}
        expected_hash = _s(context.get("expected_registry_hash"))
        event_hash = _s(event.get("registry_hash"))
        session_hash = _s(session.get("registry_hash")) or expected_hash
        if not expected_hash or event_hash != expected_hash or session_hash != expected_hash:
            return _refuse(STAGE_EVENT, R_HASH_MISMATCH,
                           "registry hash mismatch", session_id, event_id)

        # ── STAGE 2: session authorization ────────────────────────────────────
        if bool(context.get("kill_switch")):
            return _refuse(STAGE_SESSION, R_KILL_SWITCH,
                           "kill switch engaged", session_id, event_id)
        if _s(session.get("state")).upper() != "ACTIVE":
            return _refuse(STAGE_SESSION, R_SESSION_INACTIVE,
                           "session is not ACTIVE", session_id, event_id)

        now = _f(context.get("now"))
        cutoff = _f(session.get("entry_cutoff"))
        if cutoff is not None and now is not None and now > cutoff:
            return _refuse(STAGE_SESSION, R_ENTRY_CUTOFF,
                           "entry cutoff has passed", session_id, event_id)

        account_id = _s(event.get("account_id")) or _s(session.get("account_id"))
        authorized_accounts = session.get("authorized_accounts")
        authorized_accounts = authorized_accounts if isinstance(authorized_accounts, (list, tuple, set)) else ()
        if not account_id or account_id not in set(authorized_accounts):
            return _refuse(STAGE_SESSION, R_ACCOUNT_UNAUTHORIZED,
                           "account not authorized for this session", session_id, event_id)

        authorized_symbols = session.get("authorized_symbols")
        authorized_symbols = authorized_symbols if isinstance(authorized_symbols, (list, tuple, set)) else ()
        if symbol not in {str(s).upper() for s in authorized_symbols}:
            return _refuse(STAGE_SESSION, R_SYMBOL_UNAUTHORIZED,
                           "symbol not authorized for this session", session_id, event_id)

        # ── STAGE 3: account capability ───────────────────────────────────────
        snapshot = context.get("capability_snapshot")
        cap = caps.resolve_capability(account_id, snapshot, now=now)
        if not caps.is_execution_eligible(cap):
            return _refuse(STAGE_CAPABILITY, R_CAPABILITY_INELIGIBLE,
                           f"account not execution-eligible ({cap.eligibility_reason})",
                           session_id, event_id)

        # ── STAGE 4: quote / book / tape freshness ────────────────────────────
        fr = context.get("freshness")
        fr = fr if isinstance(fr, Mapping) else {}
        budgets = {
            "quote": _f(fr.get("max_quote_age_s")) or DEFAULT_FRESHNESS["max_quote_age_s"],
            "book": _f(fr.get("max_book_age_s")) or DEFAULT_FRESHNESS["max_book_age_s"],
            "tape": _f(fr.get("max_tape_age_s")) or DEFAULT_FRESHNESS["max_tape_age_s"],
        }
        for feed, budget in budgets.items():
            data = event.get(feed)
            data = data if isinstance(data, Mapping) else {}
            ts = _f(data.get("ts"))
            if ts is None or now is None or (now - ts) > budget or (now - ts) < 0:
                return _refuse(STAGE_FRESHNESS, R_DATA_STALE,
                               f"{feed} data stale or missing timestamp", session_id, event_id)

        # ── STAGE 5: universal gate + T2 evidence ─────────────────────────────
        if _s(event.get("gate_decision")).upper() != GATE_PASS:
            return _refuse(STAGE_GATE, R_GATE_VETO,
                           "universal gate did not PASS", session_id, event_id)
        if bool(event.get("requires_t2")):
            t2 = event.get("t2_evidence")
            if not isinstance(t2, Mapping) or not t2:
                return _refuse(STAGE_GATE, R_MISSING_T2,
                               "setup requires T2 evidence which is absent", session_id, event_id)

        # ── STAGE 6: server-side quantity + risk calculation ──────────────────
        entry = event.get("entry")
        entry = entry if isinstance(entry, Mapping) else {}
        side = _s(event.get("side") or entry.get("side")).lower() or "buy"
        order_type = _s(entry.get("order_type")).lower()
        limit_price = _f(entry.get("limit_price"))
        stop_price = _f(entry.get("stop_price"))

        # Price-controlled ONLY — a market entry (or a missing limit price) is refused.
        if order_type != "limit" or limit_price is None or limit_price <= 0:
            return _refuse(STAGE_RISK, R_MARKET_FORBIDDEN,
                           "entry must be a price-controlled limit with a limit_price",
                           session_id, event_id)
        if not caps.supports_price_controlled(cap):
            return _refuse(STAGE_RISK, R_MARKET_FORBIDDEN,
                           "account does not support price-controlled entry",
                           session_id, event_id)
        if stop_price is None or stop_price <= 0:
            return _refuse(STAGE_RISK, R_RISK_BREACH,
                           "a protective stop price is required", session_id, event_id)

        # Defect 2 — the SAME deterministic minimum-stop-floor validator used by the detector gate. A stop
        # inside tick/spread/volatility noise is refused here too (never widened). Config-driven floor via
        # context['stop_floor_cfg']; the validator carries CONFIGURABLE ENGINE ADAPTATION fallbacks.
        if _validate_stop_reference is not None:
            sv = _validate_stop_reference(
                entry_ref=limit_price, stop_ref=stop_price,
                atr_1m=_f(event.get("atr_1m")), spread_bps=_f(event.get("spread_bps")),
                price_increment=_f(event.get("price_increment")), price=limit_price,
                data_tier=_s(event.get("data_tier")) or None,
                cfg=context.get("stop_floor_cfg") if isinstance(context.get("stop_floor_cfg"), Mapping) else None)
            if sv.get("stop_validation") != "PASS":
                return _refuse(STAGE_RISK, R_STOP_INVALID,
                               "stop reference below deterministic noise floor: "
                               + ",".join(sv.get("reason_codes", [])), session_id, event_id)

        risk = session.get("risk")
        risk = risk if isinstance(risk, Mapping) else {}
        max_risk = _f(risk.get("max_risk_per_trade"))
        max_notional = _f(risk.get("max_position_notional"))
        if max_risk is None or max_risk <= 0:
            return _refuse(STAGE_RISK, R_RISK_BREACH,
                           "session has no positive per-trade risk budget", session_id, event_id)

        # long-only price-controlled sizing: risk per share = limit - stop
        risk_per_share = limit_price - stop_price
        if risk_per_share <= 0:
            return _refuse(STAGE_RISK, R_RISK_BREACH,
                           "stop must be below the limit for a long entry", session_id, event_id)

        quantity = int(max_risk // risk_per_share)
        if quantity <= 0:
            return _refuse(STAGE_RISK, R_RISK_BREACH,
                           "risk budget too small for one share", session_id, event_id)

        notional = quantity * limit_price
        if max_notional is not None and notional > max_notional:
            return _refuse(STAGE_RISK, R_RISK_BREACH,
                           "position notional exceeds session cap", session_id, event_id)

        risk_amount = round(quantity * risk_per_share, 4)
        if risk_amount > max_risk + 1e-9:
            return _refuse(STAGE_RISK, R_RISK_BREACH,
                           "computed risk exceeds per-trade budget", session_id, event_id)

        # ── STAGE 7: immutable OrderIntent ────────────────────────────────────
        intent = OrderIntent(
            intent_id=_intent_id(session_id, event_id, expected_hash),
            session_id=session_id,
            event_id=event_id,
            account_id=account_id,
            broker=cap.broker,
            environment=cap.environment,
            symbol=symbol,
            side=side,
            order_type="limit",
            limit_price=limit_price,
            stop_price=stop_price,
            quantity=quantity,
            risk_amount=risk_amount,
            registry_hash=expected_hash,
            created_at=now,
        )

        # ── STAGE 8: idempotency ──────────────────────────────────────────────
        key = _idem_key(session_id, event_id)
        if key in self._by_key:
            return _refuse(STAGE_IDEMPOTENCY, R_DUPLICATE,
                           f"duplicate event; intent {self._by_key[key]} already exists",
                           session_id, event_id)

        # commit intent to the ledger BEFORE dispatch so a duplicate can never race in
        self._by_key[key] = intent.intent_id
        self._journal.append({"kind": "intent", "intent_id": intent.intent_id, **intent.to_dict()})

        # ── STAGE 9: SIMULATION dispatch -> ack -> protection -> reconcile ────
        fill = _simulate_fill(intent, now)
        self._journal.append({"kind": "sim_ack", "intent_id": intent.intent_id, **fill.to_dict()})

        protection = {
            "kind": "protection",
            "intent_id": intent.intent_id,
            "status": "protected_sim",
            "protection_type": "stop",
            "stop_price": intent.stop_price,
            "adapter": SIM_ADAPTER,
            "simulated": True,
        }
        self._journal.append(protection)

        reconciliation = {
            "kind": "reconciliation",
            "intent_id": intent.intent_id,
            "reconciled": (fill.filled_qty == intent.quantity
                           and fill.status == "filled_sim"),
            "intent_qty": intent.quantity,
            "filled_qty": fill.filled_qty,
            "symbol": intent.symbol,
            "adapter": SIM_ADAPTER,
            "simulated": True,
        }
        self._journal.append(reconciliation)

        journal_entry = {
            "kind": "journal",
            "intent_id": intent.intent_id,
            "session_id": session_id,
            "event_id": event_id,
            "symbol": intent.symbol,
            "quantity": intent.quantity,
            "limit_price": intent.limit_price,
            "stop_price": intent.stop_price,
            "risk_amount": intent.risk_amount,
            "adapter": SIM_ADAPTER,
            "simulated": True,
        }
        self._journal.append(journal_entry)

        return ExecutionOutcome(
            ok=True,
            intent=intent,
            fill=fill,
            protection=protection,
            reconciliation=reconciliation,
            journal_entry=journal_entry,
        )

"""BrokerExecutionGuard (ADR-B3): fail-closed mode gating + audit. THE safety layer of this program.

Schwab default = BROKER_DISABLED. LIVE_ENABLED_FUTURE is defined but unreachable: it demands env flag + DB
control row + signed approval record, none of which exist, and the Schwab adapter raises unconditionally
anyway. Every decision (grant OR block) is audited with a correlation id.
"""
from __future__ import annotations

import os
from enum import Enum
from dataclasses import dataclass

from .order_intent import OrderIntent
from . import capabilities


class BrokerExecutionMode(str, Enum):
    SIMULATION = "SIMULATION"
    PAPER_TRAINING = "PAPER_TRAINING"        # Alpaca pipeline — never re-pointable to Schwab
    BROKER_DRY_RUN = "BROKER_DRY_RUN"        # local translate+validate+audit; ZERO order-endpoint HTTP
    BROKER_DISABLED = "BROKER_DISABLED"      # Schwab, this phase
    LIVE_ENABLED_FUTURE = "LIVE_ENABLED_FUTURE"


class ExecutionBlocked(Exception):
    """Raised whenever an execution path is reached without an explicit grant."""


@dataclass
class GuardDecision:
    allowed: bool
    mode: BrokerExecutionMode
    reason: str
    correlation_id: str


def mode_for(broker: str) -> BrokerExecutionMode:
    """Resolve the broker's execution mode — fail closed on anything unknown."""
    default = capabilities.get(broker).get("execution_mode_default", "BROKER_DISABLED")
    try:
        return BrokerExecutionMode(default)
    except ValueError:
        return BrokerExecutionMode.BROKER_DISABLED


def _live_future_unlocked() -> bool:
    """Standing locks open? Physical key = env flag OR non-expired session OR standing DB unlock
    (operator 2026-06-22: all 3 Schwab accounts, no session expiry). PLUS broker_live_enabled +
    standing approval. Per-order 2FA still required for every submit."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        env_ok = os.getenv("BROKER_LIVE_ENABLED", "false").lower() == "true"
        session_ok = False
        cur.execute("SELECT value FROM system_controls WHERE key='pilot_armed_until'")
        sr = cur.fetchone()
        if sr and sr[0]:
            import datetime as _dt
            try:
                session_ok = _dt.datetime.fromisoformat(str(sr[0])) > _dt.datetime.now(_dt.timezone.utc)
            except Exception:
                session_ok = False
        cur.execute("SELECT value FROM system_controls WHERE key='schwab_pilot_standing_unlock'")
        st = cur.fetchone()
        standing_ok = bool(st and str(st[0]).lower() == "true")
        if not (env_ok or session_ok or standing_ok):
            return False
        cur.execute("SELECT value FROM system_controls WHERE key='broker_live_enabled'")
        r = cur.fetchone()
        if not r or str(r[0]).lower() != "true":
            return False
        cur.execute("SELECT count(*) FROM broker_live_approvals WHERE revoked_at IS NULL")
        return (cur.fetchone()[0] or 0) > 0
    except Exception:
        return False


def _protective_unlocked() -> bool:
    """Stage 2c protective stops are a STANDING capability (operator 2026-06-15: 'no ARM control around
    them once unlocked'). Unlike the canary BUY pilot they do NOT require the expiring pilot_armed_until
    session — a protective SELL stop is the safe direction (sell-to-close only; can't open a position or
    overspend; bounded by protective_stop_policy: drift, qty<=held, stop-below-price, notional). Standing
    gate = policy ENABLED (committed) AND a standing DB authorization
    (system_controls['protective_stops_enabled']='true', set once, cleared to revoke). Per-order 2FA, the
    policy envelope, and the account's api_write_enabled still gate EVERY submit. Any error => locked."""
    try:
        from .protective_stop_policy import ENABLED
        if not ENABLED:
            return False
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='protective_stops_enabled'")
        r = cur.fetchone()
        return bool(r and str(r[0]).lower() == "true")
    except Exception:
        return False


_MUTATING_ACTIONS = ("submit", "replace")   # cancel stays allowed-in-principle: cancelling is the safe direction

PROTECTIVE_STOP_MARKER = "PROTECTIVE_STOP_2C"   # intent.meta.strategy_id stamp routing through protective_stop_policy
FIDELITY_PROTECTIVE_MARKER = "FIDELITY_MONITORED_STOP"  # SnapTrade-read Fidelity holdings — monitored path
OPTIONS_EXECUTION_MARKER = "OPTIONS_EXECUTION_1"  # options_execution_policy envelope


def _is_protective_stop(intent: OrderIntent) -> bool:
    try:
        return getattr(getattr(intent, "meta", None), "strategy_id", None) in (
            PROTECTIVE_STOP_MARKER, FIDELITY_PROTECTIVE_MARKER)
    except Exception:
        return False


def _is_options_execution(intent: OrderIntent) -> bool:
    try:
        return getattr(getattr(intent, "meta", None), "strategy_id", None) == OPTIONS_EXECUTION_MARKER
    except Exception:
        return False


def _options_unlocked() -> bool:
    """Standing unlock: policy ENABLED (commit) + DB options_execution_enabled flag."""
    try:
        from .options_execution_policy import ENABLED
        if not ENABLED:
            return False
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='options_execution_enabled'")
        r = cur.fetchone()
        return bool(r and str(r[0]).lower() == "true")
    except Exception:
        return False


def _options_gate_reason(intent: OrderIntent) -> str | None:
    try:
        from .options_execution_policy import evaluate as _eval
        ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
        ok, reasons = _eval(
            account_key=intent.account_key,
            strategy=str(ev.get("strategy") or "covered_call"),
            order_type=str(ev.get("order_type") or "LIMIT"),
            contracts=int(ev.get("contracts") or intent.quantity.contracts or 0),
            notional_usd=float(ev.get("notional_usd") or 0),
            spread_width_pct=ev.get("spread_width_pct"),
            symbol=intent.instrument.symbol if intent.instrument else None,
        )
        return None if ok else "; ".join(reasons)
    except Exception as e:
        return f"options gate unavailable ({str(e)[:60]}) — fail closed"


def _is_fidelity_monitored(intent: OrderIntent) -> bool:
    try:
        return getattr(getattr(intent, "meta", None), "strategy_id", None) == FIDELITY_PROTECTIVE_MARKER
    except Exception:
        return False


def _fidelity_monitored_unlocked() -> bool:
    """Standing unlock for Fidelity monitored stops (operator snaptrade_pilot_arm.py --approve)."""
    try:
        from .snaptrade_protective_stop_policy import MONITORED_ENABLED
        if not MONITORED_ENABLED:
            return False
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='fidelity_stops_enabled'")
        r = cur.fetchone()
        return bool(r and str(r[0]).lower() == "true")
    except Exception:
        return False


def _protective_gate_reason(intent: OrderIntent) -> str | None:
    """Evaluate the Stage-2c protective-stop envelope (its OWN committed envelope — sell-to-close a long,
    drift/qty/notional caps + POC proof layer). Returns None when allowed, else the joined reason(s).
    Pulls the non-intent fields (advised stop, live price, held qty, order_type) from meta.signal_evidence."""
    try:
        if _is_fidelity_monitored(intent):
            from .snaptrade_protective_stop_policy import evaluate as _ps_eval
        else:
            from .protective_stop_policy import evaluate as _ps_eval
        ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
        ok, reasons = _ps_eval(
            account_key=intent.account_key,
            instruction=str(ev.get("instruction") or "SELL"),
            order_type=str(ev.get("order_type") or ""),
            stop_price=ev.get("stop_price") if ev.get("stop_price") is not None else getattr(intent.entry, "stop_price", None),
            advised_stop=ev.get("advised_stop"),
            current_price=ev.get("current_price"),
            qty=(intent.quantity.qty if intent.quantity else None),
            held_qty=ev.get("held_qty"),
            symbol=(intent.instrument.symbol if intent.instrument else None),
        )
        return None if ok else "; ".join(reasons)
    except Exception as e:
        return f"protective-stop gate unavailable ({str(e)[:60]}) — fail closed"


def authorize(intent: OrderIntent, action: str = "submit") -> GuardDecision:
    """The single gate every adapter call must pass. Audited regardless of outcome."""
    mode = mode_for(intent.broker)
    protective = _is_protective_stop(intent)
    options_exec = _is_options_execution(intent)
    # ── HARDCODED CANARY GATE (Stage 2a Part D, operator 2026-06-12) ──────────────────────────
    # Evaluated BEFORE the mode logic so no present-or-future allow branch can bypass it. Applies
    # to every mutating action on every broker EXCEPT the alpaca paper-training pipeline (Hard
    # Rule 7: paper gate untouched). The envelope lives in canary_gate.py — commit-only literals;
    # any gate failure (including import failure) denies. Redundant this phase by design.
    #
    # Stage-2c protective stops (sells-to-close real holdings, far outside the $4/$40 BUY canary) route
    # through their OWN committed envelope (protective_stop_policy) INSTEAD of the canary gate — selected
    # by the intent.meta marker. Same fail-closed discipline; neither gate can widen the other.
    if action in _MUTATING_ACTIONS and intent.broker != "alpaca":
        if options_exec:
            gate_reason = _options_gate_reason(intent)
        elif protective:
            gate_reason = _protective_gate_reason(intent)
        else:
            try:
                from .canary_gate import evaluate as _canary_evaluate
                g = _canary_evaluate(intent)
                gate_reason = None if g.allowed else "; ".join(g.reasons)
            except Exception as e:
                gate_reason = f"canary gate unavailable ({str(e)[:60]}) — fail closed"
        if gate_reason:
            _label = ("OPTIONS_GATE BLOCK" if options_exec else
                      "PROTECTIVE_STOP_GATE BLOCK" if protective else "CANARY_GATE BLOCK")
            d = GuardDecision(False, mode, f"{_label}: {gate_reason}", intent.correlation_id)
            try:
                from .audit import record_guard_decision
                record_guard_decision(intent, action, d)
            except Exception:
                pass
            return d
    if mode == BrokerExecutionMode.PAPER_TRAINING and intent.broker == "alpaca":
        d = GuardDecision(True, mode, "alpaca paper training path (existing pipeline)", intent.correlation_id)
    elif mode == BrokerExecutionMode.BROKER_DRY_RUN:
        d = GuardDecision(action in ("translate", "preview", "validate"), mode,
                          "dry-run: local translate/validate/audit only — order-endpoint I/O prohibited "
                          "(operator decision 2026-06-11)", intent.correlation_id)
    elif ((options_exec and _options_unlocked() and _live_future_unlocked())
          or (protective and _is_fidelity_monitored(intent) and _fidelity_monitored_unlocked())
          or (protective and not _is_fidelity_monitored(intent) and _protective_unlocked())
          or (mode == BrokerExecutionMode.LIVE_ENABLED_FUTURE and _live_future_unlocked())):
        # GRANT branch. Two ways in:
        #   • protective stop + STANDING protective-unlock (no expiring arm session; operator 2026-06-15), or
        #   • canary/general write + the arm-session unlock (Stage 2b — still needs ARM).
        # Either way the gate above already passed (protective_stop_policy for protective, canary_gate else).
        # Remaining per-order locks: pilot caps (canary only — skipped for protective) and per-trade
        # TWO-FACTOR approval (web typed-ticker OR telegram/email code, unexpired, single-use).
        # Cancel is the safe direction: allowed under open locks without 2FA (audited).
        if action == "cancel":
            d = GuardDecision(True, mode, "cancel granted (safe direction) under unlocked Stage 2b pilot",
                              intent.correlation_id)
        else:
            try:
                from .approval_service import is_fully_approved
                twofa = is_fully_approved(intent.intent_id)
            except Exception:
                twofa = False
            # Protective stops are NOT counted against the canary 5-order pilot cap — they carry their own
            # envelope (protective_stop_policy, already evaluated above as the gate). The canary cap stays
            # the cap for the BUY canary only.
            if protective or options_exec:
                pilot_ok, pilot_reasons = True, []
            else:
                try:
                    from .pilot_caps import evaluate as _pilot_eval
                    pilot_ok, pilot_reasons = _pilot_eval(intent.account_key)
                except Exception as e:
                    pilot_ok, pilot_reasons = False, [f"pilot caps unavailable ({str(e)[:60]}) — fail closed"]
            if not pilot_ok:
                d = GuardDecision(False, mode, "PILOT_CAPS BLOCK: " + "; ".join(pilot_reasons),
                                  intent.correlation_id)
            elif not twofa:
                d = GuardDecision(False, mode,
                                  "DENIED: per-trade two-factor approval missing/incomplete (web typed-ticker "
                                  "OR telegram/email code)", intent.correlation_id)
            else:
                d = GuardDecision(True, mode,
                                  ("GRANTED (Options): policy envelope + standing unlock + per-trade 2FA"
                                   if options_exec else
                                   "GRANTED (Stage 2c protective stop): protective envelope + standing locks "
                                   "+ per-trade 2FA all green" if protective else
                                   "GRANTED (Stage 2b pilot): canary envelope + standing locks + pilot caps "
                                   "+ per-trade 2FA all green"), intent.correlation_id)
    else:
        d = GuardDecision(False, BrokerExecutionMode.BROKER_DISABLED,
                          f"broker '{intent.broker}' execution disabled (fail-closed default)",
                          intent.correlation_id)
    try:
        from .audit import record_guard_decision
        record_guard_decision(intent, action, d)
    except Exception:
        pass  # audit failure must not grant/extend execution; decision already made
    return d


def require(intent: OrderIntent, action: str = "submit") -> None:
    d = authorize(intent, action)
    if not d.allowed:
        raise ExecutionBlocked(d.reason)

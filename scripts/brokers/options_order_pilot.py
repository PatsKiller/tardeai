"""Options order pilot — build + 2FA + submit Schwab option orders (Stage Options-1).

Routes through OPTIONS_EXECUTION_MARKER → options_execution_policy envelope.
kind='options' on schwab_pilot_orders — does not consume canary order cap.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brokers.order_intent import OrderIntent

OPTIONS_EXECUTION_MARKER = "OPTIONS_EXECUTION_1"

_INSTRUCTION = {
    "covered_call": "SELL_TO_OPEN",
    "cash_secured_put": "SELL_TO_OPEN",
    "long_call": "BUY_TO_OPEN",
    "long_put": "BUY_TO_OPEN",
    "protective_put": "BUY_TO_OPEN",
    "credit_spread_short": "SELL_TO_OPEN",
    "credit_spread_long": "BUY_TO_OPEN",
}


def _occ_symbol(underlying: str, expiration: str, option_type: str, strike: float) -> str:
    """Build Schwab OCC symbol (simplified)."""
    from datetime import datetime
    exp = expiration[:10]
    dt = datetime.strptime(exp, "%Y-%m-%d")
    yymmdd = dt.strftime("%y%m%d")
    cp = "C" if option_type.lower() == "call" else "P"
    strike_int = int(round(strike * 1000))
    root = underlying.upper().ljust(6)[:6]
    return f"{root.strip()}{yymmdd}{cp}{strike_int:08d}"


def build_single_leg_spec(
    underlying: str,
    expiration: str,
    option_type: str,
    strike: float,
    contracts: int,
    strategy: str,
    *,
    limit_price: float | None = None,
    order_type: str = "LIMIT",
) -> dict:
    instr = _occ_symbol(underlying, expiration, option_type, strike)
    instr_side = "call" if option_type.lower() == "call" else "put"
    instruction = _INSTRUCTION.get(strategy, "SELL_TO_OPEN")
    leg = {
        "instruction": instruction,
        "quantity": int(contracts),
        "instrument": {"symbol": instr, "assetType": "OPTION"},
    }
    spec = {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": order_type,
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [leg],
    }
    if limit_price is not None and order_type == "LIMIT":
        spec["price"] = str(Decimal(str(limit_price)).quantize(Decimal("0.01")))
    return spec


def build_credit_spread_spec(
    underlying: str,
    expiration: str,
    option_type: str,
    short_strike: float,
    long_strike: float,
    contracts: int,
    *,
    net_credit: float,
) -> dict:
    short_occ = _occ_symbol(underlying, expiration, option_type, short_strike)
    long_occ = _occ_symbol(underlying, expiration, option_type, long_strike)
    legs = [
        {"instruction": "SELL_TO_OPEN", "quantity": int(contracts),
         "instrument": {"symbol": short_occ, "assetType": "OPTION"}},
        {"instruction": "BUY_TO_OPEN", "quantity": int(contracts),
         "instrument": {"symbol": long_occ, "assetType": "OPTION"}},
    ]
    return {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "NET_CREDIT",
        "price": str(Decimal(str(net_credit)).quantize(Decimal("0.01"))),
        "orderStrategyType": "SINGLE",
        "orderLegCollection": legs,
    }


def _age_seconds(ts, now=None) -> float | None:
    """Seconds since an ISO/epoch timestamp, or None when absent/unparseable (never 0)."""
    if ts in (None, ""):
        return None
    try:
        from brokers.quote_time import quote_age_seconds
        return quote_age_seconds(ts, now=now)
    except Exception:
        return None


def authorization_evidence(proposal: dict, *, buying_power: float | None = None,
                           buying_power_as_of: str | None = None, now=None) -> dict:
    """The facts an options order authorization binds to (order-authorization contract,
    2026-09-27). Everything a reviewer listed as 'must fail closed if it changes after
    approval' is carried on the intent itself, so confirm/submit re-check the SAME facts:
    proposal version (pin), desk approval pin (strategy GUID + canonical legs hash), quote
    and chain timestamps (ages are recomputed from these at submit, never trusted as a
    number), data source, executable credit basis, buying power and its timestamp, and
    the collateral the order commits."""
    try:
        import options_desk_enterprise as ent
        pin = ent.approval_pin(proposal)
    except Exception:  # noqa: BLE001
        pin = {"approved_strategy_guid": proposal.get("option_strategy_guid"), "approved_hash": None, "legs": None}
    from scripts.lib import options_workflow as wf
    econ = proposal.get("economics") or {}
    collateral = (proposal.get("workflow_economics") or {}).get("capital_required")
    for k in ("collateral", "cash_committed", "option_cost_total"):
        if collateral is None and econ.get(k) is not None:
            collateral = float(econ[k])
            break
    if collateral is None and proposal.get("strategy") == "credit_spread" and proposal.get("short_strike") and proposal.get("long_strike"):
        collateral = abs(float(proposal["short_strike"]) - float(proposal["long_strike"])) * 100 * int(proposal.get("contracts") or 1)
    quotes_as_of = proposal.get("quotes_as_of")
    if not quotes_as_of:
        legs = [l for l in (proposal.get("legs_liquidity") or []) if isinstance(l, dict) and l.get("quote_time")]
        quotes_as_of = min((l["quote_time"] for l in legs), default=None) or proposal.get("quote_time")
    return {
        "proposal_revision": proposal.get("revision"),
        "approved_order_binding": wf.order_binding(proposal),
        "analysis_binding": wf.analysis_binding(proposal),
        "analysis_reference": (proposal.get("analysis") or {}).get("id"),
        "proposal_id": proposal.get("id"),
        "source_proposal_id": proposal.get("source_proposal_id") or proposal.get("id"),
        "directive_reference": proposal.get("directive_id"),
        "directive_version": proposal.get("directive_version"),
        "proposal_pin": (proposal.get("options_thesis") or {}).get("pin") or proposal.get("thesis_version_at_decision"),
        "approved_strategy_guid": pin.get("approved_strategy_guid"),
        "approval_hash": pin.get("approved_hash"),
        "canonical_legs": pin.get("legs"),
        "data_source": proposal.get("data_source"),
        "quotes_as_of": quotes_as_of,
        "chain_fetched_at": proposal.get("chain_fetched_at"),
        "market_session": proposal.get("market_session"),
        "quote_age_seconds": _age_seconds(quotes_as_of, now=now),
        "chain_age_seconds": _age_seconds(proposal.get("chain_fetched_at"), now=now),
        "credit_basis": proposal.get("credit_basis"),
        "executable_credit": proposal.get("executable_credit"),
        "collateral_required": collateral,
        "buying_power": buying_power,
        "buying_power_as_of": buying_power_as_of,
    }


def build_intent(
    account_key: str,
    proposal: dict,
    *,
    held_qty: float | None = None,
    buying_power: float | None = None,
    buying_power_as_of: str | None = None,
    now=None,
) -> "OrderIntent":
    from brokers.order_intent import (
        OrderIntent, Instrument, Direction, EntrySpec, EntryMethod,
        Quantity, TIF, SessionPolicy, IntentMeta, AssetType, OptionLeg, SpreadType,
    )
    strategy = proposal.get("strategy") or "covered_call"
    sym = proposal.get("underlying") or proposal.get("symbol")
    from scripts.lib import options_workflow as wf
    contracts = wf.quantity(proposal.get("contracts", 1))
    if account_key != proposal.get("account"):
        raise ValueError("Selected account differs from proposal account")
    premium = wf.number(proposal.get("premium"))
    if premium is None or premium <= 0:
        raise ValueError("Positive finite limit required")
    canonical = wf.proposal_legs(proposal)
    legs = [OptionLeg(sym, l["option_type"], l["strike"], l["expiration"], l["side"], l["quantity"]).to_dict()
            for l in canonical]
    notional = premium * (wf.number(canonical[0].get("multiplier")) or 0) * contracts
    spread_w = None
    if strategy == "credit_spread" and proposal.get("short_strike") and proposal.get("long_strike"):
        spread_w = abs(float(proposal["short_strike"]) - float(proposal["long_strike"])) / max(float(proposal["short_strike"]), 1) * 100
    meta = IntentMeta(
        strategy_id=OPTIONS_EXECUTION_MARKER,
        created_by="operator",
        thesis=f"Options {strategy} on {sym}",
        signal_evidence={
            "strategy": strategy,
            "order_type": "NET_CREDIT" if strategy == "credit_spread" else "LIMIT",
            "contracts": contracts,
            "notional_usd": notional,
            "spread_width_pct": spread_w,
            "held_qty": held_qty,
            "proposal_id": proposal.get("id"),
            "short_strike": proposal.get("short_strike"),
            "long_strike": proposal.get("long_strike"),
            "limit_price": premium,
            "option_type": proposal.get("option_type", "put" if strategy == "credit_spread" else "call"),
            "expiration": proposal.get("expiration"),
            **authorization_evidence(proposal, buying_power=buying_power, buying_power_as_of=buying_power_as_of, now=now),
        },
    )
    direction = Direction.SHORT if strategy in ("covered_call", "cash_secured_put", "credit_spread") else Direction.LONG
    return OrderIntent(
        instrument=Instrument(
            symbol=sym.upper(),
            asset_type=AssetType.OPTION,
            option_legs=legs,
            spread_type=SpreadType.CREDIT_SPREAD if strategy == "credit_spread" else SpreadType.SINGLE,
        ),
        direction=direction,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=premium),
        quantity=Quantity(contracts=contracts),
        broker="schwab",
        account_key=account_key,
        tif=TIF(proposal.get("tif", "DAY")),
        session=SessionPolicy.NORMAL,
        meta=meta,
        intent_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
    )


def build_order_spec(proposal: dict) -> dict:
    from scripts.lib import options_workflow as wf
    legs = wf.proposal_legs(proposal)
    tif = proposal.get("tif", "DAY")
    price = wf.number(proposal.get("premium"))
    if tif not in wf.TIME_IN_FORCE or price is None or price <= 0:
        raise ValueError("Supported time in force and positive finite limit required")
    if Decimal(str(price)) != Decimal(str(price)).quantize(Decimal("0.01")):
        raise ValueError("Limit must be an exact cent amount; review a representable price")
    order_type = ("NET_CREDIT" if proposal["strategy"] == "credit_spread" else "NET_DEBIT") if len(legs) > 1 else "LIMIT"
    return {"session": "NORMAL", "duration": tif, "orderType": order_type,
            "price": str(Decimal(str(price)).quantize(Decimal("0.01"))), "orderStrategyType": "SINGLE",
            "orderLegCollection": [{"instruction": l["side"] + "_TO_OPEN", "quantity": l["quantity"],
                "instrument": {"symbol": _occ_symbol(l["symbol"], l["expiration"], l["option_type"], l["strike"]),
                               "assetType": "OPTION"}} for l in legs]}


def request_2fa(intent) -> dict:
    from brokers import approval_service
    return approval_service.request_approval(intent)


def submit(account_key: str, order_spec: dict, intent, *, buying_power_reader=None) -> dict:
    """The submit boundary. Buying power is re-read HERE too (the second read the proof
    document listed as the remaining gap): place_order's own readiness pass reads it from the
    intent's evidence, so the number it sees is from this call, not from confirm seconds
    earlier. A failed read leaves it None and readiness fails closed."""
    import schwab_transport
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    bp, as_of = read_buying_power(account_key, reader=buying_power_reader)
    ev["buying_power"], ev["buying_power_as_of"] = bp, as_of
    ev["buying_power_read_at"] = "submit"
    return schwab_transport.place_order(account_key, order_spec, intent, kind="options")


def load_intent(intent_id: str):
    from db_adapter import _get_conn
    from brokers.order_intent import OrderIntent
    cur = _get_conn().cursor()
    cur.execute("SELECT intent_json FROM broker_order_intents WHERE intent_id=%s", (str(intent_id),))
    r = cur.fetchone()
    if not r or not r[0]:
        return None
    import json
    payload = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    intent = OrderIntent.from_dict(payload)
    if getattr(getattr(intent, "meta", None), "strategy_id", None) != OPTIONS_EXECUTION_MARKER:
        return None
    return intent


def order_from_intent(intent) -> dict:
    """The broker order built ONLY from the intent the operator 2FA'd: its legs, contracts and
    limit price. The proposals cache is never consulted here (2026-09-27: it used to be
    overlaid on top of the intent, so a leg or premium changed in the cache after preflight
    became the order). Strategy, expiration and option type also come from the intent's legs."""
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    legs = list(intent.instrument.option_legs or [])
    if not legs:
        raise ValueError("intent carries no option legs")
    sells = [l for l in legs if str(l.get("side") or "").upper() == "SELL"]
    buys = [l for l in legs if str(l.get("side") or "").upper() == "BUY"]
    strategy = str(ev.get("strategy") or ("credit_spread" if sells and buys else "covered_call"))
    proposal = {
        "strategy": strategy,
        "underlying": intent.instrument.symbol,
        "symbol": intent.instrument.symbol,
        "expiration": legs[0].get("expiration"),
        "option_type": legs[0].get("option_type", "call"),
        "strike": legs[0].get("strike"),
        "short_strike": (sells[0].get("strike") if sells else legs[0].get("strike")),
        "long_strike": (buys[0].get("strike") if (sells and buys) else None),
        "contracts": int(intent.quantity.contracts or 1),
        "premium": float(intent.entry.limit_price or 0),
        "tif": getattr(intent.tif, "value", intent.tif),
        "legs": [{**l, "ratio": l["quantity"] // int(intent.quantity.contracts or 1)} for l in legs],
    }
    return build_order_spec(proposal)


def spec_from_intent(intent) -> dict:
    """Kept for callers; identical to order_from_intent (no cache overlay)."""
    return order_from_intent(intent)


def read_buying_power(account_key: str, *, reader=None) -> tuple[float | None, str | None]:
    """(buying_power, as_of ISO) from the broker account read, or (None, None) when the
    read fails or the account is degraded -- absence fails closed downstream."""
    import datetime as _dt
    try:
        if reader is None:
            import schwab_transport
            reader = schwab_transport.get_account
        acct = reader(account_key) or {}
        if str(acct.get("status") or "") not in ("active", "ok", ""):
            return None, None
        bp = acct.get("buying_power")
        if bp is None:
            return None, None
        return float(bp), _dt.datetime.now(_dt.timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return None, None


def bind_options_authorization(intent, order_spec: dict, *, readiness: dict) -> dict:
    """Evidence-bound approval for THIS options order: the exact order spec hash, the
    submit-mode readiness hash and the intent's authorization evidence. Called after the
    operator's 2FA is fully approved and before submit, so schwab_transport.place_order's
    revalidate_before_submit has something to compare against (until 2026-09-27 the
    options path never created one, so every options submit failed closed)."""
    from brokers.evidence_approval import create_order_evidence_approval
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    quote = None
    if ev.get("limit_price") is not None:
        quote = {"price": ev.get("limit_price"), "mid": ev.get("limit_price"), "symbol": intent.instrument.symbol,
                 "quotes_as_of": ev.get("quotes_as_of"), "credit_basis": ev.get("credit_basis")}
    return create_order_evidence_approval(intent, order_spec, readiness_snapshot=readiness, quote_snapshot=quote)

def _limit_tolerance_pct() -> float:
    """The desk's own validate tolerance for a premium move (options_validate settings)."""
    try:
        try:
            from lib.options_validate import settings as _vs
        except ImportError:
            from scripts.lib.options_validate import settings as _vs  # type: ignore
        try:
            import options_desk_enterprise as ent
            cfg = ent.load_desk_config()
        except Exception:  # noqa: BLE001
            cfg = None
        return float(_vs(cfg)["max_premium_change_pct"])
    except Exception:  # noqa: BLE001
        return 10.0


def _default_proposal_loader(proposal_id: str):
    """The proposal the desk holds now: the engine cache first, then the approval-queue row."""
    try:
        import options_engine as oe
        cached = oe._load_json(oe.PROPOSALS_CACHE)
        for p in cached.get("proposals") or []:
            if p.get("id") == proposal_id:
                return p
    except Exception:  # noqa: BLE001
        pass
    try:
        import options_desk_enterprise as ent
        row = ent._fetch_queue_row(proposal_id) or {}
        pj = row.get("proposal_json")
        if isinstance(pj, str):
            import json as _json
            pj = _json.loads(pj)
        return pj if isinstance(pj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def confirm_authorization(intent, *, now=None, buying_power_reader=None, proposal_loader=None,
                          desk_gate=None, readiness_fn=None, bind_fn=None, workflow_gate=None) -> dict:
    """Order-authorization contract, run AFTER the operator's 2FA is fully approved and BEFORE
    submit (2026-09-27). Refuses, all reasons listed, when:
      * the proposal the desk holds now is missing, or its version (pin) differs from the one
        the intent was built from                                (proposal_version_changed)
      * the desk preflight gate refuses it now (archived thesis, legs/GUID changed vs the
        desk approval pin, stale validation, liquidity, hard-risk blocks in submit mode)
      * buying power cannot be re-read now, is stale, or is below the collateral
      * submit-mode execution readiness is not ok (2FA, kill switch, freshness recomputed
        from the intent's timestamps, LLM cannot unlock, ...)
      * the evidence-bound approval for the EXACT order (spec hash + readiness hash) cannot
        be created
    Returns {"ok", "stage", "refusals", "order_spec", "readiness", "evidence"}. Never submits.
    """
    import datetime as _dt
    now = now or _dt.datetime.now(_dt.timezone.utc)
    ev = (getattr(getattr(intent, "meta", None), "signal_evidence", None) or {})
    refusals: list[dict] = []
    proposal_id = ev.get("proposal_id")
    proposal = (proposal_loader or _default_proposal_loader)(proposal_id) if proposal_id else None
    # Existing per-order approval is the sole authentication process. This
    # options-only gate refreshes account truth then all quotes AFTER 2FA.
    if proposal is not None:
        try:
            from scripts.lib.options_workflow_service import final_validation
            final = (workflow_gate or final_validation)(intent, proposal)
            if not final.get("ok"):
                return {**final, "ok": False, "broker_submitted": False}
            proposal = final.get("proposal") or proposal
        except Exception as exc:
            refusals.append({"code": "final_validation_unavailable", "reason": str(exc)[:160]})
    if not proposal_id:
        refusals.append({"code": "proposal_id_missing", "reason": "intent carries no proposal_id"})
    elif proposal is None:
        refusals.append({"code": "proposal_missing", "reason": f"proposal {proposal_id} is no longer on the desk"})
    else:
        cur_pin = (proposal.get("options_thesis") or {}).get("pin") or proposal.get("thesis_version_at_decision")
        if ev.get("proposal_pin") and cur_pin != ev.get("proposal_pin"):
            refusals.append({"code": "proposal_version_changed",
                             "reason": f"proposal version {cur_pin} differs from the approved {ev.get('proposal_pin')}",
                             "approved": ev.get("proposal_pin"), "current": cur_pin})
        # Quantity and limit: the ORDER is built from the intent, so a drift on the desk cannot
        # change what is sent -- but it means the operator approved a different trade than the
        # desk now prices, so it must be re-approved.
        try:
            cur_qty = int(proposal.get("contracts") or 1)
        except (TypeError, ValueError):
            cur_qty = None
        if cur_qty is not None and cur_qty != int(intent.quantity.contracts or 1):
            refusals.append({"code": "quantity_changed",
                             "reason": f"desk now sizes {cur_qty} contract(s); approved {int(intent.quantity.contracts or 1)}",
                             "approved": int(intent.quantity.contracts or 1), "current": cur_qty})
        cur_limit = (proposal.get("premium") if proposal.get("workflow_version") else
                     proposal.get("executable_credit") if proposal.get("executable_credit") is not None else proposal.get("premium"))
        approved_limit = ev.get("limit_price", getattr(getattr(intent, "entry", None), "limit_price", None))
        try:
            tol_pct = float(_limit_tolerance_pct())
            if cur_limit is not None and approved_limit:
                drift = abs(float(cur_limit) - float(approved_limit)) / abs(float(approved_limit)) * 100.0
                if drift > tol_pct:
                    refusals.append({"code": "limit_changed",
                                     "reason": (f"desk now prices {float(cur_limit):g} vs approved limit {float(approved_limit):g} "
                                                f"({drift:+.1f}% > {tol_pct:g}%); re-approve"),
                                     "approved": approved_limit, "current": cur_limit, "tolerance_pct": tol_pct})
        except (TypeError, ValueError):
            refusals.append({"code": "limit_unknown", "reason": "cannot compare the desk's price with the approved limit"})
        try:
            if desk_gate is None:
                import options_desk_enterprise as ent
                desk_gate = ent.preflight_desk_gate
            gate = desk_gate(proposal_id, proposal, now=now)
            for r in gate.get("refusals") or []:
                refusals.append(dict(r))
        except Exception as e:  # noqa: BLE001 -- a gate that cannot run refuses
            refusals.append({"code": "desk_gate_unavailable", "reason": f"desk preflight gate unavailable ({type(e).__name__})"})
    # Buying power is re-read NOW (the broker's number, not the preflight's).
    bp, bp_as_of = read_buying_power(intent.account_key, reader=buying_power_reader)
    ev["buying_power"], ev["buying_power_as_of"] = bp, bp_as_of
    readiness = None
    try:
        if readiness_fn is None:
            from brokers.execution_readiness import evaluate_execution_readiness as readiness_fn
        readiness = readiness_fn(
            {"intent_id": intent.intent_id, "correlation_id": intent.correlation_id,
             "account_key": intent.account_key, "signal_evidence": ev},
            asset_class="option", broker="schwab", account_key=intent.account_key, mode="submit",
        )
        if not readiness.get("ok"):
            for b in readiness.get("hard_blocks") or []:
                refusals.append({"code": b.get("code"), "reason": b.get("reason"), "source": "execution_readiness"})
    except Exception as e:  # noqa: BLE001
        refusals.append({"code": "readiness_unavailable", "reason": f"execution readiness unavailable ({type(e).__name__})"})
    order_spec = None
    try:
        order_spec = order_from_intent(intent)
    except Exception as e:  # noqa: BLE001
        refusals.append({"code": "order_spec_unavailable", "reason": f"cannot build the order from the intent ({e})"})
    evidence = None
    if not refusals and order_spec is not None and readiness is not None:
        try:
            evidence = (bind_fn or bind_options_authorization)(intent, order_spec, readiness=readiness)
            if not evidence.get("ok"):
                refusals.append({"code": "evidence_approval_failed",
                                 "reason": str(evidence.get("error") or evidence.get("reason") or "unbound")})
        except Exception as e:  # noqa: BLE001
            refusals.append({"code": "evidence_approval_failed", "reason": f"{type(e).__name__}: {str(e)[:120]}"})
    return {"ok": not refusals, "stage": "authorization", "refusals": refusals, "order_spec": order_spec,
            "readiness": {k: readiness.get(k) for k in ("ok", "mode", "evidence_hash", "hard_blocks")} if readiness else None,
            "evidence": {k: evidence.get(k) for k in ("ok", "approval_id", "evidence_hash", "order_spec_hash", "existing")} if evidence else None,
            "checked_at": now.isoformat()}

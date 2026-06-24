#!/usr/bin/env python3
"""broker_promote_sizing.py — account-aware sizing + market validation for paper→broker promote.

Re-runs account_policy.compute_sizing() for the destination account (not the paper source),
applies strategy live_trade_rules ceilings, optional cash cap, and validate_paper_proposal_live_market().
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import account_policy as ap
from db_adapter import _get_conn

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Recommended live defaults (seeded via migrate_schwab_live_policies.py when unset).
SCHWAB_LIVE_POLICY_DEFAULTS = {
    "sizing_engine": "percent_equity",
    "risk_per_trade_pct": 0.5,
    "max_position_allocation_pct": 3.0,
    "daily_loss_pause_pct": 2.0,
}


def _load_shared_risk_rules() -> dict:
    import yaml
    path = PROJECT_ROOT / "config" / "strategies" / "shared_risk_rules.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _load_strategy_config(strategy_id: str) -> dict:
    try:
        from strategy_config_loader import load_strategy_config
        return load_strategy_config(strategy_id) or {}
    except Exception:
        return {}


def effective_policy_for_broker(account_key: str, strategy_id: str,
                                shared_rules: dict | None = None) -> dict:
    """Merge account automation policy with strategy live_trade_rules absolute ceilings."""
    shared_rules = shared_rules or _load_shared_risk_rules()
    policy = dict(ap.load_policy(account_key))
    strategy_cfg = _load_strategy_config(strategy_id)
    live_rules = strategy_cfg.get("live_trade_rules") or {}
    risk_limits = (shared_rules or {}).get("risk_limits") or {}
    default_risk = float(risk_limits.get("default_risk_per_trade", ap.FALLBACK_RISK_DOLLARS))

    acct_l = (account_key or "").lower()
    if acct_l.startswith("schwab") or acct_l.startswith("fidelity"):
        if policy.get("risk_per_trade_pct") is None:
            policy["risk_per_trade_pct"] = SCHWAB_LIVE_POLICY_DEFAULTS["risk_per_trade_pct"]
        if policy.get("max_position_allocation_pct") is None:
            policy["max_position_allocation_pct"] = SCHWAB_LIVE_POLICY_DEFAULTS["max_position_allocation_pct"]
        if not policy.get("sizing_engine"):
            policy["sizing_engine"] = SCHWAB_LIVE_POLICY_DEFAULTS["sizing_engine"]

    max_pos = live_rules.get("max_position_size")
    max_risk = live_rules.get("max_dollar_risk")
    if max_pos is not None:
        cur = policy.get("max_notional_per_trade")
        policy["max_notional_per_trade"] = min(float(cur), float(max_pos)) if cur else float(max_pos)
    if max_risk is not None:
        cur = policy.get("max_risk_dollars_per_trade")
        ceiling = min(float(max_risk), default_risk)
        policy["max_risk_dollars_per_trade"] = min(float(cur), ceiling) if cur else ceiling

    policy["strategy_id"] = strategy_id
    policy["strategy_live_rules"] = {
        "max_position_size": max_pos,
        "max_dollar_risk": max_risk,
    }
    return policy


def _is_live_broker_account(account_key: str) -> bool:
    low = (account_key or "").lower()
    return low.startswith("schwab") or low.startswith("fidelity")


def account_activity_snapshot(account_key: str) -> dict:
    """Cash/equity + open positions + new trades today for broker account selection."""
    key = (account_key or "").strip()
    equity, eq_src = ap.equity_for_account(key)
    cash, cash_src = ap.cash_for_account(key)
    policy = ap.load_policy(key)
    open_count = new_today = proposals_today = 0
    try:
        cur = _get_conn().cursor()
        cur.execute(
            """SELECT COUNT(*) FROM paper_trades
               WHERE status='open'
                 AND COALESCE(target_account, account, execution_account) = %s""",
            (key,),
        )
        open_count = int(cur.fetchone()[0] or 0)
        cur.execute(
            """SELECT COUNT(*) FROM paper_trades
               WHERE COALESCE(target_account, account, execution_account) = %s
                 AND status IN ('open', 'closed', 'pending')
                 AND COALESCE(entry_time, created_at)::date = CURRENT_DATE""",
            (key,),
        )
        new_today = int(cur.fetchone()[0] or 0)
        cur.execute(
            """SELECT COUNT(*) FROM paper_trade_proposals
               WHERE COALESCE(target_account, proposed_account, intended_broker) = %s
                 AND created_at::date = CURRENT_DATE
                 AND status NOT IN ('EXPIRED', 'REJECTED', 'CANCELLED')""",
            (key,),
        )
        proposals_today = int(cur.fetchone()[0] or 0)
    except Exception:
        pass

    max_new = policy.get("max_new_positions_per_day")
    max_conc = policy.get("max_concurrent_positions")
    try:
        max_new_i = int(max_new) if max_new is not None else None
    except (TypeError, ValueError):
        max_new_i = None
    try:
        max_conc_i = int(max_conc) if max_conc is not None else None
    except (TypeError, ValueError):
        max_conc_i = None

    slots_used = max(new_today, proposals_today)
    remaining_new = (max_new_i - slots_used) if max_new_i is not None else None
    remaining_conc = (max_conc_i - open_count) if max_conc_i is not None else None

    return {
        "account_key": key,
        "equity": round(equity, 2) if equity else None,
        "equity_source": eq_src,
        "cash": round(cash, 2) if cash else None,
        "cash_source": cash_src,
        "open_trades": open_count,
        "new_trades_today": new_today,
        "proposals_today": proposals_today,
        "slots_used_today": slots_used,
        "max_new_positions_per_day": max_new_i,
        "max_concurrent_positions": max_conc_i,
        "remaining_new_today": remaining_new,
        "remaining_concurrent": remaining_conc,
        "daily_limit_reached": remaining_new is not None and remaining_new <= 0,
        "concurrent_limit_reached": remaining_conc is not None and remaining_conc <= 0,
    }


def compute_broker_sizing(
    account_key: str,
    strategy_id: str,
    entry: float,
    stop: float,
    *,
    desired_shares: int | None = None,
    shared_rules: dict | None = None,
) -> dict:
    """Max allowed shares for a broker promote. Live accounts size on cash, not equity."""
    policy = effective_policy_for_broker(account_key, strategy_id, shared_rules)
    equity, eq_src = ap.equity_for_account(account_key)
    cash, cash_src = ap.cash_for_account(account_key)
    activity = account_activity_snapshot(account_key)

    sizing_base = None
    if _is_live_broker_account(account_key) and cash and cash > 0:
        sizing_base = cash

    sizing = ap.compute_sizing(
        policy, equity, entry, stop,
        desired_shares=desired_shares, tilt=1.0,
        cash_available=cash,
        sizing_base=sizing_base,
    )
    sizing["equity_source"] = eq_src
    sizing["cash_available"] = round(cash, 2) if cash else None
    sizing["cash_source"] = cash_src
    sizing["account_key"] = account_key
    sizing["strategy_id"] = strategy_id
    sizing["account_activity"] = activity
    sizing["policy_snapshot"] = {
        "sizing_engine": policy.get("sizing_engine"),
        "risk_per_trade_pct": policy.get("risk_per_trade_pct"),
        "max_position_allocation_pct": policy.get("max_position_allocation_pct"),
        "max_risk_dollars_per_trade": policy.get("max_risk_dollars_per_trade"),
        "max_notional_per_trade": policy.get("max_notional_per_trade"),
        "strategy_live_rules": policy.get("strategy_live_rules"),
        "sizing_base_label": sizing.get("sizing_base_label"),
    }
    if desired_shares and int(desired_shares) > sizing.get("shares", 0):
        sizing["oversized"] = True
        sizing["requested_shares"] = int(desired_shares)
    else:
        sizing["oversized"] = False
    return sizing


def _quote_dict_from_payload(quote: dict | None) -> dict:
    if not quote:
        return {}
    last = quote.get("last_price") or quote.get("last")
    return {
        "last_price": last,
        "bid": quote.get("bid"),
        "ask": quote.get("ask"),
        "spread_pct": quote.get("spread_pct"),
        "quote_timestamp": quote.get("quote_timestamp") or datetime.now(timezone.utc).isoformat(),
        "provider": quote.get("provider"),
    }


def build_trade_packet(
    account_key: str,
    symbol: str,
    strategy_id: str,
    entry: float,
    stop: float,
    target: float,
    shares: int,
    *,
    quote: dict | None = None,
    proposal_id: int | None = None,
) -> dict:
    """Operator-facing trade summary for pre-2FA review and approval screens."""
    entry, stop, target = float(entry), float(stop), float(target)
    shares = int(shares)
    risk_ps = max(entry - stop, 0)
    reward_ps = max(target - entry, 0)
    dollar_risk = round(risk_ps * shares, 2) if shares and risk_ps else 0
    dollar_size = round(entry * shares, 2) if shares and entry else 0
    profit = round(reward_ps * shares, 2) if shares and reward_ps > 0 else 0
    rr = round(reward_ps / risk_ps, 2) if risk_ps > 0 and reward_ps > 0 else None
    cash, cash_src = ap.cash_for_account(account_key)
    return {
        "proposal_id": proposal_id,
        "symbol": str(symbol or "").upper(),
        "account": account_key,
        "strategy_id": strategy_id,
        "shares": shares,
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "dollar_risk": dollar_risk,
        "dollar_size": dollar_size,
        "profit_at_target": profit,
        "risk_reward": rr,
        "risk_per_share": round(risk_ps, 4),
        "cash_available": round(cash, 2) if cash else None,
        "cash_source": cash_src,
        "quote": quote or {},
    }


def evaluate_broker_promote(
    account_key: str,
    strategy_id: str,
    entry: float,
    stop: float,
    target: float,
    shares: int,
    *,
    quote: dict | None = None,
    shared_rules: dict | None = None,
    operator_route: bool = False,
) -> dict:
    """Full pre-save evaluation: sizing caps + live market validation → PASS | WARN | BLOCK.

    operator_route=True (Path B desk): operator-edited size is authoritative — P0/policy/paper-queue
    caps surface as warnings only; hard blocks are invalid plan, zero shares, cash, and market gates.
    """
    from paper_trade_logger import validate_paper_proposal_live_market

    entry, stop, target = float(entry), float(stop), float(target)
    shares = int(shares)
    sizing = compute_broker_sizing(
        account_key, strategy_id, entry, stop,
        desired_shares=shares, shared_rules=shared_rules,
    )
    policy_max_shares = int(sizing.get("shares") or 0)
    max_shares = shares if operator_route else policy_max_shares
    violations: list[str] = []
    warnings: list[str] = []

    dollar_risk = round(abs(entry - stop) * shares, 2)
    dollar_size = round(shares * entry, 2)
    snap = sizing.get("policy_snapshot") or {}
    eff_risk_cap = snap.get("max_risk_dollars_per_trade") or sizing.get("max_dollar_risk")
    eff_size_cap = snap.get("max_notional_per_trade") or sizing.get("max_dollar_size")

    if operator_route:
        if shares < 1:
            violations.append("Shares must be at least 1 for live route")
        if entry <= stop:
            violations.append("Entry must be above stop for a long trade")
        if policy_max_shares < 1:
            warnings.append(f"Policy sizing cap is 0 ({sizing.get('reason', 'SIZE_TOO_SMALL')}) — operator override")
        elif shares > policy_max_shares:
            warnings.append(
                f"Operator {shares:,} sh vs policy cap {policy_max_shares:,} "
                f"(binding={sizing.get('binding')}, engine={sizing.get('engine')})"
            )
        if eff_risk_cap and dollar_risk > float(eff_risk_cap) + 0.01:
            warnings.append(f"Dollar risk ${dollar_risk:,.2f} exceeds policy cap ${float(eff_risk_cap):,.0f}")
        if eff_size_cap and dollar_size > float(eff_size_cap) + 0.01:
            warnings.append(f"Investment ${dollar_size:,.2f} exceeds policy cap ${float(eff_size_cap):,.0f}")
    else:
        if not sizing.get("valid") or policy_max_shares < 1:
            violations.append(f"Sizing invalid: {sizing.get('reason', 'SIZE_TOO_SMALL')}")
        if shares > policy_max_shares:
            violations.append(
                f"Shares {shares:,} exceed max {policy_max_shares:,} "
                f"(binding={sizing.get('binding')}, engine={sizing.get('engine')})"
            )
        if eff_risk_cap and dollar_risk > float(eff_risk_cap) + 0.01:
            violations.append(
                f"Dollar risk ${dollar_risk:,.2f} exceeds cap ${float(eff_risk_cap):,.0f}"
            )
        if eff_size_cap and dollar_size > float(eff_size_cap) + 0.01:
            violations.append(
                f"Investment ${dollar_size:,.2f} exceeds cap ${float(eff_size_cap):,.0f}"
            )

    cash = sizing.get("cash_available")
    if cash and dollar_size > cash + 0.01:
        violations.append(f"Investment ${dollar_size:,.2f} exceeds available cash ${cash:,.2f}")

    activity = sizing.get("account_activity") or {}
    if activity.get("daily_limit_reached"):
        mx = activity.get("max_new_positions_per_day")
        used = activity.get("slots_used_today", 0)
        msg = f"Daily new-trade limit reached ({used}/{mx} today)"
        if operator_route:
            warnings.append(msg)
        else:
            violations.append(msg)
    if activity.get("concurrent_limit_reached"):
        mx = activity.get("max_concurrent_positions")
        open_n = activity.get("open_trades", 0)
        msg = f"Max concurrent positions reached ({open_n}/{mx} open)"
        if operator_route:
            warnings.append(msg)
        else:
            violations.append(msg)

    market = {"ok": False, "blocked": True, "status": "BLOCK", "reason": "no quote"}
    q = _quote_dict_from_payload(quote)
    live_price = q.get("last_price") or entry
    if not q.get("last_price") and q.get("ask"):
        live_price = float(q["ask"])
        q["last_price"] = live_price

    if q.get("last_price"):
        market = validate_paper_proposal_live_market(
            "EVAL", entry, stop, target, shares, q,
        )
        market["status"] = "BLOCK" if market.get("blocked") else (
            "WARN" if market.get("warnings") else "PASS"
        )
    elif violations:
        market["status"] = "BLOCK"
        market["reason"] = market.get("reason") or "Missing live quote for market validation"

    if violations:
        overall = "BLOCK"
    elif market.get("status") == "BLOCK":
        overall = "BLOCK"
    elif market.get("status") == "WARN" or warnings:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "status": overall,
        "allowed": overall != "BLOCK",
        "operator_route": operator_route,
        "sizing": sizing,
        "account_activity": activity,
        "max_shares": max_shares,
        "policy_max_shares": policy_max_shares,
        "recommended_shares": policy_max_shares if not operator_route else shares,
        "dollar_size": dollar_size,
        "dollar_risk": dollar_risk,
        "violations": violations,
        "warnings": warnings,
        "market": {
            "ok": market.get("ok"),
            "blocked": market.get("blocked"),
            "status": market.get("status"),
            "warnings": market.get("warnings") or [],
            "reason": market.get("reason"),
            "checks": market.get("checks") or {},
            "live_price": market.get("live_price"),
        },
    }
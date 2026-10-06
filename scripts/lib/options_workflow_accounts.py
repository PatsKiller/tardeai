"""Account eligibility projection over the existing registry and account snapshots.

Never infer options permission from an account name or aggregate across accounts.
Unknown balances, commitments or permissions leave the account visible and disabled.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.options_workflow import economics, number, refusal, timestamp

_TIERS = {
    "covered": {"covered_call", "protective_put"},
    "long": {"covered_call", "protective_put", "cash_secured_put", "long_call", "long_put", "collar"},
    "spreads": {"covered_call", "protective_put", "cash_secured_put", "long_call", "long_put",
                "collar", "credit_spread", "debit_spread"},
}
_TIERS["short_uncovered"] = _TIERS["spreads"]


def eligibility(p, account, *, now=None, max_age_seconds=120, policy_check=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    key, broker = account.get("account_key"), str(account.get("broker") or "").lower()
    route = "schwab" if broker == "schwab" else "manual" if broker == "fidelity" else "unsupported"
    caps = account.get("capabilities") or {}
    tier = caps.get("options_level")
    allowed = caps.get("options_strategies")
    if allowed is None:
        allowed = _TIERS.get(tier, set())
    verified = caps.get("verified") is True or bool(caps.get("options_level_verified"))
    if not verified or caps.get("verified") is False:
        reasons.append(refusal("permissions_unknown", "Options permissions have not been verified"))
    elif p.get("strategy") not in allowed:
        reasons.append(refusal("strategy_not_permitted", f"Recorded options tier {tier or 'unknown'} does not permit this strategy"))
    if route == "unsupported" or account.get("environment") == "paper":
        reasons.append(refusal("account_unsupported", "This account has no supported live or manual options route"))
    if account.get("is_enabled") is False:
        reasons.append(refusal("account_disabled", "Account is disabled"))
    tif_options = account.get("supported_tif") or []
    if p.get("tif", "DAY") not in tif_options:
        reasons.append(refusal("tif_unsupported", "Selected time in force is not supported for this account and order"))
    snapshot = account.get("resources") or {}
    at = timestamp(snapshot.get("as_of"))
    fresh = at is not None and 0 <= (now - at).total_seconds() <= max_age_seconds
    if not fresh:
        reasons.append(refusal("account_resources_stale", "Account balances and commitments are stale or unknown"))
    if snapshot.get("commitments_complete") is not True:
        reasons.append(refusal("commitments_unknown", "Open positions and pending order commitments are unavailable"))
    try:
        e = economics(p)
    except ValueError as exc:
        e = {}
        reasons.append(refusal("economics_unknown", str(exc)))
    cash, bp = number(snapshot.get("available_cash")), number(snapshot.get("buying_power"))
    shares = number((snapshot.get("uncommitted_shares") or {}).get(p.get("symbol")))
    if shares is None and snapshot.get("positions_complete"):
        shares = 0.0
    required = e.get("capital_required")
    resource = cash if p.get("strategy") == "cash_secured_put" else bp
    if required is not None and required > 0:
        if resource is None:
            reasons.append(refusal("cash_unknown" if p.get("strategy") == "cash_secured_put" else "buying_power_unknown",
                                   "Required available account capital is unknown"))
        elif resource < required:
            reasons.append(refusal("insufficient_cash" if p.get("strategy") == "cash_secured_put" else "insufficient_buying_power",
                                   "This account has insufficient uncommitted capital", required=required, available=resource))
    if e.get("shares_required", 0) > 0 and (shares is None or shares < e["shares_required"]):
        reasons.append(refusal("insufficient_shares", "This account has insufficient uncommitted deliverable shares",
                               required=e["shares_required"], available=shares))
    if policy_check and route == "schwab":
        for why in policy_check(p, account):
            reasons.append(refusal("execution_policy", why))
    return {"account_key": key, "display_name": account.get("display_name") or key,
            "account_type": account.get("account_type") or "unknown", "broker": broker,
            "route": route, "eligible": not reasons, "refusals": reasons, "supported_tif": tif_options,
            "options_level": tier, "permissions_source": "account_capabilities",
            "as_of": snapshot.get("as_of"), "freshness": "fresh" if fresh else "unknown_or_stale",
            "buying_power": bp if fresh else None, "available_cash": cash if fresh else None,
            "uncommitted_shares": shares if fresh else None,
            "capital_required": required, "shares_required": e.get("shares_required"),
            "resource_basis": snapshot.get("basis")}


def policy_refusals(p, account):
    from brokers import options_execution_policy as policy
    legs = p.get("legs") or []
    width = (abs(float(p["short_strike"]) - float(p["long_strike"])) /
             max(float(p["short_strike"]), 1) * 100) if p.get("strategy") == "credit_spread" else None
    _, reasons = policy.evaluate(account_key=account["account_key"], strategy=p["strategy"],
        order_type="NET_CREDIT" if p["strategy"] == "credit_spread" else "LIMIT",
        contracts=p["contracts"], notional_usd=abs(float(p["premium"])) * p["contracts"] * float(legs[0]["multiplier"]),
        spread_width_pct=width, symbol=p.get("symbol"))
    return reasons


def load_accounts(query, *, refresh=False, selected=None):
    """Account catalogue + existing holdings snapshots; refresh only the selected account.

    Reading this function never starts 2FA or calls a broker mutation. Live readers
    are runtime-only and are replaced by fake adapters in engineering tests.
    """
    import json
    from brokers.capability_gate import _caps
    from brokers.capabilities import CAPS
    from lib.canonical_store_registry import production_state_root
    caps = _caps()
    rows = query("""SELECT account_key, display_name, broker, environment, account_type,
                            is_enabled, api_read_enabled, supports_options, last_sync_at
                     FROM broker_accounts ORDER BY display_name""", fetch="all") or []
    try:
        root = production_state_root()
        holding = json.loads((root / "data/portfolios/state/holdings.json").read_text())
    except (OSError, ValueError):
        holding = {}
    summaries = holding.get("account_summaries") or {}
    for row in rows:
        key, broker = row["account_key"], str(row.get("broker") or "").lower()
        row["capabilities"] = caps.get(key, {})
        features = (CAPS.get(broker) or {}).get("features") or {}
        row["supported_tif"] = [t for t in ("DAY", "GTC")
                                if (features.get("tif." + t.lower()) or {}).get("level") in {"native", "composed"}]
        if broker == "fidelity":
            # A manual ticket's choices are instructions to the operator; no API support is implied.
            row["supported_tif"] = ["DAY", "GTC"]
        summary = summaries.get(key) or {}
        row["resources"] = {"as_of": summary.get("as_of") or holding.get("as_of"),
                            "available_cash": summary.get("available_cash"),
                            "buying_power": summary.get("buying_power"),
                            "commitments_complete": False, "basis": "stored holdings; commitments not verified"}
        if refresh and (selected is None or key == selected) and broker == "schwab" and row.get("api_read_enabled"):
            import schwab_transport
            row["resources"] = schwab_transport.get_options_resources(key)
        # Manual-account resources are usable only if the existing snapshot explicitly
        # attests commitments and timing. No inferred permissions or zero reservations.
        if broker == "fidelity" and isinstance(summary.get("options_resources"), dict):
            row["resources"] = summary["options_resources"]
    return rows

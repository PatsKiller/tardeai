"""First-class options identity GUIDs (Slice A — agentic memory acceleration).

Stable UUIDv5 identities for option strategies and contracts so desk proposals,
Hub cards, and proposal_outcome_chain attribution can join the same way
securities join thesis/outcome stores.

Compose from: underlying + right + strike + expiration + venue/account.
Never invents PnL. Never grants broker authority.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

SCHEMA = "OptionsIdentity@v1"
_NS = uuid.NAMESPACE_URL

# Right vocabulary — OCC-style C/P only after normalize.
_CALL = frozenset({"c", "call", "calls", "long_call", "short_call", "covered_call"})
_PUT = frozenset({"p", "put", "puts", "long_put", "short_put", "cash_secured_put", "protective_put"})


def normalize_right(value: Any) -> Optional[str]:
    """Return 'C' or 'P', or None when the right cannot be determined."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _CALL or s.startswith("call"):
        return "C"
    if s in _PUT or s.startswith("put"):
        return "P"
    if s in ("c", "p"):
        return s.upper()
    # option_type may already be C/P
    if s.upper() in ("C", "P"):
        return s.upper()
    return None


def _norm_underlying(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_strike(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value or "").strip()


def _norm_expiration(value: Any) -> str:
    """YYYY-MM-DD when possible; otherwise the stripped raw string."""
    s = str(value or "").strip()
    if not s:
        return ""
    # Accept YYYYMMDD / YYYY-MM-DD / ISO datetime prefix
    digits = re.sub(r"[^0-9]", "", s)[:8]
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return s[:10]


def _norm_venue(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _norm_account(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")[:32]


def contract_guid(
    underlying: Any,
    right: Any,
    strike: Any,
    expiration: Any,
    *,
    venue: Any = "",
) -> Optional[str]:
    """Deterministic identity for one option contract.

    Key: underlying + right(C|P) + strike + expiration + venue.
    Venue defaults empty so the same listed contract shares one GUID across
    accounts; pass venue when the listing is venue-specific.
    """
    und = _norm_underlying(underlying)
    cp = normalize_right(right)
    exp = _norm_expiration(expiration)
    st = _norm_strike(strike)
    if not und or not cp or not exp or not st:
        return None
    ven = _norm_venue(venue)
    key = f"tradeai:options:contract:{und}:{cp}:{st}:{exp}:{ven}"
    return str(uuid.uuid5(_NS, key))


def option_strategy_guid(
    strategy: Any,
    underlying: Any,
    *,
    right: Any = None,
    strike: Any = None,
    expiration: Any = None,
    venue: Any = "",
    account: Any = "",
    legs: Optional[list[dict[str, Any]]] = None,
) -> Optional[str]:
    """Deterministic identity for one options strategy instance on an underlying.

    Single-leg: strategy + underlying + contract key + account + venue.
    Multi-leg: strategy + underlying + sorted leg contract keys + account + venue.
    """
    strat = str(strategy or "").strip().lower().replace(" ", "_")
    und = _norm_underlying(underlying)
    if not strat or not und:
        return None
    ven = _norm_venue(venue)
    acct = _norm_account(account)

    leg_keys: list[str] = []
    if legs:
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            cg = contract_guid(
                leg.get("underlying") or und,
                leg.get("option_type") or leg.get("right") or leg.get("type"),
                leg.get("strike"),
                leg.get("expiration") or expiration,
                venue=leg.get("venue") or venue,
            )
            if cg:
                side = str(leg.get("side") or "").strip().upper()
                leg_keys.append(f"{side}:{cg}" if side else cg)
        leg_keys.sort()

    if not leg_keys:
        cg = contract_guid(und, right, strike, expiration, venue=venue)
        if cg:
            leg_keys = [cg]

    legs_part = ",".join(leg_keys) if leg_keys else "noleg"
    key = f"tradeai:options:strategy:{strat}:{und}:{legs_part}:{acct}:{ven}"
    return str(uuid.uuid5(_NS, key))


def stamp_proposal_identity(proposal: dict[str, Any]) -> dict[str, Any]:
    """Stamp option_strategy_guid + contract_guid onto a desk proposal in place.

    Fail-soft: missing fields leave GUIDs absent (None omitted). Never invents
    strikes/expirations. Idempotent — re-stamping yields the same values.
    """
    if not isinstance(proposal, dict):
        return proposal

    und = proposal.get("underlying") or proposal.get("symbol")
    right = proposal.get("option_type") or proposal.get("right")
    strike = proposal.get("strike")
    # Credit spreads: short leg is the primary contract identity
    if strike is None and proposal.get("short_strike") is not None:
        strike = proposal.get("short_strike")
    expiration = proposal.get("expiration")
    venue = proposal.get("venue") or proposal.get("broker") or ""
    account = proposal.get("account") or ""
    strategy = proposal.get("strategy") or proposal.get("strategy_id")

    legs = proposal.get("legs") if isinstance(proposal.get("legs"), list) else None

    cg = contract_guid(und, right, strike, expiration, venue=venue)
    sg = option_strategy_guid(
        strategy,
        und,
        right=right,
        strike=strike,
        expiration=expiration,
        venue=venue,
        account=account,
        legs=legs,
    )
    if cg:
        proposal["contract_guid"] = cg
    if sg:
        proposal["option_strategy_guid"] = sg
    return proposal


def outcome_attribution_keys(proposal: dict[str, Any] | None) -> dict[str, Any]:
    """Attribution keys for proposal_outcome_chain — GUIDs only, never PnL.

    Safe to call with a partial proposal. Missing GUIDs omit those keys.
    """
    if not isinstance(proposal, dict):
        return {}
    stamped = stamp_proposal_identity(dict(proposal))
    out: dict[str, Any] = {}
    sym = _norm_underlying(stamped.get("symbol") or stamped.get("underlying"))
    if sym:
        out["symbol"] = sym
    sid = stamped.get("strategy") or stamped.get("strategy_id")
    if sid:
        out["strategy_id"] = str(sid).strip().lower()
    if stamped.get("option_strategy_guid"):
        out["option_strategy_guid"] = stamped["option_strategy_guid"]
    if stamped.get("contract_guid"):
        out["contract_guid"] = stamped["contract_guid"]
    return out


__all__ = [
    "SCHEMA",
    "normalize_right",
    "contract_guid",
    "option_strategy_guid",
    "stamp_proposal_identity",
    "outcome_attribution_keys",
]

"""First-class options identity (Slice A, repaired 2026-09-24).

An option CONTRACT is a SECURITY of the underlying's ISSUER. Its GUID is minted
through the root authority, ``scripts.lib.security_identity.security_guid``:

    security_guid(issuer=<issuer_guid of the underlying>,
                  share_class="option",
                  instrument="<C|P>:<strike:.4f>:<YYYY-MM-DD>[:<venue>]")

so the key lives in the existing ``tradeai:security:`` namespace and joins
thesis / outcome stores the same way a share class does. No fifth id prefix
(AGENTS.md §13.4: extend the registered namespace, never clone one).

An option STRATEGY instance is a non-financial graph entity minted through
``ticker_knowledge_graph.entity_guid("strategy", ...)``, keyed on the strategy
id, the underlying, the sorted set of leg contract GUIDs and the account.

Rails (both verified by tests/test_options_identity_memory_20260924.py):

* **Never mint from ticker text.** The issuer comes from the identity registry
  (``identity_registry.lookup_symbol``). No registered issuer -> no contract
  GUID -> no strategy GUID. Nothing is invented.
* **No legs, no strategy.** A proposal with no strike/expiration is not an
  options position (equity scalp rows reach ``outcome_attribution_keys`` with
  only ``symbol`` + ``strategy_id``); it gets no option GUIDs at all.
* **One listed contract, one GUID.** ``venue`` is a true listing venue and
  defaults empty. The broker/account a proposal routes through is NOT a venue;
  the account scopes the strategy instance only.
* ``expiration_guid`` / ``strike_guid`` are deliberately not minted: strike and
  expiration are attributes of the contract key, not entities.

Never invents PnL. Never grants broker authority.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Optional

from scripts.lib.security_identity import security_guid

SCHEMA = "OptionsIdentity@v1"
OPTION_SHARE_CLASS = "option"

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
    digits = re.sub(r"[^0-9]", "", s)[:8]
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return s[:10]


def _norm_venue(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _norm_account(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")[:32]


# ── issuer resolution (lookup only; never mint) ────────────────────────────

def resolve_issuer_guid(underlying: Any, *, registry: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """The underlying's issuer GUID from the identity registry, or None.

    Lookup-only. A ticker with no registered issuer yields None and the caller
    mints nothing — the same rule the rest of the identity spine follows.
    Tests inject ``registry`` (or monkeypatch this function); production reads
    the cached registry document.
    """
    und = _norm_underlying(underlying)
    if not und:
        return None
    try:
        from scripts.lib import identity_registry as reg

        doc = registry if registry is not None else reg.load_cached()
        ent = reg.lookup_symbol(doc, und) or {}
    except Exception:  # noqa: BLE001 — registry unavailable is "unknown", not an error
        return None
    issuer = ent.get("issuer_guid")
    return str(issuer) if issuer else None


def contract_guid(
    underlying: Any,
    right: Any,
    strike: Any,
    expiration: Any,
    *,
    venue: Any = "",
    issuer_guid: Optional[str] = None,
    registry: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Deterministic SECURITY identity for one listed option contract.

    ``security_guid(issuer, share_class="option", instrument="C|P:strike:expiry[:venue]")``.
    Venue defaults empty so the same listed contract shares one GUID whatever
    broker or account routes it. Returns None when any key part is missing or
    the underlying has no registered issuer.
    """
    und = _norm_underlying(underlying)
    cp = normalize_right(right)
    exp = _norm_expiration(expiration)
    st = _norm_strike(strike)
    if not und or not cp or not exp or not st:
        return None
    issuer = issuer_guid or resolve_issuer_guid(und, registry=registry)
    if not issuer:
        return None
    instrument = f"{cp}:{st}:{exp}"
    ven = _norm_venue(venue)
    if ven:
        instrument = f"{instrument}:{ven}"
    return security_guid(issuer=issuer, share_class=OPTION_SHARE_CLASS, instrument=instrument)


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
    issuer_guid: Optional[str] = None,
    registry: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Deterministic graph-entity identity for one options strategy instance.

    ``entity_guid("strategy", "<strategy>|<UND>|<sorted leg contract GUIDs>|<account>")``.
    Single-leg: the one contract. Multi-leg: every leg's contract GUID, sorted,
    each prefixed by its side when given. **No resolvable leg -> None**: a row
    without strike/expiration is not an options position and gets no GUID.
    """
    strat = str(strategy or "").strip().lower().replace(" ", "_")
    und = _norm_underlying(underlying)
    if not strat or not und:
        return None
    issuer = issuer_guid or resolve_issuer_guid(und, registry=registry)
    if not issuer:
        return None

    leg_keys: list[str] = []
    if legs:
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            leg_und = leg.get("underlying") or und
            cg = contract_guid(
                leg_und,
                leg.get("option_type") or leg.get("right") or leg.get("type"),
                leg.get("strike"),
                leg.get("expiration") or expiration,
                venue=leg.get("venue") or venue,
                issuer_guid=issuer if _norm_underlying(leg_und) == und else None,
                registry=registry,
            )
            if cg:
                side = str(leg.get("side") or "").strip().upper()
                leg_keys.append(f"{side}:{cg}" if side else cg)
        leg_keys.sort()

    if not leg_keys:
        cg = contract_guid(und, right, strike, expiration, venue=venue,
                           issuer_guid=issuer, registry=registry)
        if cg:
            leg_keys = [cg]

    if not leg_keys:
        return None

    from scripts.lib.ticker_knowledge_graph import entity_guid

    value = f"{strat}|{und}|{','.join(leg_keys)}|{_norm_account(account)}"
    return entity_guid("strategy", value)


def stamp_proposal_identity(proposal: dict[str, Any], *,
                            registry: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Stamp option_strategy_guid + contract_guid onto a desk proposal in place.

    Fail-soft: missing fields leave GUIDs absent. Never invents strikes,
    expirations or issuers. Idempotent — re-stamping yields the same values.
    The proposal's ``broker`` / ``account`` are routing, not venue.
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
    venue = proposal.get("venue") or ""
    account = proposal.get("account") or ""
    strategy = proposal.get("strategy") or proposal.get("strategy_id")
    issuer = proposal.get("issuer_guid") or None
    legs = proposal.get("legs") if isinstance(proposal.get("legs"), list) else None

    cg = contract_guid(und, right, strike, expiration, venue=venue,
                       issuer_guid=issuer, registry=registry)
    sg = option_strategy_guid(
        strategy, und, right=right, strike=strike, expiration=expiration,
        venue=venue, account=account, legs=legs, issuer_guid=issuer, registry=registry,
    )
    if cg:
        proposal["contract_guid"] = cg
    if sg:
        proposal["option_strategy_guid"] = sg
    return proposal


def outcome_attribution_keys(proposal: dict[str, Any] | None, *,
                             registry: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Attribution keys for proposal_outcome_chain — GUIDs only, never PnL.

    Safe to call with a partial proposal. A row with no contract legs (equity
    scalps carry only symbol + strategy_id) gets symbol/strategy_id and NO
    option GUIDs, so the chain's option columns stay NULL for non-options.
    """
    if not isinstance(proposal, dict):
        return {}
    stamped = stamp_proposal_identity(dict(proposal), registry=registry)
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
    "OPTION_SHARE_CLASS",
    "normalize_right",
    "resolve_issuer_guid",
    "contract_guid",
    "option_strategy_guid",
    "stamp_proposal_identity",
    "outcome_attribution_keys",
]

"""quote_selection_contract.py — one canonical read-only quote-selection envelope.

A deterministic, side-effect-free selection of ONE quote for a requested symbol
from a closed set of candidate providers, with named capability / health /
freshness / entitlement states, a selection reason, a fallback flag + reason,
and an explicit UNAVAILABLE state when no candidate qualifies.

The defect this addresses (cc-header-truth-v2 Phase 2 B): a Finviz cache failure
can leave the header showing a price with no indication that the primary quote
vendor is down, and no way to tell whether the displayed price came from an
eligible alternate or was silently invented. A healthy-looking empty HTTP 200 is
not a quote. Provider eligibility is a property of the *proven* candidate set,
never a name.

Authority: READ_ONLY_ADVISORY. Pure functions. No broker, network, DB,
scheduler, or financial side effect. This tranche implements read-only quote
selection/fallback only — never broker execution failover.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Optional

QUOTE_SELECTION_CONTRACT_VERSION = "QuoteSelection@v1"

# ── Provider capability matrix (data, not prose) ─────────────────────────────
# A provider is usable as a quote source only when its role allows quotes AND
# its entitlement/health/freshness are proven. A broker/account provider is a
# truth source for ITS OWN positions, never a substitute for another broker's
# truth, and never a general quote vendor for symbols it does not hold.
PROVIDER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "finviz": {
        "role": "quote",
        "quote_capable": True,
        "auth_required": True,
        "scope": "universe",
        "default_quote": True,
    },
    "schwab": {
        "role": "broker_account",
        "quote_capable": True,
        "auth_required": True,
        "scope": "own_positions",
        "default_quote": False,
    },
    "alpaca": {
        "role": "broker_account",
        "quote_capable": True,
        "auth_required": True,
        "scope": "own_positions",
        "default_quote": False,
    },
    "moomoo": {
        "role": "data_only",
        "quote_capable": False,
        "auth_required": True,
        "scope": "none",
        "default_quote": False,
    },
    "yahoo_cache": {
        "role": "cached_quote",
        "quote_capable": True,
        "auth_required": False,
        "scope": "universe",
        "read_only_cache": True,
        "default_quote": False,
    },
    "price_cache_nav": {
        "role": "cached_nav",
        "quote_capable": False,
        "auth_required": False,
        "scope": "fund_nav",
        "read_only_cache": True,
        "default_quote": False,
    },
}

# Preferred quote provider: the header's default price source. When it is
# unavailable and an eligible alternate answers, fallback_used is set.
DEFAULT_QUOTE_PROVIDER = "finviz"

# Selection order for fallbacks (after the default provider). Deterministic.
FALLBACK_ORDER = ("yahoo_cache", "schwab", "alpaca")

# Freshness states (operator-facing)
FRESHNESS_CURRENT = "CURRENT"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNAVAILABLE = "UNAVAILABLE"

# Overall status
STATUS_SELECTED = "SELECTED"
STATUS_DEGRADED = "DEGRADED"
STATUS_UNAVAILABLE = "UNAVAILABLE"


def _norm_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def _opt_fnum(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _positive(v: Any) -> Optional[float]:
    return _opt_fnum(v)


def provider_capability(provider: str) -> dict[str, Any]:
    """Capability record for a provider. Unknown names have no capability."""
    return dict(PROVIDER_CAPABILITIES.get(provider, {}))


def candidate_eligibility(
    provider: str,
    *,
    entitlement: Optional[str] = None,
    health: str = "unknown",
    freshness: str = FRESHNESS_UNAVAILABLE,
    value: Any = None,
    authenticated: bool = False,
) -> dict[str, Any]:
    """Evaluate ONE provider candidate for quote selection.

    A candidate is eligible only when ALL of the following hold:
      * the provider's declared capability allows quotes (quote_capable),
      * it is authenticated and entitled (or requires no auth),
      * its health is usable (ok or degraded, never unknown/unavailable),
      * its observation freshness is current or stale (never unavailable),
      * it carries a positive value (never a fabricated price).

    ``moomoo`` is data-only (quote_capable=False): it is never eligible as a
    quote source and never appears as a selectable fallback.
    """
    cap = provider_capability(provider)
    reasons: list[str] = []
    if not cap:
        return {
            "provider": provider,
            "eligible": False,
            "role": "unknown",
            "rejected_reason": "provider_unknown",
            "reasons": ["provider_unknown"],
        }
    if not cap.get("quote_capable"):
        reasons.append(f"role={cap.get('role')}")
    if cap.get("auth_required") and not authenticated:
        reasons.append("unauthenticated")
    if cap.get("auth_required") and entitlement not in ("proven", "ok"):
        reasons.append("unentitled")
    if health not in ("ok", "degraded"):
        reasons.append(f"health={health}")
    if freshness not in (FRESHNESS_CURRENT, FRESHNESS_STALE):
        reasons.append(f"freshness={freshness}")
    if _positive(value) is None:
        reasons.append("no_positive_value")

    eligible = not reasons
    return {
        "provider": provider,
        "role": cap.get("role"),
        "eligible": eligible,
        "rejected_reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "capability": cap,
        "value": _positive(value),
        "health": health,
        "freshness": freshness,
        "entitlement": entitlement,
        "authenticated": authenticated,
    }


def select_quote(
    symbol: Any,
    candidates: Iterable[dict[str, Any]],
    *,
    preferred: str = DEFAULT_QUOTE_PROVIDER,
    market_session: Optional[str] = None,
    fallback_order: tuple[str, ...] = FALLBACK_ORDER,
) -> dict[str, Any]:
    """Deterministically select ONE quote from the eligible candidates.

    Returns a dict with selected provider / value / observation time, the full
    candidate board (eligible and rejected), a deterministic selection reason,
    and ``fallback_used`` + ``fallback_reason``. When no candidate qualifies the
    status is UNAVAILABLE and no price is returned (fail closed).
    """
    sym = _norm_symbol(symbol)

    # Normalize into eligibility records keyed by provider.
    by_provider: dict[str, dict[str, Any]] = {}
    for c in candidates:
        p = str(c.get("provider") or "").strip().lower()
        if not p:
            continue
        rec = candidate_eligibility(
            p,
            entitlement=c.get("entitlement"),
            health=str(c.get("health") or "unknown"),
            freshness=str(c.get("freshness") or FRESHNESS_UNAVAILABLE),
            value=c.get("value"),
            authenticated=bool(c.get("authenticated")),
        )
        # Preserve the candidate's own observation time / source hash.
        rec["observation_time"] = c.get("observation_time")
        rec["source_hash"] = c.get("source_hash")
        by_provider[p] = rec

    # Build the ordered candidate board (preferred first, then fallback order,
    # then any remaining providers in name order).
    order: list[str] = []
    for p in (preferred, *fallback_order):
        if p in by_provider and p not in order:
            order.append(p)
    for p in sorted(by_provider):
        if p not in order:
            order.append(p)

    board = [by_provider[p] for p in order]

    eligible = [r for r in board if r["eligible"]]
    selected: Optional[dict[str, Any]] = None
    selection_reason = "no_eligible_candidate"
    fallback_used = False
    fallback_reason: Optional[str] = None

    # Preferred first, then fallback order.
    if preferred in by_provider and by_provider[preferred]["eligible"]:
        selected = by_provider[preferred]
        selection_reason = f"preferred_provider={preferred}_eligible"
    else:
        for p in fallback_order:
            if p in by_provider and by_provider[p]["eligible"]:
                selected = by_provider[p]
                selection_reason = f"preferred_unavailable_fallback_to={p}"
                fallback_used = True
                pref_rec = by_provider.get(preferred)
                if pref_rec is not None:
                    fallback_reason = f"{preferred} rejected: " + (pref_rec.get("rejected_reason") or "unavailable")
                else:
                    fallback_reason = f"{preferred} not offered as a candidate"
                break

    if selected is None:
        # No eligible candidate: fail closed. Never fabricate a price.
        pref_reason = (
            by_provider.get(preferred, {}).get("rejected_reason") if preferred in by_provider else "not_offered"
        )
        return {
            "contract_version": QUOTE_SELECTION_CONTRACT_VERSION,
            "symbol": sym,
            "market_session": market_session,
            "status": STATUS_UNAVAILABLE,
            "selected_provider": None,
            "selected_value": None,
            "selected_observation_time": None,
            "selection_reason": selection_reason,
            "fallback_used": False,
            "fallback_reason": pref_reason,
            "freshness": FRESHNESS_UNAVAILABLE,
            "quality": "UNAVAILABLE",
            "source_hash": None,
            "candidates": board,
        }

    # Whole-envelope freshness: the selected provider's freshness.
    freshness = selected.get("freshness")
    quality = "DEGRADED" if fallback_used or freshness == FRESHNESS_STALE else "OK"
    status = STATUS_DEGRADED if (fallback_used or freshness == FRESHNESS_STALE) else STATUS_SELECTED

    selected_value = selected.get("value")
    src_hash = selected.get("source_hash")
    if not src_hash and selected_value is not None:
        blob = json.dumps(
            [sym, selected["provider"], selected_value, selected.get("observation_time")],
            sort_keys=True,
            default=str,
        )
        src_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()

    return {
        "contract_version": QUOTE_SELECTION_CONTRACT_VERSION,
        "symbol": sym,
        "market_session": market_session,
        "status": status,
        "selected_provider": selected["provider"],
        "selected_value": selected_value,
        "selected_observation_time": selected.get("observation_time"),
        "selection_reason": selection_reason,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "freshness": freshness,
        "quality": quality,
        "source_hash": src_hash,
        "candidates": board,
    }


def build_quote_selection(
    *,
    symbol: Any,
    candidates: Iterable[dict[str, Any]],
    preferred: str = DEFAULT_QUOTE_PROVIDER,
    market_session: Optional[str] = None,
    fallback_order: tuple[str, ...] = FALLBACK_ORDER,
) -> dict[str, Any]:
    """Convenience wrapper: same as select_quote (kept for clarity of naming)."""
    return select_quote(
        symbol,
        candidates,
        preferred=preferred,
        market_session=market_session,
        fallback_order=fallback_order,
    )


# Map a top-level repricer ``reprice_source`` string to a provider name + a
# freshness state. The repricer only ever writes ``finviz_live`` /
# ``finviz_afterhours`` at the top level; per-row fallback is captured in
# ``price_source`` counts, not here.
_REPRICE_SOURCE_MAP = {
    "finviz_live": ("finviz", FRESHNESS_CURRENT),
    "finviz_afterhours": ("finviz", FRESHNESS_CURRENT),
    "finviz": ("finviz", FRESHNESS_CURRENT),
    "yahoo_cache_fallback": ("yahoo_cache", FRESHNESS_STALE),
    "yahoo_cache": ("yahoo_cache", FRESHNESS_STALE),
    "market_quotes": ("schwab", FRESHNESS_STALE),
    "schwab": ("schwab", FRESHNESS_STALE),
}

# Per-row source strings that are NOT the primary quote vendor (a fallback).
_FALLBACK_SOURCE_HINTS = (
    "yahoo_cache_fallback",
    "yahoo",
    "market_quotes",
    "price_cache_nav",
    "proxy_public_ticker",
)


def project_quote_selection(
    *,
    reprice_source: Any = "",
    last_repriced: Any = "",
    source_counts: Optional[dict[str, int]] = None,
    has_any_price: bool = True,
) -> dict[str, Any]:
    """Project the repricer state into a QuoteSelection@v1 summary for a surface.

    This is the *aggregate* projection a header or portfolio surface reads. It
    uses the SAME provider capability matrix as ``select_quote`` (one source of
    truth for provider roles), but it reports what the repricer actually did
    rather than re-selecting: the top-level source, whether a fallback row was
    used, and the eligibility/role of every provider.

    ``has_any_price=False`` (or an empty/missing repricer source) fails closed
    to UNAVAILABLE — never a fabricated price.
    """
    source_counts = source_counts or {}
    primary_provider, primary_freshness = _REPRICE_SOURCE_MAP.get(
        str(reprice_source or "").strip().lower(),
        (str(reprice_source or "").strip().lower() or None, FRESHNESS_UNAVAILABLE),
    )

    # Fallback used when any per-row source is a non-primary fallback hint.
    fallback_rows: dict[str, int] = {}
    for src, n in (source_counts or {}).items():
        s = str(src or "").lower()
        if not s or s in ("finviz", "finviz_elite", "finviz_live", "finviz_afterhours"):
            continue
        fallback_rows[s] = fallback_rows.get(s, 0) + int(n or 0)
    fallback_used = bool(fallback_rows)

    # A missing/empty repricer source means we cannot name the selected vendor.
    if not reprice_source and not source_counts:
        primary_provider = None
        primary_freshness = FRESHNESS_UNAVAILABLE
    if not has_any_price:
        primary_provider = None
        primary_freshness = FRESHNESS_UNAVAILABLE

    # Candidate board from the capability matrix (roles are data, not prose).
    candidates: list[dict[str, Any]] = []
    for provider in ("finviz", "yahoo_cache", "schwab", "alpaca", "moomoo", "price_cache_nav"):
        cap = provider_capability(provider)
        selected = provider == primary_provider
        freshness = primary_freshness if selected else FRESHNESS_UNAVAILABLE
        candidates.append(
            {
                "provider": provider,
                "role": cap.get("role"),
                "quote_capable": cap.get("quote_capable"),
                "scope": cap.get("scope"),
                "auth_required": cap.get("auth_required"),
                "selected": selected,
                "freshness": freshness,
                "used_as_fallback": provider in fallback_rows or (provider == "yahoo_cache" and bool(fallback_rows)),
            }
        )

    # ── coverage (live capture 2026-09-04) ───────────────────────────────────
    # The header rendered "quotes DEGRADED (price_cache_nav(1))" -- something is
    # wrong, and nothing about how much. A degraded aggregate that does not state
    # its coverage lets one fallback row read the same as total vendor failure.
    # source_counts already holds the per-provider symbol tallies; the contract
    # was simply discarding them.
    total_symbols = sum(int(n or 0) for n in source_counts.values()) or None
    degraded_symbols = sum(fallback_rows.values()) or 0

    # A position carrying NO price source at all arrives under the empty key.
    # The first version of this coverage block counted it as covered, so two
    # unpriced positions rendered "100.0% · SELECTED" -- an unpriced holding
    # reading as fully quoted, which is worse than the bare DEGRADED label this
    # replaced. Unpriced is its own class and is never covered.
    unpriced_symbols = sum(int(n or 0) for k, n in source_counts.items() if not str(k or "").strip())
    covered_symbols = None
    if total_symbols is not None:
        covered_symbols = total_symbols - degraded_symbols - unpriced_symbols
    coverage_pct = (
        round(100.0 * covered_symbols / total_symbols, 1) if total_symbols and covered_symbols is not None else None
    )
    # The session the selected observation belongs to, separate from the
    # observation instant itself.
    _obs = str(last_repriced or "").strip()
    session_date = _obs[:10] if len(_obs) >= 10 and _obs[4] == "-" else None

    if primary_provider is None:
        status = STATUS_UNAVAILABLE
        quality = "UNAVAILABLE"
    elif fallback_used or unpriced_symbols:
        status = STATUS_DEGRADED
        quality = "DEGRADED"
    else:
        status = STATUS_SELECTED
        quality = "OK"

    return {
        "contract_version": QUOTE_SELECTION_CONTRACT_VERSION,
        "scope": "aggregate_portfolio_quote",
        "selected_provider": primary_provider,
        "selected_observation_time": str(last_repriced or "") or None,
        "selection_reason": (f"repricer_source={reprice_source}" if reprice_source else "no_repricer_source"),
        "fallback_used": fallback_used,
        "fallback_reason": (
            " · ".join(
                [f"{k}({v})" for k, v in sorted(fallback_rows.items())]
                + ([f"no price source({unpriced_symbols})"] if unpriced_symbols else [])
            )
            or None
        ),
        "freshness": primary_freshness,
        "status": status,
        "quality": quality,
        # ── coverage: never a degraded verdict without its extent ─────────────
        "session_date": session_date,
        "total_symbols": total_symbols,
        "covered_symbols": covered_symbols,
        "degraded_symbol_count": degraded_symbols,
        "unpriced_symbol_count": unpriced_symbols,
        "coverage_pct": coverage_pct,
        "symbols_by_source": {str(k): int(v or 0) for k, v in sorted(source_counts.items()) if k},
        "candidates": candidates,
    }

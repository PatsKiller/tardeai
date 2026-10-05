"""Price-based observation provider for the commitment outcome sweep (tranche 1, 3b).

``commitment_outcome_sweep.sweep_due_commitments`` takes an
``observation_provider(commitment) -> dict``. Its only provider was
``no_observation_provider`` (returns ``{}``), so every due commitment settled
EXPIRED. This one answers from prices:

* subject_guid -> symbol through the identity registry (lookup only);
* close on the commitment's created_at and on its due_at (the resolver's own
  ``ticker_prices`` lookup, injected);
* a direction is read from the commitment's stance (the L3 author's) or, when
  absent, from a directional recommendation word in the claim;
* returns ``{"observed": True, "change_pct": x, "confirmed": bool, ...}`` only
  when BOTH a direction and both prices exist. Otherwise ``{}`` — so
  ``governed_commitment.evaluate_outcome`` says INSUFFICIENT_EVIDENCE / EXPIRED
  truthfully. INSUFFICIENT / ABSTAIN stances are never scored.

Never invents a price, a direction or a result. MBI_BEHAVIOR = 0.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

SCHEMA = "CommitmentPriceObservation@v1"

PriceLookup = Callable[[str, str], Optional[tuple[float, str]]]
SymbolForGuid = Callable[[str], Optional[str]]

BULLISH = frozenset({"BULLISH", "BUY", "ADD", "ACCUMULATE", "LONG", "POSITIVE", "UP"})
BEARISH = frozenset({"BEARISH", "TRIM", "SELL", "SELL_TAXABLE", "REDUCE", "SHORT", "NEGATIVE", "DOWN"})
UNSCORED = frozenset({"INSUFFICIENT", "ABSTAIN", "NEUTRAL", "HOLD", "WAIT", "RECOMMEND", "DISPUTE", ""})

_CLAIM_WORD = re.compile(r"\b(BULLISH|BEARISH|TRIM|SELL|REDUCE|BUY|ADD|ACCUMULATE)\b", re.IGNORECASE)


def direction_of(commitment: Mapping[str, Any]) -> Optional[str]:
    """Only a recorded price-return claim can be scored by this provider.

    A bullish opinion, a revenue forecast or a BUY word is not a price prediction.
    More complex falsifiers need their own deterministic observation provider.
    """
    spec = commitment.get("observation_spec") or {}
    if not isinstance(spec, Mapping) or spec.get("metric") != "close_return_pct" or spec.get("source") != "ticker_prices":
        return None
    if spec.get("operator") not in {">", "<"}:
        return None
    try:
        from math import isfinite
        if not isfinite(float(spec["threshold"])):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return "UP" if spec["operator"] == ">" else "DOWN"


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def default_symbol_for_guid(guid: str) -> Optional[str]:
    """Registry entity -> ticker alias. Lookup only; None when unknown."""
    try:
        from scripts.lib import identity_registry as reg

        ent = (reg.load_cached().get("entities") or {}).get(str(guid)) or {}
        sym = str(ent.get("ticker_alias") or "").strip().upper()
        return sym or None
    except Exception:  # noqa: BLE001
        return None


def make_price_observation_provider(
    *,
    price_lookup: PriceLookup,
    symbol_for_guid: SymbolForGuid | None = None,
    now: datetime | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Build the provider. All lookups injected so the sweep stays hermetic in tests."""
    sym_for = symbol_for_guid or default_symbol_for_guid

    def provider(commitment: Mapping[str, Any]) -> dict[str, Any]:
        direction = direction_of(commitment)
        if direction is None:
            return {}
        guid = str(commitment.get("subject_guid") or "")
        symbol = str(commitment.get("symbol") or "").strip().upper() or (sym_for(guid) if guid else None)
        if not symbol:
            return {}
        start = _parse(commitment.get("created_at") or commitment.get("frozen_at"))
        end = _parse(commitment.get("due_at"))
        at = now or datetime.now(timezone.utc)
        if start is None or end is None:
            return {}
        if end > at:
            return {}  # the forecast horizon has not closed
        p0 = price_lookup(symbol, start.date().isoformat())
        p1 = price_lookup(symbol, end.date().isoformat())
        if not p0 or not p1 or not p0[0]:
            return {}
        change_pct = round((float(p1[0]) / float(p0[0]) - 1.0) * 100.0, 4)
        threshold = float(commitment["observation_spec"]["threshold"])
        confirmed = change_pct > threshold if direction == "UP" else change_pct < threshold
        return {
            "schema": SCHEMA,
            "observed": True,
            "commitment_id": commitment.get("commitment_id"),
            "source_refs": [f"ticker_prices:{symbol}:{p0[1]}", f"ticker_prices:{symbol}:{p1[1]}"],
            "symbol": symbol,
            "direction": direction,
            "price_t0": float(p0[0]), "price_t0_date": p0[1],
            "price_t1": float(p1[0]), "price_t1_date": p1[1],
            "change_pct": change_pct,
            "confirmed": bool(confirmed),
            "refuted": not bool(confirmed),
            "source": "ticker_prices",
            "memory_behavior_influence": 0,
        }

    return provider


__all__ = ["SCHEMA", "direction_of", "make_price_observation_provider", "default_symbol_for_guid"]

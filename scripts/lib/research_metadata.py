"""Provenance-separated research metadata.

Factual tags are accepted only from named deterministic producers. Judgment
tags are vocabulary constrained and remain explicitly LLM-authored.
"""
from __future__ import annotations

from typing import Any

SCHEMA = "ResearchMetadata@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

FACTUAL_FIELDS = frozenset({
    "sector", "industry", "index_memberships", "market_cap_band",
    "liquidity_band", "price", "analyst_rating", "street_mean_target",
    "revision_direction",
})
JUDGMENT_VOCABULARY = {
    "theme": frozenset({
        "AI", "DEFENSE", "ENERGY", "FINANCIALS", "HEALTHCARE", "INDUSTRIALS",
        "CONSUMER", "CYCLICAL", "RATE_SENSITIVE", "COMMODITY", "OTHER",
    }),
    "stance": frozenset({"BULLISH", "BEARISH", "NEUTRAL", "MIXED"}),
    "conviction": frozenset({"LOW", "MEDIUM", "HIGH"}),
    "catalyst_type": frozenset({
        "EARNINGS", "GUIDANCE", "SEC", "FDA_REGULATORY", "M_AND_A",
        "ANALYST_REVISION", "TARGET_REVISION", "MACRO", "SECTOR", "OTHER",
    }),
    "risk_type": frozenset({
        "VALUATION", "EXECUTION", "BALANCE_SHEET", "REGULATORY", "COMPETITION",
        "MACRO", "LIQUIDITY", "TECHNICAL", "CATALYST", "OTHER",
    }),
    "time_horizon": frozenset({"DAYS", "WEEKS", "MONTHS", "YEARS"}),
}


def _band(value: Any, cuts: tuple[tuple[float, str], ...], default: str) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    for upper, label in cuts:
        if number < upper:
            return label
    return default


def market_cap_band(value: Any) -> str | None:
    return _band(value, ((2, "MICRO_SMALL"), (10, "MID"), (200, "LARGE")), "MEGA")


def liquidity_band(avg_dollar_volume: Any) -> str | None:
    return _band(avg_dollar_volume, ((5_000_000, "LOW"), (25_000_000, "MEDIUM")), "HIGH")


def _fact(value: Any, provenance: dict[str, Any], *, derived_from: list[str] | None = None) -> dict[str, Any] | None:
    if value in (None, "", []):
        return None
    source = str(provenance.get("source") or "").strip()
    source_record_id = str(provenance.get("source_record_id") or "").strip()
    if not source or not source_record_id:
        return None
    return {
        "value": value,
        "provenance_class": "FACTUAL",
        "source": source,
        "source_record_id": source_record_id,
        "as_of": provenance.get("as_of"),
        "derived_from": list(derived_from or []),
    }


def build_factual_tags(
    *,
    symbol_profile: dict[str, Any],
    market_data: dict[str, Any],
    analyst_data: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build only facts with deterministic source and record provenance."""
    analyst_data = analyst_data or {}
    out: dict[str, dict[str, Any]] = {}
    profile_prov = dict(symbol_profile.get("provenance") or {})
    market_prov = dict(market_data.get("provenance") or {})
    analyst_prov = dict(analyst_data.get("provenance") or {})

    raw = {
        "sector": _fact(symbol_profile.get("sector"), profile_prov),
        "industry": _fact(symbol_profile.get("industry"), profile_prov),
        "index_memberships": _fact(symbol_profile.get("index_memberships"), profile_prov),
        "price": _fact(market_data.get("price"), market_prov),
        "market_cap_band": _fact(
            market_cap_band(symbol_profile.get("market_cap_b")),
            profile_prov,
            derived_from=["market_cap_b"],
        ),
        "liquidity_band": _fact(
            liquidity_band(market_data.get("avg_dollar_volume")),
            market_prov,
            derived_from=["avg_dollar_volume"],
        ),
        "analyst_rating": _fact(analyst_data.get("analyst_rating"), analyst_prov),
        "street_mean_target": _fact(
            analyst_data.get("street_mean_target") if analyst_data.get("verified_producer") is True else None,
            analyst_prov,
        ),
        "revision_direction": _fact(analyst_data.get("revision_direction"), analyst_prov),
    }
    for key, value in raw.items():
        if value is not None and key in FACTUAL_FIELDS:
            out[key] = value
    return out


def build_judgment_tags(
    raw: dict[str, Any] | None,
    *,
    provider: str,
    model: str,
    research_id: str,
) -> dict[str, Any]:
    """Filter model judgments through the controlled vocabulary."""
    raw = raw or {}
    tags: dict[str, Any] = {}
    rejected: dict[str, Any] = {}
    for field, allowed in JUDGMENT_VOCABULARY.items():
        value = str(raw.get(field) or "").upper().strip()
        if not value:
            continue
        if value in allowed:
            tags[field] = value
        else:
            rejected[field] = value
    entities = []
    for value in raw.get("named_entities") or []:
        item = " ".join(str(value).split())[:120]
        if item and item not in entities:
            entities.append(item)
    if entities:
        tags["named_entities"] = entities[:20]
    return {
        "tags": tags,
        "rejected": rejected,
        "provenance_class": "JUDGMENT",
        "provider": provider,
        "model": model,
        "research_id": research_id,
    }


def build_research_metadata(
    *,
    symbol: str,
    symbol_profile: dict[str, Any],
    market_data: dict[str, Any],
    analyst_data: dict[str, Any] | None,
    judgment: dict[str, Any] | None,
    provider: str,
    model: str,
    research_id: str,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "symbol": symbol.upper(),
        "factual": build_factual_tags(
            symbol_profile=symbol_profile,
            market_data=market_data,
            analyst_data=analyst_data,
        ),
        "judgment": build_judgment_tags(
            judgment,
            provider=provider,
            model=model,
            research_id=research_id,
        ),
        "provenance_classes_mixed": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }

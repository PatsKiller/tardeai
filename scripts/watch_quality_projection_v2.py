#!/usr/bin/env python3
"""Source-hardened read-only Watch quality projection.

This supersedes watch-quality-projection-v1 for rollout evidence. The first
projection correctly proved the policy distribution path, but it also exposed a
legacy naming conflict that must be resolved before any packet rebuild:

* the Finviz enrichment cache calls its market-cap field ``market_cap_b`` even
  though the stored value is already USD millions;
* valuation_supplement_cache.json uses ``market_cap_b`` literally as USD
  billions.

Treating both fields identically inflated many Finviz companies by 1,000x. This
module applies source-specific units, prefers current Watch observations over
stale packet copies, rejects physically implausible cached values, and records
field-level provenance. It then delegates the read-only population census to the
v1 implementation after replacing only its evidence assembler.

No packet, cache, database, provider, schedule, service, model, broker, order,
approval, or 2FA mutation is available here.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import watch_quality_projection as projection_v1

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = "watch-quality-projection-v2"

# Fail-closed sanity bands. Values outside these bands are not repaired or
# clipped; they are removed from admission evidence and surfaced in provenance.
MAX_ABS_MARGIN_PCT = 1_000.0
MAX_ABS_RETURN_PCT = 1_000.0
MAX_OWNERSHIP_PCT = 500.0
MAX_RATIO_ABS = 100_000.0
MAX_MARKET_CAP_M = 50_000_000.0  # $50T, above any plausible listed issuer.
MAX_SHARES_OUT_M = 100_000.0
MARKET_CAP_CROSSCHECK_MULTIPLE = 5.0


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _packet_sources(packet: dict) -> list[dict]:
    return [
        item
        for item in (
            packet.get("facts"),
            packet.get("shadow_facts"),
            packet.get("decision_facts"),
            packet.get("evidence"),
            packet.get("technical_snapshot"),
        )
        if isinstance(item, dict)
    ]


def _pick(
    sources: Iterable[tuple[str, dict]],
    *keys: str,
) -> tuple[Any, str | None, str | None]:
    for source_name, source in sources:
        for key in keys:
            if source.get(key) is not None:
                return source.get(key), source_name, key
    return None, None, None


def _pick_num(
    sources: Iterable[tuple[str, dict]],
    *keys: str,
) -> tuple[float | None, str | None, str | None, Any]:
    raw, source, key = _pick(sources, *keys)
    return _num(raw), source, key, raw


def _cache_timestamp(*sources: dict) -> str | None:
    return _first_text(*(
        source.get(key)
        for source in sources
        for key in ("cached_at", "as_of", "updated_at", "last_updated_at", "timestamp")
    ))


def _age_state(timestamp: str | None) -> str:
    if not timestamp:
        return "UNKNOWN"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_hours = (
            datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        ).total_seconds() / 3600
    except Exception:
        return "UNKNOWN"
    if age_hours <= 36:
        return "PARTIAL"
    if age_hours <= 168:
        return "UNKNOWN"
    return "STALE"


def _accept_numeric(
    field: str,
    value: float | None,
    *,
    source: str | None,
    raw: Any,
    rejected: dict[str, dict],
    minimum: float | None = None,
    maximum: float | None = None,
    abs_maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    invalid = (
        (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
        or (abs_maximum is not None and abs(value) > abs_maximum)
    )
    if invalid:
        rejected[field] = {
            "source": source,
            "raw": raw,
            "reason": "outside source-hardening sanity band",
        }
        return None
    return value


def _market_cap_millions(
    *,
    finviz: dict,
    supplement: dict,
    packet_fundamentals: dict,
    watch_row: dict,
    price: float | None,
    shares_out_m: float | None,
    rejected: dict[str, dict],
    field_sources: dict[str, str],
) -> float | None:
    canonical_sources = (
        ("finviz", finviz),
        ("packet", packet_fundamentals),
        ("watch_row", watch_row),
        ("supplement", supplement),
    )
    value, source, key, raw = _pick_num(
        canonical_sources,
        "market_cap_usd_millions",
        "market_cap_m",
    )

    if value is None:
        # Canonical legacy contract: the Finviz cache suffix is wrong; its value
        # is already millions (for example 67674.87 means roughly $67.7B).
        raw = finviz.get("market_cap_b")
        value = _num(raw)
        if value is not None:
            source, key = "finviz", "market_cap_b_mislabeled_millions"

    if value is None:
        # PR #170's yfinance supplement uses the suffix literally: billions.
        raw = supplement.get("market_cap_b")
        parsed = _num(raw)
        if parsed is not None:
            value = parsed * 1_000.0
            source, key = "supplement", "market_cap_b_true_billions"

    if value is None:
        raw, source, key = _pick(
            canonical_sources,
            "market_cap",
            "marketCap",
        )
        parsed = _num(raw)
        if parsed is not None:
            value = parsed / 1_000_000.0 if parsed > 1_000_000 else parsed

    value = _accept_numeric(
        "market_cap_usd_millions",
        value,
        source=source,
        raw=raw,
        rejected=rejected,
        minimum=0.0,
        maximum=MAX_MARKET_CAP_M,
    )
    if value is None:
        return None

    if price and shares_out_m:
        implied = price * shares_out_m
        if implied > 0:
            multiple = max(value, implied) / min(value, implied)
            if multiple > MARKET_CAP_CROSSCHECK_MULTIPLE:
                rejected["market_cap_usd_millions"] = {
                    "source": source,
                    "raw": raw,
                    "reason": (
                        f"conflicts {multiple:.1f}x with price × shares-outstanding "
                        f"cross-check (${implied:.1f}M)"
                    ),
                }
                return None

    field_sources["market_cap_usd_millions"] = f"{source}:{key}"
    return value


def assemble_projection_facts(
    symbol: str,
    *,
    watch_row: dict | None = None,
    packet: dict | None = None,
    finviz: dict | None = None,
    supplement: dict | None = None,
) -> tuple[dict, dict, dict]:
    """Assemble current, source-aware policy evidence without inventing values."""
    watch_row = _mapping(watch_row)
    packet = _mapping(packet)
    finviz = _mapping(finviz)
    supplement = _mapping(supplement)
    packet_sources = _packet_sources(packet)

    packet_fundamentals: dict = {}
    for source in packet_sources:
        packet_fundamentals.update(_mapping(source.get("fundamentals")))

    rejected: dict[str, dict] = {}
    field_sources: dict[str, str] = {}

    # Current Watch observations are sovereign for current price, float and
    # relative volume. Packet facts remain the preferred source for true-ATR and
    # absolute SMA evidence because the packet producer uses OHLC bars.
    current_sources = (
        ("watch_row", watch_row),
        *[("packet", source) for source in packet_sources],
        ("finviz", finviz),
        ("supplement", supplement),
    )
    technical_sources = (
        *[("packet", source) for source in packet_sources],
        ("watch_row", watch_row),
        ("finviz", finviz),
    )
    fundamental_sources = (
        ("finviz", finviz),
        ("supplement", supplement),
        ("packet", packet_fundamentals),
        ("watch_row", watch_row),
    )

    def take(
        field: str,
        sources: Iterable[tuple[str, dict]],
        *keys: str,
        minimum: float | None = None,
        maximum: float | None = None,
        abs_maximum: float | None = None,
    ) -> float | None:
        value, source, key, raw = _pick_num(sources, *keys)
        value = _accept_numeric(
            field,
            value,
            source=source,
            raw=raw,
            rejected=rejected,
            minimum=minimum,
            maximum=maximum,
            abs_maximum=abs_maximum,
        )
        if value is not None and source and key:
            field_sources[field] = f"{source}:{key}"
        return value

    price = take(
        "price",
        current_sources,
        "price",
        "live_price",
        "enriched_price",
        "current_price",
        "last_price",
        minimum=0.0001,
    )
    float_m = take(
        "float_m",
        current_sources,
        "float_m",
        "float_shares_m",
        "shares_float_m",
        "float_millions",
        minimum=0.0,
        maximum=MAX_SHARES_OUT_M,
    )
    shares_out_m = take(
        "shares_outstanding_m",
        fundamental_sources,
        "shares_outstanding_m",
        "shares_out_m",
        "sharesOutstandingM",
        minimum=0.0,
        maximum=MAX_SHARES_OUT_M,
    )

    fundamentals: dict[str, float | str] = {}
    ratio_aliases = {
        "pe": ("pe", "trailing_pe", "trailingPE"),
        "forward_pe": ("forward_pe", "forwardPE"),
        "peg": ("peg", "peg_ratio", "trailingPegRatio"),
        "pb": ("pb", "price_to_book", "priceToBook"),
        "ps": ("ps", "price_to_sales", "priceToSalesTrailing12Months"),
        "pfcf": ("pfcf", "price_to_fcf"),
        "eps_ttm": ("eps_ttm", "eps", "trailingEps"),
        "total_debt_equity": ("total_debt_equity", "debt_equity", "debtToEquity"),
        "lt_debt_equity": ("lt_debt_equity",),
        "current_ratio": ("current_ratio", "currentRatio"),
        "quick_ratio": ("quick_ratio", "quickRatio"),
        "short_ratio": ("short_ratio",),
    }
    for canonical, keys in ratio_aliases.items():
        value = take(canonical, fundamental_sources, *keys, abs_maximum=MAX_RATIO_ABS)
        if value is not None:
            fundamentals[canonical] = value

    percentage_aliases = {
        "gross_margin_pct": ("gross_margin_pct", "gross_margin", "grossMargins"),
        "oper_margin_pct": ("oper_margin_pct", "operating_margin_pct", "operatingMargins"),
        "profit_margin_pct": ("profit_margin_pct", "profit_margin", "profitMargins"),
        "roe_pct": ("roe_pct", "returnOnEquity"),
        "roa_pct": ("roa_pct", "returnOnAssets"),
        "roic_pct": ("roic_pct", "roic"),
        "eps_past_5y": ("eps_past_5y",),
        "sales_past_5y": ("sales_past_5y",),
        "eps_next_y": ("eps_next_y",),
        "eps_next_5y": ("eps_next_5y",),
        "eps_qoq": ("eps_qoq",),
        "sales_qoq": ("sales_qoq",),
    }
    for canonical, keys in percentage_aliases.items():
        limit = MAX_ABS_MARGIN_PCT if "margin" in canonical else MAX_ABS_RETURN_PCT
        value = take(canonical, fundamental_sources, *keys, abs_maximum=limit)
        if value is not None:
            fundamentals[canonical] = value

    bounded_percentage_aliases = {
        "short_float_pct": ("short_float_pct", "short_float"),
        "insider_own_pct": ("insider_own_pct", "insider_ownership_pct"),
        "inst_own_pct": ("inst_own_pct", "institutional_ownership_pct"),
        "div_yield_pct": ("div_yield_pct", "dividend_yield_pct"),
        "week52_high_pct": ("week52_high_pct",),
        "week52_low_pct": ("week52_low_pct",),
    }
    for canonical, keys in bounded_percentage_aliases.items():
        value = take(canonical, fundamental_sources, *keys, abs_maximum=MAX_OWNERSHIP_PCT)
        if value is not None:
            fundamentals[canonical] = value

    if shares_out_m is not None:
        fundamentals["shares_outstanding_m"] = shares_out_m
    market_cap_m = _market_cap_millions(
        finviz=finviz,
        supplement=supplement,
        packet_fundamentals=packet_fundamentals,
        watch_row=watch_row,
        price=price,
        shares_out_m=shares_out_m,
        rejected=rejected,
        field_sources=field_sources,
    )
    if market_cap_m is not None:
        fundamentals["market_cap_usd_millions"] = market_cap_m

    fundamentals_as_of = _cache_timestamp(finviz, supplement, packet_fundamentals)
    if fundamentals_as_of:
        fundamentals["fundamentals_as_of"] = fundamentals_as_of

    facts = {
        "symbol": symbol,
        "live_price": price,
        "float_m": float_m,
        "atr": take("atr", technical_sources, "atr", "atr_14", "atr14", minimum=0.0),
        "rvol": take("rvol", current_sources, "rvol", "relative_volume", "relative_volume_x", minimum=0.0),
        "rsi": take("rsi", current_sources, "rsi", "rsi14", "rsi_14", minimum=0.0, maximum=100.0),
        "sma50": take("sma50", technical_sources, "sma50", "sma_50", minimum=0.0),
        "short_float_pct": fundamentals.get("short_float_pct"),
        "instrument_type": _first_text(*(
            source.get(key)
            for _, source in current_sources
            for key in ("instrument_type", "asset_type")
        )),
        "quote_type": _first_text(*(
            source.get(key)
            for _, source in current_sources
            for key in ("quote_type", "quoteType")
        )),
        "bars_used": take("bars_used", technical_sources, "bars_used", minimum=0.0),
        "event_state": next((
            source.get("event_state")
            for _, source in technical_sources
            if source.get("event_state") is not None
        ), None),
        "days_to_earnings": take(
            "days_to_earnings",
            technical_sources,
            "days_to_earnings",
            abs_maximum=3650.0,
        ),
        "fundamentals": fundamentals,
    }

    direct_snapshot = _mapping(packet.get("technical_snapshot"))
    direct_freshness = _first_text(
        direct_snapshot.get("overall_freshness"),
        _mapping(packet.get("freshness")).get("overall_state"),
        _mapping(packet.get("current_validity")).get("state"),
    )
    cache_as_of = _cache_timestamp(finviz, supplement, watch_row)
    technical_snapshot = dict(direct_snapshot)
    technical_snapshot["overall_freshness"] = (
        str(direct_freshness).upper() if direct_freshness else _age_state(cache_as_of)
    )

    observed = {
        "price": facts.get("live_price"),
        "float_m": facts.get("float_m"),
        "market_cap_m": fundamentals.get("market_cap_usd_millions"),
        "atr": facts.get("atr"),
        "rvol": facts.get("rvol"),
        "pe": fundamentals.get("pe"),
        "forward_pe": fundamentals.get("forward_pe"),
        "pb": fundamentals.get("pb"),
        "ps": fundamentals.get("ps"),
        "profit_margin_pct": fundamentals.get("profit_margin_pct"),
    }
    provenance = {
        "normalization_contract": CONTRACT,
        "packet_present": bool(packet),
        "finviz_present": bool(finviz),
        "supplement_present": bool(supplement),
        "watch_row_present": bool(watch_row),
        "cache_as_of": cache_as_of,
        "observed_fields": sorted(key for key, value in observed.items() if value is not None),
        "field_sources": dict(sorted(field_sources.items())),
        "rejected_fields": rejected,
        "data_quality_issues": [
            f"{field}: {detail['reason']}"
            for field, detail in sorted(rejected.items())
        ],
    }
    return facts, technical_snapshot, provenance


def main() -> None:
    # Reuse the reviewed forced-read-only transaction, reporting, argument and
    # sanitized-export implementation. Only evidence normalization is replaced.
    projection_v1.CONTRACT = CONTRACT
    projection_v1.assemble_projection_facts = assemble_projection_facts
    projection_v1.main()


if __name__ == "__main__":
    main()

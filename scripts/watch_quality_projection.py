#!/usr/bin/env python3
"""Read-only projected quality admission for the ranked Watch population.

Historical decision packets predate watch-quality-admission-v1, so the ordinary
packet census correctly reports UNASSESSED. This script answers the next bounded
question without rebuilding or modifying a packet:

    Given evidence already present in PostgreSQL and host-local caches, what
    admission state would the current policy assign today?

The projection is intentionally conservative. Missing fields are never invented;
unknown or incomplete evidence produces RESEARCH_ONLY through the policy engine.
No provider, model, HTTP refresh, scheduler, service, or application write is used.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_packet_quality as packet_quality
import watch_quality_policy as quality_policy

STATE_ROOT = PROJECT_ROOT / "data" / "state"
FINVIZ_CACHE = STATE_ROOT / "ticker_enrichment_cache.json"
VALUATION_SUPPLEMENT = STATE_ROOT / "valuation_supplement_cache.json"
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"

CONTRACT = "watch-quality-projection-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    from env_bootstrap import load_env

    load_env()
    from db_adapter import _get_conn

    return _get_conn()


def _load_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text())
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _first_num(*values: Any) -> float | None:
    for value in values:
        parsed = _num(value)
        if parsed is not None:
            return parsed
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _nested_sources(packet: dict) -> list[dict]:
    """Return candidate raw-evidence mappings from most to least specific."""
    candidates = [
        packet.get("facts"),
        packet.get("shadow_facts"),
        packet.get("decision_facts"),
        packet.get("evidence"),
        packet.get("technical_snapshot"),
    ]
    return [_mapping(item) for item in candidates if isinstance(item, dict)]


def _value(sources: Iterable[dict], *keys: str) -> Any:
    for source in sources:
        for key in keys:
            if source.get(key) is not None:
                return source.get(key)
    return None


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
        age_hours = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600
    except Exception:
        return "UNKNOWN"
    if age_hours <= 36:
        return "PARTIAL"
    if age_hours <= 168:
        return "UNKNOWN"
    return "STALE"


def _ranked_population(cur, limit: int) -> list[dict]:
    cur.execute(
        """SELECT upper(symbol) AS symbol, min(hermes_rank) AS rank
             FROM watchlist_items
            WHERE symbol IS NOT NULL
              AND coalesce(status, 'active') IN ('active', 'researched')
            GROUP BY upper(symbol)
            ORDER BY min(hermes_rank) NULLS LAST, upper(symbol)
            LIMIT %s""",
        (limit,),
    )
    ranked = [
        {"symbol": str(symbol), "rank": int(rank) if rank is not None else None}
        for symbol, rank in cur.fetchall()
    ]
    symbols = [row["symbol"] for row in ranked]
    if not symbols:
        return ranked
    cur.execute(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol), to_jsonb(watchlist_items)
             FROM watchlist_items
            WHERE upper(symbol) = ANY(%s)
            ORDER BY upper(symbol), last_seen_at DESC NULLS LAST""",
        (symbols,),
    )
    details = {str(symbol): _mapping(payload) for symbol, payload in cur.fetchall()}
    for row in ranked:
        row["watch_row"] = details.get(row["symbol"], {})
    return ranked


def _latest_packets(cur, symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    cur.execute(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol), generated_at, packet
             FROM decision_packets
            WHERE superseded_by IS NULL AND upper(symbol) = ANY(%s)
            ORDER BY upper(symbol), generated_at DESC""",
        (symbols,),
    )
    return {
        str(symbol): {
            "generated_at": generated_at.isoformat() if generated_at else None,
            "packet": _mapping(packet),
        }
        for symbol, generated_at, packet in cur.fetchall()
    }


def _held_symbols() -> set[str]:
    raw = _load_json(HOLDINGS_PATH)
    rows = raw.get("holdings") if isinstance(raw.get("holdings"), list) else []
    return {
        str(row.get("symbol") or "").upper()
        for row in rows
        if isinstance(row, dict) and row.get("symbol") and not row.get("is_cash")
    }


def assemble_projection_facts(
    symbol: str,
    *,
    watch_row: dict | None = None,
    packet: dict | None = None,
    finviz: dict | None = None,
    supplement: dict | None = None,
) -> tuple[dict, dict, dict]:
    """Assemble policy inputs and return (facts, technical_snapshot, provenance)."""
    watch_row = _mapping(watch_row)
    packet = _mapping(packet)
    finviz = _mapping(finviz)
    supplement = _mapping(supplement)
    packet_sources = _nested_sources(packet)
    sources = [*packet_sources, watch_row, finviz, supplement]

    packet_fundamentals = {}
    for source in packet_sources:
        packet_fundamentals.update(_mapping(source.get("fundamentals")))
    fundamentals_sources = [packet_fundamentals, finviz, supplement, watch_row]

    market_cap_m = _first_num(
        _value(fundamentals_sources, "market_cap_usd_millions", "market_cap_m"),
    )
    if market_cap_m is None:
        market_cap_b = _first_num(_value(fundamentals_sources, "market_cap_b"))
        market_cap_m = market_cap_b * 1000 if market_cap_b is not None else None
    if market_cap_m is None:
        market_cap_raw = _first_num(_value(fundamentals_sources, "market_cap", "marketCap"))
        if market_cap_raw is not None:
            market_cap_m = market_cap_raw / 1_000_000 if market_cap_raw > 1_000_000 else market_cap_raw

    fundamentals = dict(packet_fundamentals)
    aliases = {
        "pe": ("pe", "trailing_pe", "trailingPE"),
        "forward_pe": ("forward_pe", "forwardPE"),
        "peg": ("peg", "peg_ratio", "trailingPegRatio"),
        "pb": ("pb", "price_to_book", "priceToBook"),
        "ps": ("ps", "price_to_sales", "priceToSalesTrailing12Months"),
        "eps_ttm": ("eps_ttm", "eps", "trailingEps"),
        "profit_margin_pct": ("profit_margin_pct", "profit_margin", "profitMargins"),
        "oper_margin_pct": ("oper_margin_pct", "operating_margin_pct", "operatingMargins"),
        "roic_pct": ("roic_pct", "roic"),
        "roe_pct": ("roe_pct", "returnOnEquity"),
        "total_debt_equity": ("total_debt_equity", "debt_equity", "debtToEquity"),
        "current_ratio": ("current_ratio", "currentRatio"),
        "quick_ratio": ("quick_ratio", "quickRatio"),
        "shares_outstanding_m": ("shares_outstanding_m", "shares_out_m", "sharesOutstandingM"),
        "short_float_pct": ("short_float_pct", "short_float"),
        "insider_own_pct": ("insider_own_pct", "insider_ownership_pct"),
        "inst_own_pct": ("inst_own_pct", "institutional_ownership_pct"),
        "eps_past_5y": ("eps_past_5y",),
        "sales_past_5y": ("sales_past_5y",),
        "eps_next_y": ("eps_next_y",),
        "sales_qoq": ("sales_qoq",),
    }
    for canonical, keys in aliases.items():
        value = _value(fundamentals_sources, *keys)
        parsed = _num(value)
        if parsed is not None:
            fundamentals[canonical] = parsed
    if market_cap_m is not None:
        fundamentals["market_cap_usd_millions"] = market_cap_m

    facts = {
        "symbol": symbol,
        "live_price": _first_num(_value(sources, "live_price", "enriched_price", "current_price", "last_price", "price")),
        "float_m": _first_num(_value(sources, "float_m", "float_shares_m", "shares_float_m", "float_millions")),
        "atr": _first_num(_value(sources, "atr", "atr_14", "atr14")),
        "rvol": _first_num(_value(sources, "rvol", "relative_volume", "relative_volume_x")),
        "rsi": _first_num(_value(sources, "rsi", "rsi14", "rsi_14")),
        "sma50": _first_num(_value(sources, "sma50", "sma_50")),
        "short_float_pct": _first_num(_value(sources, "short_float_pct", "short_float")),
        "instrument_type": _first_text(_value(sources, "instrument_type", "asset_type")),
        "quote_type": _first_text(_value(sources, "quote_type", "quoteType")),
        "bars_used": _first_num(_value(sources, "bars_used")),
        "event_state": _value(sources, "event_state"),
        "days_to_earnings": _first_num(_value(sources, "days_to_earnings")),
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

    provenance = {
        "packet_present": bool(packet),
        "finviz_present": bool(finviz),
        "supplement_present": bool(supplement),
        "watch_row_present": bool(watch_row),
        "cache_as_of": cache_as_of,
        "observed_fields": sorted(
            key for key, value in {
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
            }.items()
            if value is not None
        ),
    }
    return facts, technical_snapshot, provenance


def build_projection(conn, limit: int = 200, sample_limit: int = 40) -> dict:
    try:
        conn.rollback()
    except Exception:
        pass
    conn.set_session(readonly=True, autocommit=False)
    cur = conn.cursor()
    cur.execute("SHOW transaction_read_only")
    read_only = str(cur.fetchone()[0]).lower() == "on"
    if not read_only:
        raise RuntimeError("database session is not read-only")

    population = _ranked_population(cur, limit)
    symbols = [row["symbol"] for row in population]
    packets = _latest_packets(cur, symbols)
    finviz_cache = _load_json(FINVIZ_CACHE)
    supplement_cache = _load_json(VALUATION_SUPPLEMENT)
    held = _held_symbols()

    state_counts: Counter[str] = Counter()
    thesis_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    current_gate_counts: Counter[str] = Counter()
    rows: list[dict] = []

    for population_row in population:
        symbol = population_row["symbol"]
        packet_record = packets.get(symbol) or {}
        packet = _mapping(packet_record.get("packet"))
        facts, technical_snapshot, provenance = assemble_projection_facts(
            symbol,
            watch_row=population_row.get("watch_row"),
            packet=packet,
            finviz=finviz_cache.get(symbol),
            supplement=supplement_cache.get(symbol),
        )
        selected = packet_quality.select_governing_validation(packet)
        ticket = _mapping(selected.get("ticket"))
        ownership = _mapping(packet.get("ownership"))
        if symbol in held:
            ownership = {**ownership, "held": True}
        admission = quality_policy.evaluate_admission(
            facts,
            technical_snapshot=technical_snapshot,
            ticket=ticket,
            family=selected.get("family"),
            ownership=ownership,
        )
        projected = str(admission.get("state") or "UNASSESSED").upper()
        current_gate = packet_quality.packet_gate(packet)
        current_quality = str(current_gate.get("quality") or "UNASSESSED").upper()
        state_counts[projected] += 1
        thesis_counts[str(admission.get("thesis_state") or "UNKNOWN").upper()] += 1
        current_gate_counts[current_quality] += 1
        for field in provenance.get("observed_fields") or []:
            field_counts[field] += 1
        for reason in admission.get("reasons") or []:
            reason_counts[str(reason)] += 1
        rows.append({
            "symbol": symbol,
            "rank": population_row.get("rank"),
            "held": bool(ownership.get("held") or ownership.get("shares")),
            "packet_present": bool(packet),
            "current_packet_quality": current_quality,
            "projected_quality": projected,
            "new_entry_allowed": bool(admission.get("new_entry_allowed")),
            "management_only": bool(admission.get("management_only")),
            "thesis_state": admission.get("thesis_state"),
            "technical_freshness": _mapping(technical_snapshot).get("overall_freshness"),
            "primary_reason": (admission.get("reasons") or [None])[0],
            "hard_failures": admission.get("hard_failures") or [],
            "warnings": admission.get("warnings") or [],
            "facts_used": admission.get("facts_used") or {},
            "provenance": provenance,
        })

    conn.rollback()
    priority = sorted(
        rows,
        key=lambda row: (
            {"QUARANTINED": 0, "RESEARCH_ONLY": 1, "ADMITTED": 2}.get(row["projected_quality"], 3),
            row["rank"] if row["rank"] is not None else 10**9,
            row["symbol"],
        ),
    )
    return {
        "contract": CONTRACT,
        "generated_at": _now(),
        "read_only": read_only,
        "policy_version": quality_policy.POLICY_VERSION,
        "limit": limit,
        "population": len(population),
        "packets_found": len(packets),
        "current_packet_quality_counts": dict(sorted(current_gate_counts.items())),
        "projected_quality_counts": dict(sorted(state_counts.items())),
        "projected_new_entry_allowed": sum(1 for row in rows if row["new_entry_allowed"]),
        "projected_management_only": sum(1 for row in rows if row["management_only"]),
        "thesis_counts": dict(sorted(thesis_counts.items())),
        "evidence_field_coverage": dict(sorted(field_counts.items())),
        "top_reasons": reason_counts.most_common(25),
        "attention_sample": priority[:sample_limit],
        "all_rows": rows,
        "authority": {
            "database_write": False,
            "packet_rebuild": False,
            "cache_write": False,
            "network_refresh": False,
            "model_call": False,
            "provider_call": False,
            "schedule_change": False,
            "external_action": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sample-limit", type=int, default=40)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        raise SystemExit("--limit must be between 1 and 1000")
    if args.sample_limit < 0 or args.sample_limit > args.limit:
        raise SystemExit("--sample-limit must be between 0 and --limit")

    report = build_projection(_conn(), args.limit, args.sample_limit)
    public_report = {key: value for key, value in report.items() if key != "all_rows"}
    print(json.dumps(public_report, indent=2, sort_keys=True, default=str))
    if args.json_output:
        path = Path(args.json_output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        path.chmod(0o600)
        print(f"sanitized_json_output|{path}")


if __name__ == "__main__":
    main()

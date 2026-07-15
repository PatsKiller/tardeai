#!/usr/bin/env python3
"""
Advisory rotation intelligence scorer.

Read-only. Produces HOLD / ADD_REVIEW / TRIM_REVIEW / ROTATE_REVIEW ideas from
portfolio data, optionally enriched by symbol-card exports, ETF/fund overrides,
and Fidelity/manual fund-code mappings. It does not connect to external trading
systems and does not change holdings.
"""
from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ETF_OVERRIDES = Path("config/etf_classification_overrides.json")
DEFAULT_FUND_MAP = Path("config/fidelity_fund_code_map.json")


@dataclass
class Candidate:
    symbol: str
    account_key: str | None
    sector: str | None
    current_value: float
    account_type: str | None
    instrument_type: str
    trim_score: float
    add_score: float
    recommendation: str
    confidence: float
    evidence: dict[str, Any]


@dataclass
class RotationIdea:
    from_symbol: str
    to_symbol: str
    from_account: str | None
    to_account: str | None
    action_class: str
    score: float
    review_amount: float
    rationale: str
    evidence: dict[str, Any]


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "—"):
            return default
        return float(value)
    except Exception:
        return default


def first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, "", [], {}):
            return d.get(k)
    return None


def load_symbol_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    symbols = data.get("symbols", {}) if isinstance(data, dict) else {}
    return {str(k).upper(): v for k, v in symbols.items() if isinstance(v, dict)}


def load_fund_codes(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    codes = data.get("codes", {}) if isinstance(data, dict) else {}
    return {str(k).upper(): v for k, v in codes.items() if isinstance(v, dict)}


def account_type(account_key: str | None) -> str | None:
    if not account_key:
        return None
    text = account_key.lower()
    if "roth" in text:
        return "roth_ira"
    if "rollover" in text or "ira" in text:
        return "rollover_ira"
    if "taxable" in text:
        return "taxable"
    if "401" in text or "fidelity" in text:
        return "manual_401k"
    return text


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("holdings", "positions", "rows", "data"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        if all(isinstance(v, dict) for v in payload.values()):
            return [dict(v, symbol=v.get("symbol") or k) for k, v in payload.items()]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def cards_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
    rows = rows_from_payload(payload)
    if not rows and isinstance(payload, dict):
        for key in ("cards", "symbols", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                rows = [x for x in val if isinstance(x, dict)]
                break
            if isinstance(val, dict):
                rows = [dict(v, symbol=v.get("symbol") or k) for k, v in val.items() if isinstance(v, dict)]
                break
        if not rows and isinstance(payload.get("data"), dict):
            rows = list(cards_from_payload(payload["data"]).values())
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(first(row, "symbol", "ticker") or "").upper()
        if sym:
            out[sym] = row
    return out


def symbol_of(row: dict[str, Any]) -> str:
    return str(first(row, "symbol", "ticker") or "UNKNOWN").upper()


def merge_metadata(
    row: dict[str, Any],
    card: dict[str, Any] | None,
    symbol_overrides: dict[str, dict[str, Any]],
    fund_codes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merged = dict(row)
    sym = symbol_of(merged)
    sym_ov = symbol_overrides.get(sym, {})
    fund_ov = fund_codes.get(sym, {})

    if card:
        for src_keys, dest_key in [
            (("sector", "sector_name", "gics_sector"), "sector"),
            (("asset_class", "instrument_type", "security_type"), "asset_class"),
            (("analyst_upside_pct", "upside_pct", "target_upside_pct"), "analyst_upside_pct"),
            (("news_score", "sentiment_score"), "news_score"),
            (("protection_state", "stop_health"), "protection_state"),
        ]:
            if merged.get(dest_key) in (None, "", [], {}):
                val = first(card, *src_keys)
                if val not in (None, "", [], {}):
                    merged[dest_key] = val
        analyst = first(card, "analyst", "analyst_consensus")
        if isinstance(analyst, dict) and merged.get("analyst_upside_pct") in (None, "", [], {}):
            val = first(analyst, "upside_pct", "target_upside_pct", "upside")
            if val not in (None, "", [], {}):
                merged["analyst_upside_pct"] = val
        if isinstance(analyst, dict):
            _op = first(analyst, "opinions", "number_of_analyst_opinions")
            if _op not in (None, "", [], {}):
                merged["analyst_opinions"] = _op
        if first(card, "analyst_unavailable", "analyst_not_applicable", "no_analyst_coverage"):
            merged["analyst_unavailable"] = True
        merged["_card_enriched"] = True

    for ov, marker in ((sym_ov, "_override_enriched"), (fund_ov, "_fund_code_enriched")):
        if not ov:
            continue
        for key in ("sector", "asset_class", "instrument_type", "display_name"):
            if merged.get(key) in (None, "", [], {}) and ov.get(key) not in (None, "", [], {}):
                merged[key] = ov.get(key)
        if ov.get("analyst_required") is False:
            merged["analyst_not_applicable"] = True
        if ov.get("manual_only") is True:
            merged["manual_only"] = True
        if ov.get("mapping_status"):
            merged["mapping_status"] = ov.get("mapping_status")
        if ov.get("mag7_exposure_pct") is not None:
            merged["mag7_exposure_pct"] = ov.get("mag7_exposure_pct")
        merged[marker] = True
    return merged


def instrument_type_for(row: dict[str, Any]) -> str:
    return str(first(row, "asset_class", "instrument_type", "security_type") or "equity")


def score_row(row: dict[str, Any], total_value: float, stops: dict[str, Any] | None = None) -> Candidate:
    symbol = symbol_of(row)
    account_key = first(row, "account_key", "account")
    sector = first(row, "sector", "sector_type", "gics_sector")
    asset_class = instrument_type_for(row)
    value = as_float(first(row, "market_value", "current_value", "value"))
    concentration = (value / total_value * 100.0) if total_value else 0.0
    upside = as_float(first(row, "analyst_upside_pct", "upside_pct", "target_upside_pct"), 0.0)
    sentiment = as_float(first(row, "news_score", "sentiment_score"), 0.0)
    income_yield = as_float(first(row, "yield", "dividend_yield", "income_yield"), 0.0)
    protection = str(first(row, "protection_state", "stop_health") or "unknown")
    acct = account_type(str(account_key) if account_key else None)
    analyst_na = bool(first(row, "analyst_unavailable", "analyst_not_applicable", "no_analyst_coverage"))
    manual_only = bool(first(row, "manual_only")) or acct == "manual_401k"
    mapping_status = first(row, "mapping_status")

    trim = 0.0
    add = 0.0
    evidence: dict[str, Any] = {"concentration_pct": round(concentration, 2)}
    if row.get("_card_enriched"):
        evidence["symbol_card_enriched"] = True
    if row.get("_override_enriched"):
        evidence["classification_override"] = True
    if row.get("_fund_code_enriched"):
        evidence["fund_code_mapping"] = mapping_status or "mapped"
    if analyst_na:
        evidence["analyst_not_applicable"] = True
    if not sector:
        evidence["missing_sector"] = True
    if upside == 0.0 and not analyst_na:
        evidence["missing_or_neutral_analyst_upside"] = True
    if manual_only:
        evidence["manual_only"] = True
    if mapping_status and mapping_status != "verified":
        evidence["mapping_status"] = mapping_status

    asset_l = asset_class.lower()
    is_fund = "etf" in asset_l or "fund" in asset_l or "index" in asset_l

    if concentration >= 5.0:
        trim += min(25.0, (concentration - 5.0) * 3.0)
        evidence["concentration_review"] = True
    if upside < -5:
        trim += 15
        evidence["negative_upside_pct"] = upside
    if upside > 10:
        _addc = min(25.0, upside / 2.0)
        # Thin analyst coverage (<3 opinions) makes a high upside unreliable — discount the add it earns so
        # a +79% from 1 analyst doesn't score like a +34% from 9.
        _opinions = first(row, "analyst_opinions")
        _thin = (_opinions is None) or (as_float(_opinions, 0) < 3)
        if _thin:
            _addc *= 0.4
            evidence["thin_analyst_coverage"] = True
        add += _addc
        evidence["positive_upside_pct"] = upside
    if sentiment < -0.25:
        trim += 10
        evidence["negative_news_score"] = sentiment
    if sentiment > 0.25:
        add += 8
        evidence["positive_news_score"] = sentiment
    if protection in {"unprotected", "alert", "near_trigger", "orphaned", "oversized"}:
        trim += 8
        evidence["protection_review"] = protection
    # advisory surfacing only (stop_policy.yaml dynamic tiers) — never moves the score;
    # gives the rotation LLM + UI the same tier context the protection advisor uses
    try:
        import holding_family as _hf
        _fam, _fam_src = _hf.classify_family(symbol)
        _vt = _hf.volatility_tier(symbol)
        evidence["stop_tier"] = _fam
        evidence["stop_tier_source"] = _fam_src
        if _vt:
            evidence["volatility_tier"] = _vt.get("tier")
    except Exception:
        pass
    if income_yield >= 0.05:
        trim = max(0.0, trim - 8)
        evidence["income_preservation"] = income_yield
    if acct == "taxable" and trim > 0:
        trim = max(0.0, trim - 5)
        evidence["taxable_review_required"] = True
    if acct == "roth_ira" and add > 0:
        add += 5
        evidence["growth_account_fit"] = "roth_ira"
    if is_fund and sector:
        evidence["fund_sector"] = sector

    # Unknown manual fund codes should not produce strong action classes.
    if manual_only and mapping_status and mapping_status != "verified":
        trim = min(trim, 20.0)
        add = min(add, 0.0)
        evidence["action_downgraded_until_mapping_verified"] = True

    # Stop-risk overlay (Aegis nightly thesis) — a deteriorating/triggered protective stop adds trim
    # regardless of concentration/valuation, and is NOT softened by the income/taxable reductions above.
    # This is how a small high-upside name with a BROKEN stop still becomes a rotate-out review, instead of
    # the engine (blind to stop state) scoring it trim=0. Deterministic stop math dominates valuation here.
    _STOP_TRIM = {"triggered": 40.0, "danger": 40.0, "broken": 40.0, "warning": 20.0, "weakening": 10.0}
    stop = (stops or {}).get(symbol.upper()) if symbol else None
    if stop:
        _stt = _STOP_TRIM.get(str(stop.get("status", "")).lower(), 0.0)
        if _stt:
            trim += _stt
            evidence["stop_status"] = stop.get("status")
            evidence["stop_trim"] = _stt

    trim = round(max(0.0, min(100.0, trim)), 2)
    add = round(max(0.0, min(100.0, add)), 2)

    if trim >= 35 and trim > add:
        rec = "TRIM_REVIEW"
        confidence = min(0.95, 0.45 + trim / 100.0)
    elif add >= 30 and add >= trim:
        rec = "ADD_REVIEW"
        confidence = min(0.95, 0.45 + add / 100.0)
    elif trim >= 20 or add >= 20:
        rec = "WATCH"
        confidence = 0.55
    else:
        rec = "HOLD"
        confidence = 0.50

    return Candidate(symbol, str(account_key) if account_key else None, sector, value, acct, asset_class, trim, add, rec, round(confidence, 3), evidence)


def build_ideas(candidates: list[Candidate], min_pair_score: float) -> list[RotationIdea]:
    trims = [c for c in candidates if c.recommendation in {"TRIM_REVIEW", "WATCH"} and c.trim_score > 0]
    adds = [c for c in candidates if c.recommendation in {"ADD_REVIEW", "WATCH"} and c.add_score > 0]
    ideas: list[RotationIdea] = []
    for src in trims:
        for dst in adds:
            if src.symbol == dst.symbol:
                continue
            score = round(min(100.0, src.trim_score * 0.55 + dst.add_score * 0.65 + (5 if src.sector != dst.sector else 0)), 2)
            if score < min_pair_score:
                continue
            amount = round(min(src.current_value * 0.10, 5000.0), 2)
            ideas.append(RotationIdea(
                from_symbol=src.symbol,
                to_symbol=dst.symbol,
                from_account=src.account_key,
                to_account=dst.account_key,
                action_class="ROTATE_REVIEW" if score >= 70 else "WATCH_PAIR",
                score=score,
                review_amount=amount,
                rationale=f"Review shifting partial exposure from {src.symbol} to {dst.symbol}; evidence favors human review, not automatic action.",
                evidence={"from": src.evidence, "to": dst.evidence},
            ))
    return sorted(ideas, key=lambda x: x.score, reverse=True)[:20]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/portfolios/state/holdings.json")
    ap.add_argument("--cards", help="optional /api/v2/symbol-cards JSON export for analyst/news/sector enrichment")
    ap.add_argument("--etf-overrides", default=str(DEFAULT_ETF_OVERRIDES))
    ap.add_argument("--fund-map", default=str(DEFAULT_FUND_MAP))
    ap.add_argument("--min-pair-score", type=float, default=45.0)
    ap.add_argument("--stops", help="optional JSON map {SYMBOL: {status, severity}} of Aegis stop/thesis "
                                    "deterioration; adds trim so a broken stop drives a rotate-out review")
    args = ap.parse_args()

    payload = json.loads(Path(args.input).read_text())
    rows = rows_from_payload(payload)
    symbol_overrides = load_symbol_overrides(Path(args.etf_overrides))
    fund_codes = load_fund_codes(Path(args.fund_map))
    cards = cards_from_payload(json.loads(Path(args.cards).read_text())) if args.cards else {}
    total = as_float((payload.get("portfolio_totals", {}) or {}).get("total_value")) if isinstance(payload, dict) else 0.0
    if not total:
        total = sum(as_float(first(r, "market_value", "current_value", "value")) for r in rows)

    stops = {}
    if args.stops:
        try:
            stops = {k.upper(): v for k, v in json.loads(Path(args.stops).read_text()).items()}
        except Exception:
            stops = {}
    enriched_rows = [merge_metadata(r, cards.get(symbol_of(r)), symbol_overrides, fund_codes) for r in rows]
    candidates = [score_row(r, total, stops) for r in enriched_rows]
    ideas = build_ideas(candidates, args.min_pair_score)
    data_quality = {
        "holding_rows": len(rows),
        "symbol_cards_loaded": len(cards),
        "etf_overrides_loaded": len(symbol_overrides),
        "fund_codes_loaded": len(fund_codes),
        "rows_with_sector": sum(1 for c in candidates if c.sector),
        "rows_with_add_or_trim_signal": sum(1 for c in candidates if c.add_score > 0 or c.trim_score > 0),
        "fund_or_etf_rows": sum(1 for c in candidates if any(x in c.instrument_type.lower() for x in ("etf", "fund", "index"))),
        "manual_401k_rows": sum(1 for c in candidates if c.account_type == "manual_401k"),
    }
    report = {
        "ok": True,
        "run_id": f"rotation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "advisory_only": True,
        "data_quality": data_quality,
        "diagnostics": "No rotation ideas means no source has a trim signal and no destination has an add signal above thresholds. Use --cards, ETF overrides, and fund-map enrichment.",
        "summary": {
            "trim_review": sum(c.recommendation == "TRIM_REVIEW" for c in candidates),
            "add_review": sum(c.recommendation == "ADD_REVIEW" for c in candidates),
            "watch": sum(c.recommendation == "WATCH" for c in candidates),
            "rotation_ideas": len(ideas),
        },
        "top_candidates": [asdict(c) for c in sorted(candidates, key=lambda c: max(c.trim_score, c.add_score), reverse=True)[:25]],
        "top_rotation_ideas": [asdict(i) for i in ideas],
        "safety": "Advisory only. Human review required. No account changes are made by this script.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

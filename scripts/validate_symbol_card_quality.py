#!/usr/bin/env python3
"""
Validate symbol-card intelligence coverage.

Read-only. Accepts several common API shapes and reports useful diagnostics
when an endpoint returns an error, empty object, or unexpected payload shape.

ETF/fund symbols are handled differently from individual equities: analyst
coverage is not required when an override marks the symbol as analyst_not_applicable.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ["symbol", "description", "sector", "analyst", "news"]
STALE_DAYS = {"quote": 1, "news": 14, "analyst": 45, "profile": 90}
DEFAULT_ETF_OVERRIDES = Path("config/etf_classification_overrides.json")


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def age_days(value: Any) -> float | None:
    dt = parse_dt(value)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def load_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    symbols = data.get("symbols", {}) if isinstance(data, dict) else {}
    return {str(k).upper(): v for k, v in symbols.items() if isinstance(v, dict)}


def _dict_values_to_cards(d: dict[str, Any]) -> list[dict[str, Any]]:
    if not d:
        return []
    if all(isinstance(v, dict) for v in d.values()):
        return [dict(v, symbol=v.get("symbol") or k) for k, v in d.items()]
    return []


def normalize_payload(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diag: dict[str, Any] = {"payload_type": type(data).__name__}
    if isinstance(data, dict):
        diag["top_level_keys"] = sorted([str(k) for k in data.keys()])[:50]
        if data.get("ok") is False:
            diag["payload_error"] = data.get("error") or data.get("reason") or data.get("message") or "ok=false"
        for key in ("cards", "symbols", "items", "results", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                diag["card_source"] = key
                return [x for x in value if isinstance(x, dict)], diag
            if isinstance(value, dict):
                diag["card_source"] = key
                cards = _dict_values_to_cards(value)
                if cards:
                    return cards, diag
        value = data.get("data")
        if isinstance(value, list):
            diag["card_source"] = "data"
            return [x for x in value if isinstance(x, dict)], diag
        if isinstance(value, dict):
            diag["data_keys"] = sorted([str(k) for k in value.keys()])[:50]
            for key in ("cards", "symbols", "items", "results", "rows"):
                nested = value.get(key)
                if isinstance(nested, list):
                    diag["card_source"] = f"data.{key}"
                    return [x for x in nested if isinstance(x, dict)], diag
                if isinstance(nested, dict):
                    diag["card_source"] = f"data.{key}"
                    cards = _dict_values_to_cards(nested)
                    if cards:
                        return cards, diag
            cards = _dict_values_to_cards(value)
            if cards:
                diag["card_source"] = "data.<symbol_map>"
                return cards, diag
        cards = _dict_values_to_cards(data)
        if cards:
            diag["card_source"] = "<symbol_map>"
            return cards, diag
    if isinstance(data, list):
        diag["card_source"] = "root_list"
        return [x for x in data if isinstance(x, dict)], diag
    return [], diag


def first(card: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if card.get(key) not in (None, "", [], {}):
            return card.get(key)
    return None


def symbol_for(card: dict[str, Any]) -> str:
    return str(first(card, "symbol", "ticker") or "UNKNOWN").upper()


def override_for(card: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return overrides.get(symbol_for(card), {})


def instrument_type(card: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> str:
    ov = override_for(card, overrides)
    asset_class = first(card, "asset_class", "instrument_type", "security_type") or ov.get("asset_class")
    if asset_class:
        text = str(asset_class).lower()
        if "etf" in text or "fund" in text or "index" in text:
            return str(asset_class)
        return str(asset_class)
    return "equity"


def analyst_not_applicable(card: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> bool:
    ov = override_for(card, overrides)
    if ov.get("analyst_required") is False:
        return True
    return bool(first(card, "analyst_unavailable", "analyst_not_applicable", "no_analyst_coverage"))


def sector_value(card: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> Any:
    return first(card, "sector", "sector_name", "gics_sector", "sector_etf") or override_for(card, overrides).get("sector")


def is_present(card: dict[str, Any], field: str, overrides: dict[str, dict[str, Any]]) -> bool:
    if field == "sector":
        return sector_value(card, overrides) not in (None, "", [], {})
    if field == "analyst" and analyst_not_applicable(card, overrides):
        return True
    aliases = {
        "description": ("description", "company_description", "business_summary", "summary"),
        "analyst": ("analyst", "analyst_consensus", "analyst_rating", "target_price", "price_target", "upside_pct"),
        "news": ("news", "top_news", "articles", "headlines"),
        "symbol": ("symbol", "ticker"),
    }
    for key in aliases.get(field, (field,)):
        value = card.get(key)
        if value in (None, "", [], {}):
            continue
        if field == "analyst" and isinstance(value, dict):
            return any(value.get(k) not in (None, "", [], {}) for k in ("rating", "consensus", "target", "target_price", "price_target", "upside_pct"))
        if field == "news" and isinstance(value, list):
            return len(value) > 0
        return True
    return False


def quality_for(card: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [f for f in REQUIRED_FIELDS if not is_present(card, f, overrides)]
    score = 100 - len(missing) * 15
    news_list = first(card, "news", "top_news", "articles", "headlines")
    analyst_obj = first(card, "analyst", "analyst_consensus")
    freshness_warnings = []
    stamps = {
        "quote": first(card, "quote_updated_at", "price_updated_at", "updated_at"),
        "news": first(card, "news_updated_at") or (news_list[0].get("published_at") if isinstance(news_list, list) and news_list and isinstance(news_list[0], dict) else None),
        "analyst": first(card, "analyst_updated_at") or (analyst_obj.get("updated_at") if isinstance(analyst_obj, dict) else None),
        "profile": first(card, "profile_updated_at", "description_updated_at"),
    }
    for key, max_days in STALE_DAYS.items():
        if key == "analyst" and analyst_not_applicable(card, overrides):
            continue
        days = age_days(stamps.get(key))
        if days is not None and days > max_days:
            freshness_warnings.append(f"{key}_stale_{days:.1f}d")
            score -= 5
    score = max(0, min(100, score))
    status = "ACTIONABLE" if score >= 85 and not missing else "WATCH" if score >= 70 else "MISSING_DATA"
    return {
        "symbol": symbol_for(card),
        "instrument_type": instrument_type(card, overrides),
        "sector": sector_value(card, overrides),
        "score": score,
        "status": status,
        "missing": missing,
        "freshness_warnings": freshness_warnings,
        "analyst_not_applicable": analyst_not_applicable(card, overrides),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    missing_by_field = Counter()
    missing_by_symbol: dict[str, list[str]] = {}
    by_status = Counter(r["status"] for r in results)
    by_type = Counter(str(r.get("instrument_type") or "unknown") for r in results)
    missing_by_type: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        if r["missing"]:
            missing_by_symbol[r["symbol"]] = r["missing"]
        for f in r["missing"]:
            missing_by_field[f] += 1
            missing_by_type[str(r.get("instrument_type") or "unknown")][f] += 1
    return {
        "by_status": dict(by_status),
        "by_instrument_type": dict(by_type),
        "missing_by_field": dict(missing_by_field),
        "missing_by_type": {k: dict(v) for k, v in missing_by_type.items()},
        "symbols_missing_sector": [r["symbol"] for r in results if "sector" in r["missing"]],
        "symbols_missing_analyst": [r["symbol"] for r in results if "analyst" in r["missing"]],
        "symbols_missing_news": [r["symbol"] for r in results if "news" in r["missing"]],
        "missing_by_symbol": missing_by_symbol,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input")
    src.add_argument("--stdin", action="store_true")
    ap.add_argument("--etf-overrides", default=str(DEFAULT_ETF_OVERRIDES))
    ap.add_argument("--min-actionable-coverage", type=float, default=0.95)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.stdin else Path(args.input).read_text()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        report = {"ok": False, "error": "invalid_json", "detail": str(exc), "raw_prefix": raw[:300]}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    overrides = load_overrides(Path(args.etf_overrides))
    cards, diag = normalize_payload(payload)
    results = [quality_for(c, overrides) for c in cards]
    actionable = [r for r in results if r["status"] == "ACTIONABLE"]
    coverage = (len(actionable) / len(results)) if results else 0.0
    report = {
        "ok": bool(results) and coverage >= args.min_actionable_coverage,
        "card_count": len(results),
        "actionable_count": len(actionable),
        "actionable_coverage": round(coverage, 4),
        "min_actionable_coverage": args.min_actionable_coverage,
        "diagnostics": {**diag, "etf_overrides_loaded": len(overrides)},
        "coverage_report": summarize(results),
        "hint": "For ETFs/funds, add config/etf_classification_overrides.json entries. For small caps without coverage, emit analyst_unavailable=true or no_analyst_coverage=true.",
        "worst": sorted(results, key=lambda r: r["score"])[:25],
    }
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

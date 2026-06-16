#!/usr/bin/env python3
"""
Validate symbol-card intelligence coverage.

Read-only. Accepts several common API shapes and reports useful diagnostics
when an endpoint returns an error, empty object, or unexpected payload shape.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = ["symbol", "description", "sector", "analyst", "news"]
STALE_DAYS = {"quote": 1, "news": 14, "analyst": 45, "profile": 90}


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


def is_present(card: dict[str, Any], field: str) -> bool:
    aliases = {
        "description": ("description", "company_description", "business_summary", "summary"),
        "sector": ("sector", "sector_name", "gics_sector", "sector_etf"),
        "analyst": ("analyst", "analyst_consensus", "analyst_rating", "target_price", "price_target", "upside_pct"),
        "news": ("news", "top_news", "articles", "headlines"),
        "symbol": ("symbol", "ticker"),
    }
    keys = aliases.get(field, (field,))
    for key in keys:
        value = card.get(key)
        if value in (None, "", [], {}):
            continue
        if field == "analyst" and isinstance(value, dict):
            return any(value.get(k) not in (None, "", [], {}) for k in ("rating", "consensus", "target", "target_price", "price_target", "upside_pct"))
        if field == "news" and isinstance(value, list):
            return len(value) > 0
        return True
    return False


def first(card: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if card.get(key) not in (None, "", [], {}):
            return card.get(key)
    return None


def quality_for(card: dict[str, Any]) -> dict[str, Any]:
    missing = [f for f in REQUIRED_FIELDS if not is_present(card, f)]
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
        days = age_days(stamps.get(key))
        if days is not None and days > max_days:
            freshness_warnings.append(f"{key}_stale_{days:.1f}d")
            score -= 5
    score = max(0, min(100, score))
    return {
        "symbol": first(card, "symbol", "ticker") or "UNKNOWN",
        "score": score,
        "status": "ACTIONABLE" if score >= 85 and not missing else "WATCH" if score >= 70 else "MISSING_DATA",
        "missing": missing,
        "freshness_warnings": freshness_warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input")
    src.add_argument("--stdin", action="store_true")
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

    cards, diag = normalize_payload(payload)
    results = [quality_for(c) for c in cards]
    actionable = [r for r in results if r["status"] == "ACTIONABLE"]
    coverage = (len(actionable) / len(results)) if results else 0.0
    report = {
        "ok": bool(results) and coverage >= args.min_actionable_coverage,
        "card_count": len(results),
        "actionable_count": len(actionable),
        "actionable_coverage": round(coverage, 4),
        "min_actionable_coverage": args.min_actionable_coverage,
        "diagnostics": diag,
        "hint": "card_count=0 means the endpoint returned an error/empty/unexpected shape; inspect diagnostics.top_level_keys and payload_error.",
        "worst": sorted(results, key=lambda r: r["score"])[:25],
    }
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

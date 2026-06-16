#!/usr/bin/env python3
"""
Validate symbol-card intelligence coverage.

Read-only. The validator can run against a JSON export from
/api/v2/symbol-cards or directly against a lightweight fixture. It does not
change DB state and does not place orders.

Usage examples:
  python scripts/validate_symbol_card_quality.py --input data/symbol_cards.json
  curl -s http://localhost:7777/api/v2/symbol-cards | python scripts/validate_symbol_card_quality.py --stdin
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = [
    "symbol",
    "description",
    "sector",
    "analyst",
    "news",
]

STALE_DAYS = {
    "quote": 1,
    "news": 14,
    "analyst": 45,
    "profile": 90,
}


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def age_days(value: Any) -> float | None:
    dt = parse_dt(value)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def normalize_payload(data: Any) -> list[dict]:
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if "cards" in data and isinstance(data["cards"], list):
            return [x for x in data["cards"] if isinstance(x, dict)]
        if "symbols" in data and isinstance(data["symbols"], dict):
            return [dict(v, symbol=k) if isinstance(v, dict) else {"symbol": k, "value": v} for k, v in data["symbols"].items()]
        # Common shape: {"AAPL": {...}, "MSFT": {...}}
        if all(isinstance(v, dict) for v in data.values()):
            return [dict(v, symbol=v.get("symbol") or k) for k, v in data.items()]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def is_present(card: dict, field: str) -> bool:
    value = card.get(field)
    if value in (None, "", [], {}):
        return False
    if field == "analyst" and isinstance(value, dict):
        return any(value.get(k) not in (None, "", [], {}) for k in ("rating", "consensus", "target", "target_price", "upside_pct"))
    if field == "news" and isinstance(value, list):
        return len(value) > 0
    return True


def quality_for(card: dict) -> dict:
    missing = [f for f in REQUIRED_FIELDS if not is_present(card, f)]
    score = 100 - len(missing) * 15

    freshness_warnings = []
    stamps = {
        "quote": card.get("quote_updated_at") or card.get("price_updated_at") or card.get("updated_at"),
        "news": card.get("news_updated_at") or (card.get("news", [{}])[0].get("published_at") if isinstance(card.get("news"), list) and card.get("news") else None),
        "analyst": card.get("analyst_updated_at") or (card.get("analyst", {}) or {}).get("updated_at") if isinstance(card.get("analyst"), dict) else None,
        "profile": card.get("profile_updated_at") or card.get("description_updated_at"),
    }
    for key, max_days in STALE_DAYS.items():
        days = age_days(stamps.get(key))
        if days is not None and days > max_days:
            freshness_warnings.append(f"{key}_stale_{days:.1f}d")
            score -= 5

    score = max(0, min(100, score))
    status = "ACTIONABLE" if score >= 85 and not missing else "WATCH" if score >= 70 else "MISSING_DATA"
    return {
        "symbol": card.get("symbol") or card.get("ticker") or "UNKNOWN",
        "score": score,
        "status": status,
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
    cards = normalize_payload(json.loads(raw))
    results = [quality_for(c) for c in cards]
    actionable = [r for r in results if r["status"] == "ACTIONABLE"]
    coverage = (len(actionable) / len(results)) if results else 0.0
    report = {
        "ok": coverage >= args.min_actionable_coverage,
        "card_count": len(results),
        "actionable_count": len(actionable),
        "actionable_coverage": round(coverage, 4),
        "min_actionable_coverage": args.min_actionable_coverage,
        "worst": sorted(results, key=lambda r: r["score"])[:25],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Cards: {report['card_count']} | actionable: {report['actionable_count']} | coverage: {coverage:.1%}")
        for row in report["worst"][:10]:
            print(f"{row['symbol']}: {row['score']} {row['status']} missing={row['missing']} stale={row['freshness_warnings']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

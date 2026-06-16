#!/usr/bin/env python3
"""
Advisory rotation intelligence scorer.

Read-only. Produces HOLD / ADD_REVIEW / TRIM_REVIEW / ROTATE_REVIEW ideas from
portfolio data. It does not connect to external trading systems and does not
change holdings.
"""
from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Candidate:
    symbol: str
    account_key: str | None
    sector: str | None
    current_value: float
    account_type: str | None
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


def score_row(row: dict[str, Any], total_value: float) -> Candidate:
    symbol = str(row.get("symbol") or row.get("ticker") or "UNKNOWN").upper()
    account_key = row.get("account_key") or row.get("account")
    sector = row.get("sector") or row.get("sector_type")
    value = as_float(row.get("market_value") or row.get("current_value") or row.get("value"))
    concentration = (value / total_value * 100.0) if total_value else 0.0
    upside = as_float(row.get("analyst_upside_pct") or row.get("upside_pct"), 0.0)
    sentiment = as_float(row.get("news_score") or row.get("sentiment_score"), 0.0)
    income_yield = as_float(row.get("yield") or row.get("dividend_yield") or row.get("income_yield"), 0.0)
    protection = str(row.get("protection_state") or row.get("stop_health") or "unknown")
    acct = account_type(account_key)

    trim = 0.0
    add = 0.0
    evidence: dict[str, Any] = {"concentration_pct": round(concentration, 2)}

    if concentration >= 5.0:
        trim += min(25.0, (concentration - 5.0) * 3.0)
        evidence["concentration_review"] = True
    if upside < -5:
        trim += 15
        evidence["negative_upside_pct"] = upside
    if upside > 10:
        add += min(25.0, upside / 2.0)
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
    if income_yield >= 0.05:
        trim = max(0.0, trim - 8)
        evidence["income_preservation"] = income_yield
    if acct == "taxable" and trim > 0:
        trim = max(0.0, trim - 5)
        evidence["taxable_review_required"] = True
    if acct == "roth_ira" and add > 0:
        add += 5
        evidence["growth_account_fit"] = "roth_ira"
    if acct == "manual_401k":
        evidence["manual_only"] = True

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

    return Candidate(symbol, account_key, sector, value, acct, trim, add, rec, round(confidence, 3), evidence)


def build_ideas(candidates: list[Candidate]) -> list[RotationIdea]:
    trims = [c for c in candidates if c.recommendation == "TRIM_REVIEW"]
    adds = [c for c in candidates if c.recommendation == "ADD_REVIEW"]
    ideas: list[RotationIdea] = []
    for src in trims:
        for dst in adds:
            if src.symbol == dst.symbol:
                continue
            score = round(min(100.0, src.trim_score * 0.55 + dst.add_score * 0.65 + (5 if src.sector != dst.sector else 0)), 2)
            if score < 45:
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
                rationale=f"Review shifting partial exposure from {src.symbol} to {dst.symbol}; evidence favors a human-reviewed rotation, not automatic action.",
                evidence={"from": src.evidence, "to": dst.evidence},
            ))
    return sorted(ideas, key=lambda x: x.score, reverse=True)[:20]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/portfolios/state/holdings.json")
    args = ap.parse_args()

    payload = json.loads(Path(args.input).read_text())
    rows = rows_from_payload(payload)
    total = as_float((payload.get("portfolio_totals", {}) or {}).get("total_value")) if isinstance(payload, dict) else 0.0
    if not total:
        total = sum(as_float(r.get("market_value") or r.get("current_value") or r.get("value")) for r in rows)

    candidates = [score_row(r, total) for r in rows]
    ideas = build_ideas(candidates)
    report = {
        "ok": True,
        "run_id": f"rotation-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "advisory_only": True,
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

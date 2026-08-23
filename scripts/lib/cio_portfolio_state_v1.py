"""Deterministic PortfolioState@v1 projection.

Observed cash is not synonymous with investable cash. Investable cash remains
UNVERIFIED until every included account has current, read-only broker evidence.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "PortfolioState@v1"
READ_ONLY_CASH_SOURCE_CLASSES = frozenset({"BROKER_READ_ONLY", "CUSTODIAN_READ_ONLY"})


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _asset_class(row: dict[str, Any]) -> str:
    if row.get("is_cash") or str(row.get("symbol") or "").upper() in {"CASH", "USD"}:
        return "CASH"
    asset = str(row.get("asset_type") or row.get("bucket") or "").upper()
    symbol = str(row.get("symbol") or "").upper()
    if "BOND" in asset or "FIXED" in asset or (symbol.isdigit() and len(symbol) >= 8):
        return "FIXED_INCOME"
    if any(token in asset for token in ("ETF", "FUND", "EQUITY", "STOCK")):
        return "EQUITY"
    return "OTHER"


def load_holdings_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"holdings_unavailable:{type(exc).__name__}", "holdings": []}
    return value if isinstance(value, dict) else {"ok": False, "error": "holdings_not_object", "holdings": []}


def build_portfolio_state(
    holdings_document: dict[str, Any],
    *,
    broker_cash_evidence: dict[str, dict[str, Any]] | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    rows = [row for row in holdings_document.get("holdings", []) if isinstance(row, dict)]
    evidence = broker_cash_evidence or {}
    positions: list[dict[str, Any]] = []
    cash_accounts: dict[str, dict[str, Any]] = {}
    allocation_values = {"CASH": 0.0, "EQUITY": 0.0, "FIXED_INCOME": 0.0, "OTHER": 0.0}
    conflicted = 0
    unavailable_values = 0

    for row in rows:
        account = str(row.get("account_id") or row.get("account") or "UNKNOWN")
        asset_class = _asset_class(row)
        market_value = _num(_first_not_none(row.get("market_value"), row.get("current_value_usd")))
        if market_value is None:
            unavailable_values += 1
            market_value = 0.0
        allocation_values[asset_class] += market_value
        is_conflicted = bool(row.get("conflicted"))
        conflicted += int(is_conflicted)
        position = {
            "symbol": str(row.get("symbol") or row.get("ticker") or "").upper(),
            "account_id": account,
            "asset_class": asset_class,
            "asset_type": row.get("asset_type"),
            "quantity": _num(_first_not_none(row.get("quantity"), row.get("shares"))),
            "market_value_usd": round(market_value, 2),
            "price": _num(_first_not_none(row.get("canonical_mark"), row.get("current_price"), row.get("price"))),
            "price_source": row.get("canonical_mark_source") or row.get("source"),
            "source_as_of": row.get("canonical_mark_as_of") or row.get("as_of") or row.get("updated_at"),
            "source": row.get("source"),
            "truth_quality": "CONFLICTED" if is_conflicted else "VERIFIED",
        }
        positions.append(position)
        if asset_class == "CASH":
            current = cash_accounts.setdefault(account, {"observed_cash_usd": 0.0, "source_rows": []})
            current["observed_cash_usd"] = round(current["observed_cash_usd"] + market_value, 2)
            current["source_rows"].append({"source": row.get("source"), "as_of": position["source_as_of"]})

    all_cash_verified = bool(cash_accounts)
    investable_total = 0.0
    for account, cash in cash_accounts.items():
        proof = evidence.get(account) if isinstance(evidence.get(account), dict) else {}
        verified = (
            bool(proof.get("verified"))
            and proof.get("source_class") in READ_ONLY_CASH_SOURCE_CLASSES
            and bool(proof.get("source"))
            and bool(proof.get("as_of"))
        )
        cash.update({
            "settled_cash_usd": _num(proof.get("settled_cash_usd")) if verified else None,
            "available_cash_usd": _num(proof.get("available_cash_usd")) if verified else None,
            "buying_power_usd": _num(proof.get("buying_power_usd")) if verified else None,
            "reserved_cash_usd": _num(proof.get("reserved_cash_usd")) if verified else None,
            "investable_cash_usd": _num(proof.get("investable_cash_usd")) if verified else None,
            "verification_source": proof.get("source") if verified else None,
            "verification_source_class": proof.get("source_class") if verified else None,
            "verification_as_of": proof.get("as_of") if verified else None,
            "truth_quality": "VERIFIED" if verified else "UNVERIFIED_INVESTABLE",
        })
        if not verified or cash["investable_cash_usd"] is None:
            all_cash_verified = False
        else:
            investable_total += float(cash["investable_cash_usd"])

    totals = holdings_document.get("portfolio_totals") if isinstance(holdings_document.get("portfolio_totals"), dict) else {}
    computed_total = sum(allocation_values.values())
    total_value = _num(totals.get("total_value")) or computed_total
    observed_cash = allocation_values["CASH"]
    allocation = {
        key.lower(): {
            "market_value_usd": round(value, 2),
            "pct": round((value / total_value * 100.0), 4) if total_value else None,
        }
        for key, value in allocation_values.items()
    }
    if not rows or total_value <= 0 or unavailable_values:
        quality = "UNAVAILABLE"
    elif conflicted:
        quality = "CONFLICTED"
    elif not all_cash_verified:
        quality = "UNVERIFIED_INVESTABLE"
    else:
        quality = "VERIFIED"

    payload = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_as_of": holdings_document.get("generated_at") or holdings_document.get("as_of"),
        "source_path": source_path,
        "truth_quality": quality,
        "total_portfolio_value_usd": round(total_value, 2),
        "observed_cash_usd": round(observed_cash, 2),
        "investable_cash_usd": round(investable_total, 2) if all_cash_verified else None,
        "investable_cash_status": "VERIFIED" if all_cash_verified else "UNVERIFIED_INVESTABLE",
        "cash_accounts": cash_accounts,
        "allocation": allocation,
        "positions": positions,
        "position_count": len(positions),
        "conflicted_position_count": conflicted,
        "unavailable_value_count": unavailable_values,
        "financial_arithmetic": "DETERMINISTIC_PYTHON",
        "llm_arithmetic": False,
    }
    payload["version"] = "portfolio_state_" + hashlib.sha256(
        json.dumps({k: payload[k] for k in ("source_as_of", "truth_quality", "total_portfolio_value_usd", "observed_cash_usd", "investable_cash_usd", "allocation")}, sort_keys=True).encode()
    ).hexdigest()[:16]
    return payload

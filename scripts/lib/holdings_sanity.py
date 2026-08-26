"""Evidence-based holdings snapshot validation.

Replaces the historical hard-coded $1,000,000 floor (which assumed a ~$1.24M
portfolio) with coverage / completeness / relative-drop guards.

The same contract is used pre-write and post-write. Reason codes are stable.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

# Known governed brokerage accounts. Optional venues present on last-good are
# also required when they carried material value.
REQUIRED_ACCOUNTS = (
    "schwab_taxable",
    "schwab_roth",
    "schwab_rollover_ira",
)
# Historical aliases written into holdings.json
ACCOUNT_ALIASES = {
    "schwab_roth_ira": "schwab_roth",
    "schwab_ira": "schwab_rollover_ira",
}

CATASTROPHIC_DROP_FRACTION = 0.5
POSITION_COLLAPSE_FRACTION = 0.4
MATERIAL_ACCOUNT_USD = 5_000.0
MATERIAL_CASH_USD = 10_000.0
CASH_EXCLUSION_FRACTION = 0.20

REASON_VALID_COMPLETE = "VALID_COMPLETE"
REASON_EMPTY_PAYLOAD = "EMPTY_PAYLOAD"
REASON_SCHEMA_INVALID = "SCHEMA_INVALID"
REASON_NONFINITE_VALUE = "NONFINITE_VALUE"
REASON_NEGATIVE_VALUE = "NEGATIVE_VALUE"
REASON_INCOMPLETE_ACCOUNTS = "INCOMPLETE_ACCOUNTS"
REASON_CASH_EXCLUDED = "CASH_EXCLUDED"
REASON_POSITION_COUNT_COLLAPSE = "POSITION_COUNT_COLLAPSE"
REASON_CATASTROPHIC_DROP = "CATASTROPHIC_DROP"
REASON_EMERGENCY_FLOOR = "EMERGENCY_FLOOR"


@dataclass
class Validation:
    ok: bool
    reason_code: str
    reason: str
    total: float = 0.0
    position_count: int = 0
    accounts: list[str] = field(default_factory=list)
    missing_accounts: list[str] = field(default_factory=list)
    cash_total: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def as_tuple(self) -> tuple[bool, str]:
        return self.ok, f"{self.reason_code}: {self.reason}"


def _norm_acct(raw: Any) -> str:
    s = str(raw or "").strip()
    return ACCOUNT_ALIASES.get(s, s)


def positions_of(doc: Any) -> list[dict]:
    if not isinstance(doc, dict):
        return []
    pos = doc.get("holdings") or doc.get("positions") or []
    if isinstance(pos, dict):
        pos = list(pos.values())
    return [p for p in pos if isinstance(p, dict)]


def declared_total(doc: Any) -> float:
    if not isinstance(doc, dict):
        return 0.0
    try:
        return float((doc.get("portfolio_totals") or {}).get("total_value") or doc.get("total_value") or 0)
    except (TypeError, ValueError):
        return 0.0


def sum_market_value(pos: list[dict]) -> float:
    total = 0.0
    for p in pos:
        try:
            total += float(p.get("market_value") or p.get("value") or 0)
        except (TypeError, ValueError):
            continue
    return total


def cash_total_of(pos: list[dict]) -> float:
    total = 0.0
    for p in pos:
        sym = str(p.get("symbol") or "").upper()
        if sym == "CASH" or p.get("is_cash"):
            try:
                total += float(p.get("market_value") or p.get("value") or 0)
            except (TypeError, ValueError):
                continue
    return total


def accounts_of(pos: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in pos:
        acct = _norm_acct(p.get("account") or p.get("account_id") or p.get("account_key") or "")
        if not acct:
            continue
        try:
            mv = float(p.get("market_value") or p.get("value") or 0)
        except (TypeError, ValueError):
            mv = 0.0
        out[acct] = out.get(acct, 0.0) + mv
    return out


def _finite_nonnegative(pos: list[dict]) -> tuple[str | None, str]:
    for p in pos:
        for field in ("market_value", "value", "price", "shares", "qty"):
            if field not in p or p.get(field) is None:
                continue
            try:
                v = float(p[field])
            except (TypeError, ValueError):
                return REASON_SCHEMA_INVALID, f"non-numeric {field} on {p.get('symbol')}"
            if not math.isfinite(v):
                return REASON_NONFINITE_VALUE, f"non-finite {field} on {p.get('symbol')}"
            if field in ("market_value", "value", "price") and v < 0:
                # short/option negative MV can be legitimate; shares of cash/equity should not be NaN.
                continue
            if field in ("shares", "qty") and v < 0 and str(p.get("symbol") or "").upper() != "CASH":
                # short inventory is allowed; just reject NaN which is handled above
                continue
        try:
            mv = p.get("market_value")
            if mv is not None and not math.isfinite(float(mv)):
                return REASON_NONFINITE_VALUE, f"non-finite market_value on {p.get('symbol')}"
        except (TypeError, ValueError):
            return REASON_SCHEMA_INVALID, f"bad market_value on {p.get('symbol')}"
    return None, ""


def emergency_floor() -> float | None:
    raw = os.environ.get("HOLDINGS_EMERGENCY_MIN_TOTAL", "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def validate_payload(new_holdings: Any, last_good: Any | None = None) -> Validation:
    """Single validation contract for pre-write and post-write."""
    if not isinstance(new_holdings, dict):
        return Validation(False, REASON_SCHEMA_INVALID, "payload is not a dict")

    pos = positions_of(new_holdings)
    if not pos:
        return Validation(False, REASON_EMPTY_PAYLOAD, "zero positions in payload — refusing to write")

    bad, why = _finite_nonnegative(pos)
    if bad:
        return Validation(False, bad, why, position_count=len(pos))

    declared = declared_total(new_holdings)
    summed = sum_market_value(pos)
    total = declared if declared > 0 else summed
    cash = cash_total_of(pos)
    accts = accounts_of(pos)
    acct_names = sorted(accts)

    floor = emergency_floor()
    if floor is not None and total < floor:
        return Validation(
            False, REASON_EMERGENCY_FLOOR,
            f"total_value {total:,.0f} below emergency floor {floor:,.0f}",
            total=total, position_count=len(pos), accounts=acct_names, cash_total=cash,
        )

    last_pos = positions_of(last_good) if last_good is not None else []
    last_total = 0.0
    last_cash = 0.0
    last_accts: dict[str, float] = {}
    if last_pos:
        last_total = declared_total(last_good) or sum_market_value(last_pos)
        last_cash = cash_total_of(last_pos)
        last_accts = accounts_of(last_pos)

        missing = []
        required = set(REQUIRED_ACCOUNTS)
        for name, mv in last_accts.items():
            if mv >= MATERIAL_ACCOUNT_USD:
                required.add(name)
        for name in sorted(required):
            if name not in accts:
                missing.append(name)
            elif accts[name] <= 0 and last_accts.get(name, 0) >= MATERIAL_ACCOUNT_USD:
                missing.append(name)
        if missing:
            return Validation(
                False, REASON_INCOMPLETE_ACCOUNTS,
                f"missing/empty governed accounts: {', '.join(missing)}",
                total=total, position_count=len(pos), accounts=acct_names,
                missing_accounts=missing, cash_total=cash,
                details={"last_good_accounts": last_accts, "new_accounts": accts},
            )

        if last_cash >= MATERIAL_CASH_USD and cash < CASH_EXCLUSION_FRACTION * last_cash:
            return Validation(
                False, REASON_CASH_EXCLUDED,
                f"cash {cash:,.0f} is < {CASH_EXCLUSION_FRACTION:.0%} of last-good cash {last_cash:,.0f}",
                total=total, position_count=len(pos), accounts=acct_names, cash_total=cash,
                details={"last_good_cash": last_cash},
            )

        if last_total > 0 and total < CATASTROPHIC_DROP_FRACTION * last_total:
            return Validation(
                False, REASON_CATASTROPHIC_DROP,
                f"total {total:,.0f} < {CATASTROPHIC_DROP_FRACTION:.0%} of last-good {last_total:,.0f}",
                total=total, position_count=len(pos), accounts=acct_names, cash_total=cash,
                details={"last_good_total": last_total},
            )

        if len(last_pos) >= 10 and len(pos) < POSITION_COLLAPSE_FRACTION * len(last_pos):
            return Validation(
                False, REASON_POSITION_COUNT_COLLAPSE,
                f"position count {len(pos)} < {POSITION_COLLAPSE_FRACTION:.0%} of last-good {len(last_pos)}",
                total=total, position_count=len(pos), accounts=acct_names, cash_total=cash,
            )

    return Validation(
        True, REASON_VALID_COMPLETE, "ok",
        total=total, position_count=len(pos), accounts=acct_names, cash_total=cash,
        details={"declared_total": declared, "summed_market_value": summed, "last_good_total": last_total},
    )


def file_is_intact(path) -> bool:
    """Non-wipe check for shell wrappers: payload parses and is non-empty.

    Does not apply the historical $1M floor. Relative/coverage guards need last-good.
    """
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return False
    try:
        doc = json.loads(p.read_text())
    except Exception:
        return False
    return validate_payload(doc, None).ok

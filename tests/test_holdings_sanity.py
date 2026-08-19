"""Holdings guard: coverage/relative drop — not a historical $1M floor."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from holdings_sanity import (  # noqa: E402
    REASON_CASH_EXCLUDED,
    REASON_CATASTROPHIC_DROP,
    REASON_EMPTY_PAYLOAD,
    REASON_INCOMPLETE_ACCOUNTS,
    REASON_VALID_COMPLETE,
    validate_payload,
)


def _pos(symbol, account, mv, cash=False):
    return {
        "symbol": "CASH" if cash else symbol,
        "account": account,
        "market_value": mv,
        "is_cash": cash,
        "price": 1.0 if cash else 10.0,
        "shares": mv if cash else mv / 10.0,
    }


def _doc(rows, total=None):
    tot = total if total is not None else sum(r["market_value"] for r in rows)
    return {"holdings": rows, "portfolio_totals": {"total_value": tot}}


LAST_GOOD = _doc([
    _pos("SCHD", "schwab_taxable", 200_000),
    _pos("CASH", "schwab_taxable", 100_000, cash=True),
    _pos("SCHG", "schwab_roth", 150_000),
    _pos("CASH", "schwab_roth", 50_000, cash=True),
    _pos("VTI", "schwab_rollover_ira", 400_000),
    _pos("CASH", "schwab_rollover_ira", 280_000, cash=True),
], total=1_180_000)


def test_complete_sub_million_is_valid():
    # Complete current book at ~$723k (cash included) vs last-good $1.18M is a 39% drop — allowed.
    rows = [
        _pos("SCHD", "schwab_taxable", 120_000),
        _pos("CASH", "schwab_taxable", 80_000, cash=True),
        _pos("SCHG", "schwab_roth", 90_000),
        _pos("CASH", "schwab_roth", 40_000, cash=True),
        _pos("VTI", "schwab_rollover_ira", 250_000),
        _pos("CASH", "schwab_rollover_ira", 143_000, cash=True),
    ]
    v = validate_payload(_doc(rows, total=723_000), LAST_GOOD)
    assert v.ok, v
    assert v.reason_code == REASON_VALID_COMPLETE


def test_cash_excluded_722k_blocked():
    rows = [
        _pos("SCHD", "schwab_taxable", 200_000),
        _pos("SCHG", "schwab_roth", 150_000),
        _pos("VTI", "schwab_rollover_ira", 372_923),
    ]
    v = validate_payload(_doc(rows, total=722_923), LAST_GOOD)
    assert not v.ok
    assert v.reason_code == REASON_CASH_EXCLUDED


def test_missing_account_blocked():
    rows = [
        _pos("SCHD", "schwab_taxable", 200_000),
        _pos("CASH", "schwab_taxable", 100_000, cash=True),
        _pos("SCHG", "schwab_roth", 150_000),
        _pos("CASH", "schwab_roth", 50_000, cash=True),
    ]
    v = validate_payload(_doc(rows, total=500_000), LAST_GOOD)
    assert not v.ok
    assert v.reason_code == REASON_INCOMPLETE_ACCOUNTS
    assert "schwab_rollover_ira" in v.missing_accounts


def test_catastrophic_drop_blocked():
    # Keep cash/account coverage so the relative-total guard is the one that fires.
    rows = [
        _pos("SCHD", "schwab_taxable", 40_000),
        _pos("CASH", "schwab_taxable", 30_000, cash=True),
        _pos("SCHG", "schwab_roth", 30_000),
        _pos("CASH", "schwab_roth", 20_000, cash=True),
        _pos("VTI", "schwab_rollover_ira", 80_000),
        _pos("CASH", "schwab_rollover_ira", 50_000, cash=True),
    ]
    v = validate_payload(_doc(rows, total=250_000), LAST_GOOD)
    assert not v.ok
    assert v.reason_code == REASON_CATASTROPHIC_DROP


def test_empty_payload_blocked():
    v = validate_payload({"holdings": [], "portfolio_totals": {"total_value": 0}}, LAST_GOOD)
    assert v.reason_code == REASON_EMPTY_PAYLOAD


def test_no_static_million_floor_on_first_write():
    rows = [
        _pos("SCHD", "schwab_taxable", 200_000),
        _pos("CASH", "schwab_taxable", 50_000, cash=True),
        _pos("SCHG", "schwab_roth", 200_000),
        _pos("CASH", "schwab_roth", 50_000, cash=True),
        _pos("VTI", "schwab_rollover_ira", 200_000),
        _pos("CASH", "schwab_rollover_ira", 22_923, cash=True),
    ]
    v = validate_payload(_doc(rows, total=722_923), None)
    assert v.ok, v
    assert v.reason_code == REASON_VALID_COMPLETE

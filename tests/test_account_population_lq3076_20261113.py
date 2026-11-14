"""LQ-20261113-3076 (trace A07): one account count, used by the Home Accounts table and the CIO card.

Before: the CIO book line counted only accounts holding a non-cash position (4) while the Home Accounts table
listed every account in the book, a cash-only account included (5), and neither said which it was.
After: ``portfolio_total_contract.account_population`` is the one definition; the portfolio-total contract
(Home) and ``cio_overnight_brief.book_summary`` (CIO card) both call it, and the card names both counts.
Synthetic fixtures only: no DB, no network, no live state.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib import portfolio_total_contract as ptc  # noqa: E402
from scripts.lib import home_cio_card  # noqa: E402

AS_OF = "2026-01-05T21:00:00+00:00"


def _positions_rows() -> list[dict]:
    """positions_current-shaped rows (load_positions_current): five accounts, one of them cash only."""
    rows = []
    for acct, sym in (("syn_a", "AAA"), ("syn_b", "BBB"), ("syn_c", "CCC"), ("syn_d", "DDD")):
        rows.append({"account": acct, "symbol": sym, "qty": 10.0, "market_value": 1000.0, "is_cash": False, "as_of": AS_OF})
        rows.append({"account": acct, "symbol": "CASH", "qty": 50.0, "market_value": 50.0, "is_cash": True, "as_of": AS_OF})
    rows.append({"account": "syn_e", "symbol": "CASH", "qty": 700.0, "market_value": 700.0, "is_cash": True, "as_of": AS_OF})
    return rows


def _holdings_doc() -> dict:
    """The same book as the holdings store Home's portfolio-total contract reads."""
    holdings = []
    for r in _positions_rows():
        holdings.append({"account": r["account"], "symbol": r["symbol"], "shares": r["qty"],
                         "market_value": r["market_value"], "is_cash": r["is_cash"]})
    total = sum(h["market_value"] for h in holdings)
    return {"holdings": holdings, "portfolio_totals": {"total_value": total, "total_cash": 900.0, "as_of": AS_OF}}


def test_account_population_counts_a_cash_only_account_and_names_it():
    pop = ptc.account_population(_positions_rows())
    assert pop["accounts"] == 5
    assert pop["accounts_with_positions"] == 4
    assert pop["cash_only_accounts"] == ["syn_e"]
    assert pop["unnamed_rows"] == 0
    assert pop["definition"] == ptc.ACCOUNTS_DEFINITION and "cash rows included" in pop["definition"]


def test_account_population_edges_zero_quantity_unnamed_and_cash_symbol():
    rows = [
        {"account": "syn_a", "symbol": "AAA", "qty": 0.0, "market_value": 0.0},        # closed: not in the book
        {"account": "syn_b", "symbol": "BBB", "quantity": 3, "market_value": 30.0},
        {"account": "", "symbol": "CCC", "shares": 2, "market_value": 20.0},          # unnamed: counted, not dropped
        {"account_key": "syn_c", "symbol": "SPAXX", "qty": 100.0, "market_value": 100.0},  # money-market symbol = cash
        {"account": " syn_b ", "symbol": "DDD", "market_value": 5.0},   # no quantity field: in the book; its own name
        "not a row",
    ]
    pop = ptc.account_population(rows)
    assert pop["accounts"] == 3, pop          # " syn_b " is a stored name of its own, as in by_account (LQ-3092)
    assert pop["accounts_with_positions"] == 2
    assert pop["cash_only_accounts"] == ["syn_c"]
    assert pop["unnamed_rows"] == 1


def _in_book(by_account: dict) -> int:
    return sum(1 for a in by_account.values() if a["in_book"])


def test_home_contract_and_cio_book_use_the_same_account_count():
    import cio_overnight_brief as brief

    home = ptc.build_portfolio_total(_holdings_doc())
    assert home["account_population"]["accounts"] == 5
    assert sorted(home["by_account"]) == ["syn_a", "syn_b", "syn_c", "syn_d", "syn_e"]
    assert home["account_population"]["accounts"] == _in_book(home["by_account"]) == len(home["by_account"])

    book = brief.book_summary(positions={"rows": _positions_rows(), "as_of": AS_OF}, holdings_doc={}, held={},
                              quotes={}, stops_by_symbol={}, as_of=datetime(2026, 1, 5, 21, 30, tzinfo=timezone.utc))
    assert book["accounts"] == home["account_population"]["accounts"] == 5
    assert book["accounts_with_positions"] == home["account_population"]["accounts_with_positions"] == 4
    assert book["cash_only_accounts"] == ["syn_e"]
    assert book["accounts_definition"] == ptc.ACCOUNTS_DEFINITION
    assert book["positions"] == 4
    assert "4 position(s) in 4 account(s) with positions (5 account(s) in the book; cash only:" in book["line"]


def test_cio_book_line_names_unnamed_rows():
    import cio_overnight_brief as brief

    rows = _positions_rows() + [{"account": None, "symbol": "ZZZ", "qty": 1.0, "market_value": 9.0, "is_cash": False}]
    book = brief.book_summary(positions={"rows": rows, "as_of": AS_OF}, holdings_doc={}, held={}, quotes={},
                              stops_by_symbol={}, as_of=datetime(2026, 1, 5, 21, 30, tzinfo=timezone.utc))
    assert book["accounts"] == 5 and book["accounts_unnamed_rows"] == 1
    assert "1 row(s) with no account name" in book["line"]


def test_card_passes_both_counts_and_never_relabels_a_legacy_brief():
    new = home_cio_card._book_accounts({"accounts": 5, "accounts_with_positions": 4, "cash_only_accounts": ["syn_e"],
                                        "accounts_unnamed_rows": 0, "accounts_definition": ptc.ACCOUNTS_DEFINITION})
    assert new == {"accounts": 5, "accounts_with_positions": 4, "cash_only_accounts": ["syn_e"],
                   "accounts_unnamed_rows": 0, "accounts_definition": ptc.ACCOUNTS_DEFINITION}
    # A brief written before the shared definition: its "accounts" meant "with positions".
    legacy = home_cio_card._book_accounts({"positions": 4, "accounts": 4, "cash": 900.0})
    assert legacy["accounts"] is None
    assert legacy["accounts_with_positions"] == 4
    assert "non-cash position" in legacy["accounts_definition"]


def test_card_book_item_carries_the_counts():
    src = (ROOT / "scripts/lib/home_cio_card.py").read_text()
    assert "**_book_accounts(book)" in src
    assert "accounts=book.get(\"accounts\")" not in src


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_book_accounts_text_ts():
    test = ROOT / "apps/command-center-v3/src/lib/cioCardAccounts.test.ts"
    out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(test)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert " 0 failed" in out.stdout


# ── LQ-20261113-3092 (REVIEW-3086 R1): Home's table and the card count accounts by one rule, on a dirty book too ──
def _doc(rows: list[dict]) -> dict:
    return {"holdings": rows, "portfolio_totals": {"total_value": sum(r.get("market_value") or 0 for r in rows),
                                                   "as_of": AS_OF}}


@pytest.mark.parametrize("rows,accounts,entries,unnamed", [
    # REVIEW-3086 probe 1: an account whose only row is closed (qty 0) is a table entry, not an account
    ([{"account": "A", "symbol": "AAA", "quantity": 5, "market_value": 50.0},
      {"account": "B", "symbol": "BBB", "quantity": 0, "market_value": 0.0}], 1, 2, 0),
    # probe 2: a row with no account name is listed (key ""), counted in unnamed_rows, never an account
    ([{"account": "A", "symbol": "AAA", "quantity": 5, "market_value": 50.0},
      {"account": "", "symbol": "CCC", "quantity": 2, "market_value": 20.0}], 1, 2, 1),
    # probe 3: names are taken exactly as stored, by both (one key space with today_by_account): two entries, two
    ([{"account": "A", "symbol": "AAA", "quantity": 5, "market_value": 50.0},
      {"account": " A ", "symbol": "DDD", "quantity": 1, "market_value": 10.0}], 2, 2, 0),
    # a whitespace-only name is unnamed in both
    ([{"account": "A", "symbol": "AAA", "quantity": 5, "market_value": 50.0},
      {"account": "  ", "symbol": "EEE", "quantity": 1, "market_value": 10.0}], 1, 2, 1),
])
def test_home_table_in_book_entries_equal_the_card_count_on_a_dirty_book(rows, accounts, entries, unnamed):
    home = ptc.build_portfolio_total(_doc(rows))
    pop = home["account_population"]
    assert pop["accounts"] == accounts == _in_book(home["by_account"])
    assert len(home["by_account"]) == entries                       # the table still lists every stored name
    assert pop["unnamed_rows"] == unnamed
    assert all(a["unnamed"] == (not k.strip()) and not (a["unnamed"] and a["in_book"]) for k, a in home["by_account"].items())
    assert home["by_account_sum"] == pytest.approx(home["value"])   # entries still sum to the total


def test_r3_one_quantity_reader_first_readable_field_wins_and_a_short_is_not_counted():
    rows = [{"account": "A", "symbol": "AAA", "quantity": 0, "shares": 5, "market_value": 50.0},   # quantity read first
            {"account": "B", "symbol": "BBB", "qty": -3, "market_value": -30.0},                   # a short
            {"account": "C", "symbol": "CCC", "broker_shares": 2, "market_value": 20.0}]
    pop = ptc.account_population(rows)
    assert pop["accounts"] == 1 and pop["cash_only_accounts"] == []
    by = ptc.accounts_from_rows(rows)
    assert {k for k, a in by.items() if a["in_book"]} == {"C"}
    assert "short" in ptc.ACCOUNTS_DEFINITION and "exactly as stored" in ptc.ACCOUNTS_DEFINITION


def test_r4_a_cash_balance_at_quantity_zero_keeps_its_account_in_the_book():
    rows = [{"account": "A", "symbol": "AAA", "qty": 5, "market_value": 50.0, "is_cash": False},
            {"account": "B", "symbol": "CASH", "qty": 0, "market_value": 500.0, "is_cash": True},
            {"account": "Z", "symbol": "CASH", "qty": 0, "market_value": 0.0, "is_cash": True}]   # empty: not in book
    pop = ptc.account_population(rows)
    assert pop["accounts"] == 2 and pop["cash_only_accounts"] == ["B"]
    assert {k: a["in_book"] for k, a in ptc.accounts_from_rows(rows).items()} == {"A": True, "B": True, "Z": False}


def test_r5_brief_positions_and_cash_use_the_account_rules_readers():
    import cio_overnight_brief as brief

    rows = [{"account": "A", "symbol": "AAA", "qty": 5.0, "market_value": 500.0, "is_cash": False},
            {"account": "S", "symbol": "SPAXX", "qty": 300.0, "market_value": 300.0, "is_cash": False},  # unflagged
            {"account": "H", "symbol": "HHH", "shares": 2.0, "market_value": 40.0}]                     # holdings shape
    book = brief.book_summary(positions={"rows": rows, "as_of": AS_OF}, holdings_doc={}, held={}, quotes={},
                              stops_by_symbol={}, as_of=datetime(2026, 1, 5, 21, 30, tzinfo=timezone.utc))
    assert book["positions"] == 2 == book["accounts_with_positions"]
    assert book["cash_only_accounts"] == ["S"]
    assert "2 position(s) in 2 account(s) with positions (3 account(s) in the book; cash only:" in book["line"]
    assert "$300 cash" in book["line"]

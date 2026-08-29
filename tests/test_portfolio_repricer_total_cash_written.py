"""`portfolio_totals.total_cash` is written by the repricer too.

The operator's pick was "write total_cash at the source". The first pass wrote
it in `portfolio_loader.load_all_portfolios` — which is *a* source, but not the
one that runs. The 16:10 Mon-Fri cron invokes `portfolio_repricer`, which never
calls the loader and keeps its own `portfolio_totals.update({...})` block with
the identical omission.

The stored document said so plainly and was not read carefully enough:

    last_pipeline_run   2026-08-26T10:30:00   ← written by the loader
    last_repriced       2026-08-28 16:45 ET   ← written by the repricer

Two days apart. The loader fix would not have fired on the next pass, and the
fossil would still have been sitting there Monday morning.

`total_mv_excluded` is the tell: it is in the repricer's update list and has
stayed correct to the cent, while `total_cash`, absent from that list, drifted
to $52,677.32 wrong.
"""
from __future__ import annotations

import copy
import inspect
import json
import re
from pathlib import Path

import pytest

from scripts.portfolio_repricer import _recalc_totals

FOSSIL = 578_107.50
ROW_SUM = 630_784.82

CASH_ROWS = [
    {"symbol": "CASH", "account": "moomoo_taxable_live",  "is_cash": True, "market_value": 500.00},
    {"symbol": "CASH", "account": "alpaca_taxable_live",  "is_cash": True, "market_value": 5_000.00},
    {"symbol": "CASH", "account": "schwab_taxable",       "is_cash": True, "market_value": 37_894.31},
    {"symbol": "CASH", "account": "schwab_roth",          "is_cash": True, "market_value": 1_472.71},
    {"symbol": "CASH", "account": "schwab_rollover_ira",  "is_cash": True, "market_value": 585_917.80},
]


@pytest.fixture()
def book():
    """A book carrying the live fossil, so the test reproduces the real bug."""
    return {
        "as_of": "2026-08-26",
        "holdings": CASH_ROWS + [
            {"symbol": "SCHD", "account": "schwab_rollover_ira", "shares": 10_000.25,
             "market_value": 351_408.81, "cost_basis": 300_000.00, "is_cash": False},
        ],
        "portfolio_totals": {"total_cash": FOSSIL, "as_of": "2026-08-26"},
        # `account_summaries`, not `accounts` — gt is summed from this dict, and
        # an empty one yields total_value 0, which makes total_mv_excluded
        # meaningless. No reported_total, so each account total is derived.
        "account_summaries": {
            "moomoo_taxable_live": {}, "alpaca_taxable_live": {},
            "schwab_taxable": {}, "schwab_roth": {},
            "schwab_rollover_ira": {},
        },
    }


def test_a_reprice_overwrites_the_fossil(book):
    _recalc_totals(book)
    assert book["portfolio_totals"]["total_cash"] != FOSSIL, "the stale value survived"
    assert book["portfolio_totals"]["total_cash"] == ROW_SUM


def test_stored_total_cash_equals_the_row_sum(book):
    _recalc_totals(book)
    rows = [h for h in book["holdings"] if h.get("is_cash")]
    assert book["portfolio_totals"]["total_cash"] == round(
        sum(h["market_value"] for h in rows), 2)


def test_the_write_is_attributed(book):
    _recalc_totals(book)
    totals = book["portfolio_totals"]
    assert totals["total_cash_source"] == "position_rows"
    assert totals["total_cash_written_at"] != "2026-08-26", (
        "written_at must be the time of the write, not the document's stale "
        "as_of — _recalc_totals runs before last_repriced is stamped")


def test_the_gap_closes_after_the_write(book):
    """cash_gap < 1 is the operator's condition for S5 to get a number again."""
    _recalc_totals(book)
    totals = book["portfolio_totals"]
    assert abs(totals["total_cash"] - totals["total_mv_excluded"]) < 1.0


def test_other_totals_keys_are_still_refreshed(book):
    _recalc_totals(book)
    for key in ("total_value", "total_cost", "total_gain", "total_mv_excluded",
                "excluded_count", "day_change", "day_change_pct"):
        assert key in book["portfolio_totals"], key


def test_a_book_with_no_cash_rows_writes_zero_not_the_fossil(book):
    book["holdings"] = [h for h in book["holdings"] if not h.get("is_cash")]
    _recalc_totals(book)
    assert book["portfolio_totals"]["total_cash"] == 0.0


def test_both_writers_agree_on_the_same_book(book):
    """The loader and the repricer must not produce two different numbers."""
    from scripts.portfolio_loader import load_all_portfolios  # noqa: F401
    _recalc_totals(book)
    repriced = book["portfolio_totals"]["total_cash"]
    loader_definition = round(
        sum(float(h.get("market_value") or 0)
            for h in book["holdings"] if h.get("is_cash")), 2)
    assert repriced == loader_definition == ROW_SUM


def test_every_portfolio_totals_writer_writes_total_cash():
    """The test that would have caught the miss.

    Patching one writer proved nothing while a second writer of the same dict
    kept omitting the field. Any new `portfolio_totals.update({...})` site must
    include `total_cash` or this fails and names the file.
    """
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in sorted((root / "scripts").rglob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'\["portfolio_totals"\]\.update\(\{', src):
            depth, i = 0, m.end() - 1
            while i < len(src):
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            # the exact key, with its colon: `total_cash_source` and
            # `total_cash_written_at` both contain "total_cash" as a substring
            # and would satisfy a looser check while the real field is missing.
            if not re.search(r'"total_cash"\s*:', src[m.end():i]):
                line = src[:m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(root)}:{line}")
    assert not offenders, (
        "portfolio_totals writer(s) that never refresh total_cash — the exact "
        "shape of the drift bug: " + ", ".join(offenders))


def test_the_repricer_does_not_call_the_loader():
    """Documents *why* two patches were needed, so nobody merges them later."""
    src = inspect.getsource(__import__("scripts.portfolio_repricer",
                                       fromlist=["x"]))
    # strip comments and docstrings: this file *discusses* load_all_portfolios
    code = re.sub(r"#.*", "", re.sub(r'"""(?:.|\n)*?"""', "", src))
    assert "load_all_portfolios" not in code

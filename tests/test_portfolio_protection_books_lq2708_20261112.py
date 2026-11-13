"""LQ-20261107-2708: one verdict per book. The backend side of the shared protection-books contract.

tests/fixtures/portfolio_protection_books_lq2708.json is also read by the page test
apps/command-center-v3/src/lib/portfolioV002.contract.test.ts. Here each book's raw positions go through
cio_truth.protection_for; the result must be the wire the page test consumes, and stops_protection.summary over that
wire must give the fixture's backend verdict. The page-vs-backend invariants are checked on the fixture itself, so a
book cannot be edited into a split the page would hide. Synthetic fixtures only.
"""
import json
from pathlib import Path

import pytest

from scripts.lib import cio_truth as truth
from scripts.lib import stops_protection as sp

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "tests" / "fixtures" / "portfolio_protection_books_lq2708.json").read_text())
BOOKS = DOC["books"]


@pytest.mark.parametrize("book", BOOKS, ids=[b["name"] for b in BOOKS])
def test_wire_is_protection_for_output(book):
    wire = [{**r, **truth.protection_for(r, broker_available=True)} for r in book["raw"]]
    assert wire == book["wire"], "cio_truth.protection_for changed: regenerate the fixture and re-check the page test"


@pytest.mark.parametrize("book", BOOKS, ids=[b["name"] for b in BOOKS])
def test_summary_verdict_and_one_book_invariants(book):
    got = sp.summary(book["wire"], [])["verdict"]
    assert got == book["expect"]["summary"]
    page = book["expect"]["page"]
    assert not (page == "GAP" and got == "OK"), "page GAP while the backend reads OK"
    assert not (page == "OK" and got != "OK"), "page OK while the backend does not"
    if page != got:
        assert book.get("split"), "an undeclared page/backend split"
        assert page == "UNKNOWN", "a declared split may only be the page reading UNKNOWN"


def test_unpriced_and_zero_value_gap_books_are_counted_on_the_wire():
    by = {b["name"]: b for b in BOOKS}
    for name in ("unpriced_gap_counts", "zero_value_gap_counts"):
        gap = [r for r in by[name]["wire"] if r["protection_state"] == "GAP"]
        assert gap and all(r["protection"]["counted"] is True and r["protection"]["price_missing"] is True for r in gap), name
    known = [r for r in by["known_40_gap_is_listed_not_counted"]["wire"] if r["protection_state"] == "GAP"]
    assert known and known[0]["protection"]["counted"] is False


def test_limits_are_the_registry_contract():
    c = truth.stop_freshness_contract()
    assert c is not None
    assert DOC["stop_read_max_age_s"] == {"session": round(c["open_h"] * 3600), "off_hours": round(c["closed_h"] * 3600)}


def test_r1_value_is_the_config_or_the_safe_fallback():
    path = ROOT / "config" / "protection_verdict.json"
    want = (json.loads(path.read_text())["protection_verdict"]["expired_day_stop_open_session"]
            if path.exists() else "UNKNOWN")
    assert DOC["r1_expired_open_session"] == want

"""A mark that cannot be used must say why it was dropped, not just vanish from R/R.

COVERS = ["scripts/hermes_watchlist_scorer.py"]

The lead's 13:00 ET ruling on LQ-20261107-143 asks for the price source to be a real mark with a
staleness guard and **skip+reason**. cc-deepseek-5's LQ-189 commit (15e21c9b6) supplied the mark —
`resolve_mark` over the newest `market_quotes` / `ticker_prices` row, Finviz first — and made a stale
mark write NULL. What it does not do is record *why*: after that commit a name whose R/R factor was
dropped because its mark is 40 minutes old is indistinguishable, in the run summary and the history
row, from a name that has no target or no stop at all. That is the RE-3 shape the audit standard
forbids — a receipt that cannot tell "cannot see" from "nothing to lose".

Rules pinned here:
  * a fresh mark is the price and needs no reason;
  * a stale mark is not a price → price None, reason "stale_mark";
  * no mark at all → price None, reason "no_mark";
  * a name with no target or no stop has no R/R to lose, so it gets NO note (noise otherwise);
  * the run summary carries the counts and the first 20 affected symbols, and the log line prints them.

Fixtures only; nothing here touches a DB or the network.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_watchlist_scorer as S  # noqa: E402

COVERS = ["scripts/hermes_watchlist_scorer.py"]


def wi(**kw):
    row = {"symbol": "OPLN", "target_price": 42.0, "stop_loss": 30.0}
    row.update(kw)
    return row


def mark(price, *, stale=False):
    return {"price": price, "source": "data_broker:market_quotes", "as_of": "2026-11-06T21:45:00Z",
            "age_s": 600 if not stale else 5400, "live": not stale, "stale": stale}


# ── one row ─────────────────────────────────────────────────────────────────

def test_a_fresh_mark_is_the_price_and_needs_no_reason():
    assert S._marked_price(wi(), mark(34.35)) == (34.35, None)


def test_a_stale_mark_is_not_a_price_and_says_why():
    assert S._marked_price(wi(), mark(34.35, stale=True)) == (None, "stale_mark")


def test_no_mark_at_all_says_so():
    assert S._marked_price(wi(), {"price": None, "source": "none", "stale": True}) == (None, "no_mark")
    assert S._marked_price(wi(), None) == (None, "no_mark")


def test_a_name_without_target_or_stop_gets_no_note():
    """The price is still NULL, but nothing was dropped: an R/R note here would be noise."""
    assert S._marked_price(wi(target_price=None), mark(34.35, stale=True)) == (None, None)
    assert S._marked_price(wi(stop_loss=None), {"price": None, "stale": True}) == (None, None)


# ── the run's note ──────────────────────────────────────────────────────────

def test_the_note_counts_and_names_the_affected_symbols():
    rows = [
        wi(symbol="OPLN"),                                    # stale → noted
        wi(symbol="PTN"),                                     # no mark → noted
        wi(symbol="SDHC"),                                    # fresh → silent
        wi(symbol="RTAC", target_price=None),                 # no R/R to lose → silent
    ]
    marks = {
        "OPLN": mark(34.35, stale=True),
        "PTN": {"price": None, "source": "none", "stale": True},
        "SDHC": mark(9.85),
        "RTAC": mark(5.0, stale=True),
    }
    counts, syms = S._mark_notes(rows, marks)
    assert counts == {"stale_mark": 1, "no_mark": 1}
    assert syms == [{"symbol": "OPLN", "reason": "stale_mark"}, {"symbol": "PTN", "reason": "no_mark"}]


def test_the_note_names_at_most_twenty_symbols_but_counts_every_one():
    rows = [wi(symbol=f"S{i:02d}") for i in range(25)]
    marks = {f"S{i:02d}": mark(10.0, stale=True) for i in range(25)}
    counts, syms = S._mark_notes(rows, marks)
    assert counts == {"stale_mark": 25}
    assert len(syms) == 20


def test_the_run_summary_carries_the_note():
    """Wiring guard: the summary and the printed line are where a reader (page, lane receipt, log) looks."""
    src = inspect.getsource(S.run)
    assert "rr_skipped" in src
    assert "rr_skipped_symbols" in src

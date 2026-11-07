"""A ticker discovery must not mint a security out of an English word (LQ-20261107-110).

Measured 2026-11-07 over 1,310 live news rows: the whole-pattern ``re.IGNORECASE`` on the
"stock SYMBOL" rule produced 67 candidates of which 59 were ordinary words (PRICE 49, SEES 12,
HAS 9, JUMPS 7 …). Those words became watchlist rows, then strategy cards: 170 of the 350
cards classified ``intel_discovery`` have no price bar at all, and 206 of the 221 NULL-price
cards have never had one.

Every fixture here is synthetic — no live symbol, headline or price appears in this file.

Two guarantees:
  * the SYMBOL is matched case-sensitively (a real ticker is printed in capitals); only the
    context word is case-insensitive;
  * a candidate with no price bar in the lookback window is dropped from discovery and named
    in the run's reason, rather than becoming a card that can never be priced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import intel_auto_discovery as IDA  # noqa: E402


# ── the extractor ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "The stock price rose 4% after the close.",
        "The stock sees a second day of gains.",
        "Investors bought right before earnings.",
        "Shares of the company jumped.",
        "Analysts sold after the downgrade.",
        "A stock has no dividend.",
    ],
)
def test_an_english_word_after_a_context_word_is_not_a_ticker(text):
    assert IDA.extract_tickers_from_text(text) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Shares of AAA trade above their 50-day.", ["AAA"]),
        ("Bought BBB yesterday.", ["BBB"]),
        ("the ticker CCC appears here", ["CCC"]),
    ],
)
def test_a_capitalised_symbol_after_the_same_words_is_still_a_ticker(text, expected):
    assert IDA.extract_tickers_from_text(text) == expected


def test_a_cash_tag_is_still_a_ticker():
    assert IDA.extract_tickers_from_text("Watching $ZZZ into the print.") == ["ZZZ"]


def test_the_blacklist_still_applies():
    assert IDA.extract_tickers_from_text("$CEO $ETF") == []


def test_the_context_word_stays_case_insensitive():
    """Only the symbol is case-sensitive; 'BOUGHT' and 'bought' are the same context."""
    assert IDA.extract_tickers_from_text("BOUGHT AAA.") == ["AAA"]
    assert IDA.extract_tickers_from_text("bought BBB.") == ["BBB"]


# ── the price gate ───────────────────────────────────────────────────────────


def test_a_candidate_with_no_price_bar_is_dropped_and_named():
    discoveries = [
        {"symbol": "AAA", "mentions": 3},
        {"symbol": "NOPX", "mentions": 2},
        {"symbol": "BBB", "mentions": 2},
    ]
    kept, dropped = IDA.split_priceable(discoveries, {"AAA", "BBB"})
    assert [d["symbol"] for d in kept] == ["AAA", "BBB"]
    assert [d["symbol"] for d in dropped] == ["NOPX"]


def test_the_run_reports_what_the_scan_dropped(monkeypatch):
    """The count reaches the caller: a drop that only exists in a log tail is not a reason."""
    def fake_scan(days=2, min_mentions=2, *, stats=None):  # noqa: ARG001 -- signature parity
        if stats is not None:
            stats.update({"candidates": 3, "kept": 1, "dropped_no_price": 2,
                          "dropped_symbols": ["NOPX", "QUUX"]})
        return [{"symbol": "AAA", "mentions": 2, "sources": ["news"],
                 "strategy_tags": [], "quality_avg": 70.0}]

    monkeypatch.setattr(IDA, "scan_for_discoveries", fake_scan)
    monkeypatch.setattr(
        IDA, "add_discoveries_to_watchlist",
        lambda d, dry_run=False: {"added": 0, "failed": 0, "failures": [], "discoveries": d[:10]},
    )
    out = IDA.run()
    assert out["dropped_no_price"] == 2
    assert out["dropped_symbols"] == ["NOPX", "QUUX"]


# ── the writer must not count a rolled-back insert as added ──────────────────


class _FakeCursor:
    def __init__(self, fail_on: str):
        self.fail_on = fail_on
        self.statements: list[str] = []

    def execute(self, sql, params=None):  # noqa: ARG002 -- params recorded via sql only
        text = str(sql).strip()
        self.statements.append(text)
        if self.fail_on in text:
            raise RuntimeError("write refused")

    def close(self):
        pass


class _FakeConn:
    def __init__(self, fail_on: str):
        self.cur = _FakeCursor(fail_on)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_a_failed_watchlist_insert_is_not_counted_as_added(monkeypatch):
    conn = _FakeConn(fail_on="INSERT INTO watchlist_items")
    monkeypatch.setattr(IDA, "_get_conn", lambda: conn)
    result = IDA.add_discoveries_to_watchlist(
        [{"symbol": "AAA", "mentions": 3, "sources": ["news"], "strategy_tags": [], "quality_avg": 70.0}],
        dry_run=False,
    )
    assert result["added"] == 0
    assert result["failed"] == 1
    assert result["failures"], "a failure must carry a reason, not just a count"


def test_one_failed_insert_does_not_discard_the_batch(monkeypatch):
    """A bare conn.rollback() in the except branch threw away every earlier insert of the run."""
    conn = _FakeConn(fail_on="portfolio_intelligence_events")
    monkeypatch.setattr(IDA, "_get_conn", lambda: conn)
    result = IDA.add_discoveries_to_watchlist(
        [{"symbol": "BBB", "mentions": 2, "sources": ["news"], "strategy_tags": [], "quality_avg": 60.0}],
        dry_run=False,
    )
    joined = " | ".join(conn.cur.statements)
    assert "INSERT INTO ticker_strategy_classifications" in joined
    assert "INSERT INTO watchlist_items" in joined
    assert "ROLLBACK TO SAVEPOINT" in joined
    assert conn.rollbacks == 0, "a per-statement failure must not roll back the whole batch"
    assert result["added"] == 1
    assert result["failed"] == 1


def test_a_dry_run_writes_nothing(monkeypatch):
    conn = _FakeConn(fail_on="__never__")
    monkeypatch.setattr(IDA, "_get_conn", lambda: conn)
    result = IDA.add_discoveries_to_watchlist(
        [{"symbol": "CCC", "mentions": 3, "sources": ["news"], "strategy_tags": [], "quality_avg": 70.0}],
        dry_run=True,
    )
    assert result["added"] == 0
    assert conn.cur.statements == []

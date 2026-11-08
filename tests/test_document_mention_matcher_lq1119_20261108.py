"""LQ-20261107-1119: take over LQ-1022 (CHANGES from cc-sonnet-1), landed on grok-a's tip f7512791b.

Covers the review's required fixes and today's false tickers (ARR, ETH, SOAR, DRAM).
Names here are the SEC title forms, hand-built. Only synthetic rows, no database.
"""

from __future__ import annotations

from types import SimpleNamespace

import scripts.backfill_document_mentions as B
from lib import document_mentions as DM
from scripts.lib.document_mention_matcher import match_mentions

NAMES = {
    "JKHY": ["JACK HENRY & ASSOCIATES INC"],
    "ARR": ["Armour Residential REIT, Inc."],
    "ETH": ["Grayscale Ethereum Staking Mini ETF"],
    "SOAR": ["SOAR AI, Inc."],
    "ALRM": ["Alarm.com Holdings, Inc."],
    "JACK": ["JACK IN THE BOX INC"],
}

REJECT = [
    "ENHANCED",
    "NASDAQ",
    "GLOBE NEWSWIRE",
    "NEW YORK",
    "YORK",
    "Alarm",
    "Fortitude Family Office LLC",
    "Lands Enterprise AI Partnership",
    "Great Business",
]


def _symbols(text: str, own: str | None = None) -> set[str]:
    return {row["symbol"] for row in match_mentions(text, names=NAMES, own_symbol=own)}


# --- today's false tickers: a bare parenthesised abbreviation never binds --------------------------

def test_abbreviations_in_parentheses_do_not_bind_without_their_name():
    assert _symbols("Annual recurring revenue (ARR) grew 4x this quarter.") == set()
    assert _symbols("Ethereum (ETH) rallied on staking news.") == set()
    assert _symbols("Memory chip makers (DRAM) and peers rose.") == set()
    assert _symbols("Shares soar (SOAR) on the day.") == set()


def test_parenthesised_ticker_binds_only_next_to_its_own_name():
    assert _symbols("Armour Residential REIT, Inc. (ARR) reported.") == {"ARR"}
    assert _symbols("Armour Residential REIT (ARR) reported.") == {"ARR"}


def test_lowercase_parenthetical_never_binds():
    assert _symbols("results (est) and (ai) trends") == set()


def test_cashtag_never_binds_alone():
    assert _symbols("The filing lists $ETH only.") == set()
    assert _symbols("The filing lists $eth only.") == set()
    assert _symbols("Grayscale Ethereum Staking Mini ETF and $ETH rose.") == {"ETH"}


# --- review finding 3: nothing is offered when the filed symbol is not in the text ----------------

def test_lone_hit_is_dropped_when_filed_under_another_symbol():
    assert match_mentions("Jack Henry & Associates reported results.", names=NAMES, own_symbol="ALRM") == []


def test_filed_symbol_named_in_text_decides_the_subject():
    rows = match_mentions("Jack Henry & Associates reported results.", names=NAMES, own_symbol="JKHY")
    assert rows[0]["role"] == "subject"


# --- review finding 1: run() must use names and must write the right rows -------------------------

class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=()):
        return None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return (None,)


class _Conn:
    def __init__(self, rows):
        self._cur = _Cur(rows)

    def cursor(self):
        return self._cur

    def close(self):
        return None


def _no_registry(monkeypatch):
    monkeypatch.setattr("lib.research_identity.load_registry", lambda *a, **k: {})


def test_run_writes_jkhy_and_nothing_for_the_rejected_phrases(monkeypatch):
    docs = [(1, "JKHY", "Jack Henry & Associates (JKHY) expanded.")]
    docs += [(10 + i, "JKHY", phrase) for i, phrase in enumerate(REJECT)]
    written: list[int] = []

    def fake_persist(conn, *, source_table, source_id, rows):
        written.append(source_id)
        return len(rows)

    monkeypatch.setattr(B, "_conn", lambda: _Conn(docs))
    _no_registry(monkeypatch)
    monkeypatch.setattr(DM, "persist", fake_persist)

    stat = B.run("news_articles", 100, True, names=NAMES)
    assert stat["scanned"] == len(docs)
    assert written == [1]
    assert stat["written"] == 1


def test_run_builds_names_from_the_registry_when_not_given(monkeypatch):
    doc = {"mention_names": {"JKHY": ["JACK HENRY & ASSOCIATES INC"]}}
    monkeypatch.setattr(B, "_conn", lambda: _Conn([(2, "JKHY", "Jack Henry & Associates (JKHY) expanded.")]))
    monkeypatch.setattr("lib.research_identity.load_registry", lambda *a, **k: doc)
    monkeypatch.setattr(DM, "persist", lambda conn, **kw: 0)
    stat = B.run("news_articles", 100, False, names=None)
    assert stat["offered"] == 1


def test_run_refuses_when_no_company_names_exist(monkeypatch):
    import scripts.lib.schwab_instrument_evidence as SIE

    monkeypatch.setattr(B, "_conn", lambda: _Conn([]))
    _no_registry(monkeypatch)
    monkeypatch.setattr(SIE, "load", lambda *a, **k: {})
    stat = B.run("news_articles", 100, False, names=None)
    assert stat.get("refused")
    assert stat["scanned"] == 0 and stat["max_id"] is None


def test_run_refusal_makes_the_command_exit_2(monkeypatch):
    refused = {"table": "news_articles", "scanned": 0, "written": 0, "max_id": None,
               "refused": "no company names"}
    monkeypatch.setattr(B, "run", lambda *a, **k: refused)
    monkeypatch.setattr(B, "load_watermarks", lambda: {})
    a = SimpleNamespace(budget_s=0, rescan=True, legacy_matcher=False, apply=False, limit=100)
    stats = {"scanned": 0, "written": 0, "offered": 0, "no_mention": 0, "undecided": 0}
    assert B._run(a, ["news_articles"], stats) == 2

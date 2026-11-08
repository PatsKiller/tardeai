"""LQ-20261107-1022: a document mention binds only when the name and the symbol agree.

Synthetic names only. The desk tagger is not imported.
"""

from __future__ import annotations

from scripts.lib.document_mention_matcher import match_mentions

NAMES = {
    "ALRM": ["Alarm.com Holdings, Inc."],
    "FTCO": ["Fortitude Gold Corporation"],
    "LE": ["Lands' End, Inc."],
    "GEG": ["Great Elm Group, Inc."],
    "ENHA": ["Enhabit, Inc."],
    "NDAQ": ["Nasdaq, Inc."],
    "NYT": ["The New York Times Company"],
    "GL": ["Globe Life Inc."],
    "JACK": ["Jack in the Box Inc."],
    "JKHY": ["Jack Henry & Associates, Inc."],
    "YORW": ["The York Water Company"],
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


def _symbols(text: str) -> set[str]:
    return {row["symbol"] for row in match_mentions(text, names=NAMES)}


def test_boilerplate_and_lookalike_phrases_do_not_bind():
    for phrase in REJECT:
        assert _symbols(phrase) == set(), phrase


def test_jack_henry_associates_binds_jkhy_not_jack():
    rows = match_mentions("Jack Henry & Associates reported results.", names=NAMES)
    assert [row["symbol"] for row in rows] == ["JKHY"]
    assert rows[0]["role"] == "subject"
    assert rows[0]["role_confidence"] == 1.0


def test_ticker_must_be_uppercase_and_beside_the_same_name():
    rows = match_mentions("Jack Henry & Associates (JKHY) expanded.", names=NAMES)
    assert {row["symbol"] for row in rows} == {"JKHY"}
    assert match_mentions("The filing lists $JKHY only.", names=NAMES) == []
    prose = match_mentions("results (est) and (ai) trends", names={"EST": ["Eastern Standard Timekeepers"], "AI": ["Ai Holdings Group"]})
    assert prose == []
    assert match_mentions("results (EST) and (AI) trends", names={"EST": ["Eastern Standard Timekeepers"], "AI": ["Ai Holdings Group"]}) == []


def test_a_foreign_name_is_not_the_subject_of_another_filing():
    rows = match_mentions("Jack Henry & Associates reported.", names=NAMES, own_symbol="AAPL")
    assert rows == []
    agreed = match_mentions("Jack Henry & Associates reported.", names=NAMES, own_symbol="JKHY")
    assert [row["symbol"] for row in agreed] == ["JKHY"]
    assert agreed[0]["role"] == "subject"
    assert agreed[0]["role_confidence"] == 1.0


def test_run_loads_names_from_the_registry_and_writes_jkhy_only():
    from scripts.backfill_document_mentions import run

    registry = {
        "by_symbol": {"JKHY": "g-jkhy", "ALRM": "g-alrm", "NDAQ": "g-ndaq"},
        "entities": {
            "g-jkhy": {"company": "Jack Henry & Associates, Inc."},
            "g-alrm": {"company": "Alarm.com Holdings, Inc."},
            "g-ndaq": {"company": "Nasdaq, Inc."},
        },
    }
    documents = [
        (1, "JKHY", "Jack Henry & Associates (JKHY) reported results."),
        (2, None, "Alarm"),
        (3, None, "NASDAQ"),
        (4, None, "NEW YORK"),
        (5, None, "GLOBE NEWSWIRE"),
        (6, None, "YORK"),
        (7, None, "Fortitude Family Office LLC"),
        (8, None, "Lands Enterprise AI Partnership"),
        (9, None, "Great Business"),
        (10, None, "ENHANCED"),
    ]

    class Cur:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return [None]

        def fetchall(self):
            return documents

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            return None

    written: list[tuple] = []

    def persist_fn(conn, *, source_table, source_id, rows):
        written.append((source_id, [row["symbol"] for row in rows if row.get("role")]))
        return len(written[-1][1])

    stat = run(
        "news_articles", 20, True, mark=0, seed=False, legacy=False, names=None,
        conn=Conn(), registry=registry, persist_fn=persist_fn,
    )
    assert stat["rows_read"] == 10 or stat["scanned"] == 10
    symbols = [sym for _doc, syms in written for sym in syms]
    assert symbols == ["JKHY"]
    assert stat["written"] == 1


def test_undecided_when_two_exact_names_and_no_filed_symbol():
    text = "Jack Henry & Associates and Jack in the Box both reported."
    rows = match_mentions(text, names=NAMES)
    assert {row["symbol"] for row in rows} == {"JKHY", "JACK"}
    assert all(row["role"] is None for row in rows)
    decided = match_mentions(text, names=NAMES, own_symbol="JKHY")
    roles = {row["symbol"]: row["role"] for row in decided}
    assert roles == {"JKHY": "subject", "JACK": "mentioned"}

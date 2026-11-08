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


def test_the_full_name_binds_and_a_bare_ticker_or_parenthetical_does_not():
    """A bare ticker is not a name. (est) and (ai) are not company names either."""
    rows = match_mentions("Jack Henry & Associates (JKHY) expanded.", names=NAMES)
    assert {row["symbol"] for row in rows} == {"JKHY"}
    assert match_mentions("The filing lists $JKHY only.", names=NAMES) == []
    prose = match_mentions("results (est) and (ai) trends", names={"EST": ["Eastern Standard Timekeepers"], "AI": ["Ai Holdings Group"]})
    assert prose == []
    assert match_mentions("results (EST) and (AI) trends", names={"EST": ["Eastern Standard Timekeepers"], "AI": ["Ai Holdings Group"]}) == []


def test_a_one_token_official_name_does_not_bind():
    """Apple Inc. is one content token. Binding that token would match the word anywhere."""
    from scripts.lib.document_mention_matcher import content_tokens, name_agrees

    assert content_tokens("Apple Inc.") == ["apple"]
    assert name_agrees("Apple Inc.", "AAPL", {"AAPL": ["Apple Inc."]}) is False
    assert match_mentions("Apple reported a record quarter.", names={"AAPL": ["Apple Inc."]}) == []


def test_a_foreign_name_is_not_the_subject_of_another_filing():
    rows = match_mentions("Jack Henry & Associates reported.", names=NAMES, own_symbol="AAPL")
    assert rows == []
    agreed = match_mentions("Jack Henry & Associates reported.", names=NAMES, own_symbol="JKHY")
    assert [row["symbol"] for row in agreed] == ["JKHY"]
    assert agreed[0]["role"] == "subject"
    assert agreed[0]["role_confidence"] == 1.0


def test_a_registry_shaped_like_production_needs_symbol_profiles_for_names():
    """The live identity registry has aliases, not company names. Profiles do."""
    from scripts.lib.document_mention_matcher import names_from_profile_rows, names_from_registry

    registry = {
        "by_symbol": {"JKHY": "g-jkhy"},
        "entities": {"g-jkhy": {"aliases": ["JKHY"], "identity_status": "CONFIRMED", "active": True}},
    }
    assert names_from_registry(registry) == {}
    names = names_from_profile_rows([{
        "symbol": "JKHY",
        "description_1s": "Jack Henry & Associates, Inc. operates as a financial technology company.",
    }])
    assert len(names) > 0 and "JKHY" in names
    rows = match_mentions("Jack Henry & Associates, Inc. reported.", names=names)
    assert [row["symbol"] for row in rows] == ["JKHY"]


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


def test_instrument_description_binds_and_run_uses_that_book():
    """An aliases-only registry has no names. run() must read the instrument book.

    Replacing that read with an empty book writes nothing, so this test fails.
    """
    from scripts.backfill_document_mentions import run
    from scripts.lib.document_mention_matcher import names_from_instrument_records
    import scripts.lib.schwab_instrument_evidence as evidence

    records = {"FRSH": {"description": "FRESHWORKS INC A"}, "JKHY": {"description": "JACK HENRY & ASSOCIATES INC"}}
    names = names_from_instrument_records(records)
    assert "FRSH" in names and "JKHY" in names
    assert [row["symbol"] for row in match_mentions("Freshworks Inc A reported.", names=names)] == ["FRSH"]

    registry = {
        "by_symbol": {"JKHY": "g-jkhy"},
        "entities": {"g-jkhy": {"aliases": ["JKHY"], "identity_status": "CONFIRMED", "active": True}},
    }
    documents = [
        (1, "JKHY", "Jack Henry & Associates Inc reported results."),
        (2, "SPCX", "Space Exploration Technologies Corp announced a launch."),
    ]

    class Cur:
        def execute(self, sql, params=None):
            self.sql = sql or ""

        def fetchone(self):
            return [None]

        def fetchall(self):
            if "symbol_profiles" in self.sql:
                return [("SPCX", "Space Exploration Technologies Corp. provides launch service.")]
            return documents

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            return None

    original_load = evidence.load
    evidence.load = lambda path=None: {"instruments": records}
    written: list[tuple] = []

    def persist_fn(conn, *, source_table, source_id, rows):
        written.append((source_id, [row["symbol"] for row in rows if row.get("role")]))
        return len(written[-1][1])

    try:
        stat = run(
            "news_articles", 20, True, mark=0, seed=False, legacy=False, names=None,
            conn=Conn(), registry=registry, persist_fn=persist_fn,
        )
    finally:
        evidence.load = original_load
    symbols = [sym for _doc, syms in written for sym in syms]
    assert symbols == ["JKHY", "SPCX"], symbols
    assert stat["written"] == 2


def test_undecided_when_two_exact_names_and_no_filed_symbol():
    text = "Jack Henry & Associates and Jack in the Box both reported."
    rows = match_mentions(text, names=NAMES)
    assert {row["symbol"] for row in rows} == {"JKHY", "JACK"}
    assert all(row["role"] is None for row in rows)
    decided = match_mentions(text, names=NAMES, own_symbol="JKHY")
    roles = {row["symbol"]: row["role"] for row in decided}
    assert roles == {"JKHY": "subject", "JACK": "mentioned"}

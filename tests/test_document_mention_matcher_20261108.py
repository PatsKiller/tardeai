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


def test_ticker_plus_name_binds_and_a_lone_ticker_does_too():
    rows = match_mentions("Jack Henry & Associates (JKHY) expanded.", names=NAMES)
    assert {row["symbol"] for row in rows} == {"JKHY"}
    lone = match_mentions("The filing lists $JKHY only.", names=NAMES)
    assert [row["symbol"] for row in lone] == ["JKHY"]


def test_undecided_when_two_exact_names_and_no_filed_symbol():
    text = "Jack Henry & Associates and Jack in the Box both reported."
    rows = match_mentions(text, names=NAMES)
    assert {row["symbol"] for row in rows} == {"JKHY", "JACK"}
    assert all(row["role"] is None for row in rows)
    decided = match_mentions(text, names=NAMES, own_symbol="JKHY")
    roles = {row["symbol"]: row["role"] for row in decided}
    assert roles == {"JKHY": "subject", "JACK": "mentioned"}

"""LQ-20261107-411: a place name must never bind an issuer, however it was narrowed.

Measured on the live spine 2026-11-07: 240 `document_mentions` rows with
`matched_via='company_name'` and a `matched_text` beginning "York" or "Las Vegas".
Two symbols carried almost all of them — YSS (York Space Systems) and LVS (Las Vegas
Sands) — and both symbols are real, which is what made the rows hard to see. The
texts were "York City", "York University", "Las Vegas Review-Journal", "Las Vegas
Raiders Week", and a bare "YORK" or "Las Vegas" in prose.

The mechanism is `company_name_index.resolve_name`'s progressive-prefix narrowing:
the query is shortened until one instrument matches, and the stoplist in
`inbound_identity_tagger` was checked against the words the TEXT contained, never
against the words that finally MATCHED. "Las Vegas Sands" is a company; "LAS VEGAS"
is a place; the matcher accepted both.

Fixtures are synthetic: the instrument feed is a stub, the registry is a stub, and
no holdings or prices appear anywhere. Descriptions mirror the live feed's shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import lib.company_name_index as C  # noqa: E402
import lib.non_issuer_phrases as N  # noqa: E402
from lib import document_mentions as DM  # noqa: E402
from lib import inbound_identity_tagger as T  # noqa: E402

#: The three symbols the live bug reached, with the live feed's descriptions
#: (Schwab instrument sweep). Placeholder CUSIPs — not real identifiers.
FEED = {
    "LVS": {"description": "LAS VEGAS SANDS CORP", "identifiers": {"cusip": "TEST00411"}},
    "YSS": {"description": "YORK SPACE SYS INC", "identifiers": {"cusip": "TEST00412"}},
    "NYT": {"description": "NEW YORK TIMES CO A", "identifiers": {"cusip": "TEST00413"}},
}

REG = {
    "entities": {
        "s-lvs": {"ticker_alias": "LVS", "aliases": ["LVS"], "subject_guid": "s-lvs",
                  "security_guid": "s-lvs", "issuer_guid": "i-lvs",
                  "identity_status": "CONFIRMED"},
        "s-yss": {"ticker_alias": "YSS", "aliases": ["YSS"], "subject_guid": "s-yss",
                  "security_guid": "s-yss", "issuer_guid": "i-yss",
                  "identity_status": "CONFIRMED"},
        "s-nyt": {"ticker_alias": "NYT", "aliases": ["NYT"], "subject_guid": "s-nyt",
                  "security_guid": "s-nyt", "issuer_guid": "i-nyt",
                  "identity_status": "CONFIRMED"},
    },
    "by_symbol": {"LVS": "s-lvs", "YSS": "s-yss", "NYT": "s-nyt"},
}


@pytest.fixture(autouse=True)
def _stub_feed(monkeypatch):
    monkeypatch.setattr(C, "_instruments", lambda: FEED)
    C.refresh()
    yield
    C.refresh()


def _bound(result) -> set[str]:
    return {r["symbol"] for r in result["resolved"]}


# ── the place alone ────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["York", "YORK", "york", "York.", "  York  "])
def test_a_bare_place_name_resolves_to_nothing(name):
    assert C.resolve_name(name) is None


@pytest.mark.parametrize("name", ["Las Vegas", "LAS VEGAS", "las vegas", "Las Vegas."])
def test_a_bare_two_word_place_name_resolves_to_nothing(name):
    assert C.resolve_name(name) is None


# ── the place plus prose: narrowing must not stop on the place ─────────────

@pytest.mark.parametrize("text", [
    "York City Council approved the plan.",
    "York University published the study.",
    "The Las Vegas Review-Journal reported the filing.",
    "Analysts are in Las Vegas for the Raiders Week event.",
    "YORK",
])
def test_prose_around_a_place_name_does_not_bind_the_issuer(text):
    r = T.tag_inbound(text, registry=REG)
    assert "YSS" not in _bound(r)
    assert "LVS" not in _bound(r)
    # RESIDUAL, disclosed in the DONE note: the tagger records the place as an
    # UNRESOLVED mention, because its own stoplist (`NON_ISSUER_PHRASES` in
    # inbound_identity_tagger) does not carry "york"/"las vegas" yet — that file is
    # under another session's claim. A false gap is noise; a false SYMBOL is the
    # defect, and the symbol is what this item removes. The one-line follow-up is
    # in the note: the tagger imports `lib.non_issuer_phrases`.


def test_the_guard_is_what_stops_the_binding(monkeypatch):
    """Without the place check these texts resolve — the fixtures are not empty."""
    monkeypatch.setattr(C, "is_non_issuer_phrase", lambda text: False)
    assert C.resolve_name("York")["symbol"] == "YSS"
    assert C.resolve_name("Las Vegas")["symbol"] == "LVS"
    assert C.resolve_name("York City")["symbol"] == "YSS"
    assert C.resolve_name("Las Vegas Review-Journal")["symbol"] == "LVS"


# ── controls: a real issuer whose name STARTS with a place still resolves ──

@pytest.mark.parametrize("name,symbol", [
    ("Las Vegas Sands", "LVS"),
    ("LAS VEGAS SANDS CORP", "LVS"),
    ("Las Vegas Sands analyst note", "LVS"),
    ("York Space Systems", "YSS"),
    ("YORK SPACE SYS INC", "YSS"),
    ("New York Times", "NYT"),
    ("New York Times Co", "NYT"),
    ("NEW YORK TIMES CO A", "NYT"),
])
def test_a_real_issuer_named_after_a_place_still_resolves(name, symbol):
    """The check runs on the matched width, not on the words it shares with a place."""
    hit = C.resolve_name(name)
    assert hit is not None and hit["symbol"] == symbol


def test_a_real_issuer_still_binds_next_to_a_place_in_the_same_text():
    r = T.tag_inbound("Las Vegas Sands will present in Las Vegas next week.", registry=REG)
    assert "LVS" in _bound(r)


# ── the cleanup API: name the reason for a stored row ──────────────────────

@pytest.mark.parametrize("text,phrase", [
    ("Las Vegas", "las vegas"),            # the name as written IS the place
    ("LAS VEGAS.", "las vegas"),
    ("YORK", "york"),
    ("York City", "york"),                 # narrowed onto the place
    ("York University", "york"),
    ("Las Vegas Review-Journal", "las vegas"),
    ("Las Vegas Raiders Week", "las vegas"),
    ("Nasdaq", "nasdaq"),                  # exchange, same vocabulary
    ("GLOBE NEWSWIRE", "globe newswire"),
])
def test_non_issuer_match_names_the_phrase_a_stored_row_rests_on(text, phrase):
    """The purge rule needs the reason, not just `resolve_name() is None` — the
    existing one refuses 0 of the 240 stored rows (measured 2026-11-07)."""
    assert C.non_issuer_match(text) == phrase
    assert C.resolve_name(text) is None


@pytest.mark.parametrize("text", [
    "Las Vegas Sands", "Las Vegas Sands Corp", "Las Vegas Sands analyst note",
    "York Space Systems", "YORK SPACE SYS INC", "New York Times",
    "Nasdaq Inc", "Visa", "", None,
])
def test_a_name_that_is_kept_is_never_named_a_place(text):
    """No row the matcher still produces may be selected for cleanup."""
    assert C.non_issuer_match(text) is None


# ── the cleanup rule the operator's purge tool applies ─────────────────────

def test_the_purge_rule_refuses_a_place_match():
    """Measured 2026-11-07: today's rule refuses 0 of the 240 stored york/las-vegas rows, so the
    operator's purge tool would have had nothing to archive for this defect."""
    assert (DM.false_positive_reason("Las Vegas", "LVS", "company_name",
                                     text="Analysts gathered in Las Vegas this week.")
            == "non_issuer_phrase:las vegas")


def test_the_purge_rule_refuses_a_narrowed_place_match():
    assert (DM.false_positive_reason("Las Vegas Review-Journal", "LVS", "company_name",
                                     text="The Las Vegas Review-Journal reported the filing.")
            == "non_issuer_phrase:las vegas")


def test_context_does_not_save_a_place_match():
    """`own_symbol` and the surrounding text only ever ALLOW the ambiguity rules. A place is not a
    company in context either, so this rule returns before that gate."""
    why = DM.false_positive_reason("Las Vegas", "LVS", "company_name",
                                   text="Las Vegas Sands will present in Las Vegas next week.",
                                   own_symbol="LVS")
    assert why == "non_issuer_phrase:las vegas"


@pytest.mark.parametrize("name,symbol,text", [
    ("Las Vegas Sands", "LVS", "Las Vegas Sands reported quarterly results."),
    ("York Space Systems", "YSS", "York Space Systems won the contract."),
])
def test_the_purge_rule_keeps_a_real_issuer_whose_name_starts_with_a_place(name, symbol, text):
    assert DM.false_positive_reason(name, symbol, "company_name", text=text) is None


def test_a_ticker_alias_match_is_untouched():
    assert DM.false_positive_reason("LVS", "LVS", "ticker_alias", text="LVS rose 2% today.") is None


# ── the vocabulary is one vocabulary ───────────────────────────────────────

def test_shared_vocabulary_covers_the_tagger_stoplist():
    """`inbound_identity_tagger` still carries its own copy; it must be a subset.

    When the tagger starts importing `lib.non_issuer_phrases`, this test keeps the
    same meaning: the phrase that its doors check is the phrase this index checks.
    """
    assert T.NON_ISSUER_PHRASES <= N.NON_ISSUER_PHRASES


def test_the_two_phrases_this_item_added_are_in_the_shared_set():
    assert "york" in N.NON_ISSUER_PHRASES
    assert "las vegas" in N.NON_ISSUER_PHRASES


@pytest.mark.parametrize("text", ["YORK", "York", " york ", "Las Vegas", "LAS VEGAS.",
                                  "LAS   VEGAS", "Nasdaq", "New York"])
def test_phrase_test_ignores_case_spacing_and_trailing_punctuation(text):
    assert N.is_non_issuer_phrase(text)


@pytest.mark.parametrize("text", ["Las Vegas Sands", "York Space SYS", "New York Times",
                                  "Nasdaq Inc", "Visa", "", None])
def test_a_real_issuer_name_is_not_a_place_phrase(text):
    assert not N.is_non_issuer_phrase(text)

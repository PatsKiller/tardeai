"""LQ-20261107-51: wire services, exchanges, places and ordinary words must not bind issuers.
Synthetic text and a synthetic registry only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import document_mentions as DM  # noqa: E402

fp = DM.false_positive_reason


def test_wire_service_exchange_and_place_names_are_refused_by_name():
    """LQ-411: an exchange, wire or place has its own reason, which runs BEFORE the context gate —
    the same unconditional refusal the writer applies. Kept apart from the ordinary-word rows below
    because the two rules are different claims: this one is "the phrase is not a company", that one
    is "a word alone is ambiguous until the text names the symbol"."""
    for name, sym, phrase in [("GLOBE NEWSWIRE", "GL", "globe newswire"), ("Nasdaq", "NDAQ", "nasdaq"),
                              ("NEW YORK", "NYT", "new york"), ("SAN DIEGO", "SJT", "san diego")]:
        text = f"SOMECITY, Jan. 1 -- {name} reported an enhanced, bullish outlook."
        assert fp(name, sym, "company_name", text=text) == f"non_issuer_phrase:{phrase}", name


def test_ordinary_word_names_are_refused_without_context():
    for name, sym in [("Globe", "GL"), ("ACCESS Newswire", "ACCS"), ("ENHANCED", "ENHA"), ("BULLISH", "BLSH"),
                      ("Ideal", "IPWR"), ("Versus", "VS")]:
        text = f"SOMECITY, Jan. 1 -- {name} reported an enhanced, bullish outlook."
        assert fp(name, sym, "company_name", text=text) == "ambiguous_name_without_context", name


def test_finance_prose_phrases_are_refused():
    for name in ("Price Target Raised", "Day Moving Average", "Liquidity Mapping Around", "Price-Driven Insight"):
        assert fp(name, "XXXX", "company_name", text=f"The {name} is critical.") == "prose_phrase_without_context", name


def test_ordinary_word_aliases_are_refused():
    for word in ("News", "Here", "Stock", "Year"):
        assert fp(word, word.upper(), "ticker_alias", text=f"{word} for investors") == "ordinary_word_alias_without_context"


def test_context_allows_an_ambiguous_name():
    assert fp("Globe", "GL", "company_name", text="Globe Life Inc. (GL) rose.") is None          # named as a ticker
    assert fp("ENHANCED", "ENHA", "company_name", text="ENHANCED report", own_symbol="enha") is None  # filed under it
    assert fp("Be", "BE", "ticker_alias", text="Fuel cell maker NYSE: BE gained") is None
    # "Nasdaq" was allowed here until 2026-11-07 (LQ-411). It is an exchange name, and the writer's
    # stoplist refuses it whether or not the text names the ticker; the judge must make the same claim.


def test_context_does_not_save_a_non_issuer_phrase():
    """The name rule returns before the context gate, so naming the symbol cannot rescue the phrase."""
    assert fp("Nasdaq", "NDAQ", "company_name",
              text="Shares of Nasdaq, NASDAQ: NDAQ, rose") == "non_issuer_phrase:nasdaq"
    assert fp("NEW YORK", "NYT", "company_name",
              text="NEW YORK (NYSE: NYT) -- shares rose", own_symbol="NYT") == "non_issuer_phrase:new york"


def test_the_symbol_must_stand_alone_to_count_as_context():
    assert fp("Globe", "GL", "company_name", text="Globe news (GLOW) today") == "ambiguous_name_without_context"


def test_distinctive_names_and_tickers_are_untouched():
    assert fp("Apple", "AAPL", "company_name", text="Apple unveiled a phone") is None
    assert fp("Bloom Energy", "BE", "company_name", text="Bloom Energy won a contract") is None
    assert fp("Morgan Stanley", "MS", "company_name", text="Morgan Stanley estimates") is None
    assert fp("NASDAQ", "NDAQ", "ticker", text="NASDAQ") is None          # ticker matches are a different claim


def test_a_match_must_sit_on_word_boundaries():
    assert fp("Ideal", "IPWR", "company_name", text="An idealistic plan") == "no_word_boundary"


def test_extract_drops_the_false_company_match_but_keeps_the_real_one():
    reg = {
        "entities": {"s-x": {"ticker_alias": "XCOR", "subject_guid": "s-x", "security_guid": "s-x",
                             "issuer_guid": "i-x", "identity_status": "CONFIRMED"}},
        "by_symbol": {"XCOR": "s-x"},
    }
    rows = DM.extract("Acme Widgets (XCOR) said so. GLOBE NEWSWIRE distributed it.", own_symbol="XCOR", registry=reg)
    assert [r["symbol"] for r in rows] == ["XCOR"] and rows[0]["role"] == "subject"


def test_punctuation_in_the_source_does_not_defeat_a_real_name():
    assert fp("Johnson Johnson", "JNJ", "company_name", text="Johnson & Johnson raised guidance") is None
    assert fp("Cohen Steers", "CNS", "company_name", text="Cohen & Steers fund") is None

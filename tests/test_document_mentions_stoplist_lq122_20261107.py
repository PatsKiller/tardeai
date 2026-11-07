"""LQ-20261107-122: exchange, wire-service and place names must never bind an issuer.

Measured on the live spine 2026-11-07 (document_mentions, 24h): NASDAQ bound NDAQ
(686 and 332 rows), GLOBE NEWSWIRE bound GL (494), NEW YORK bound NYT. Jack Henry
bound JACK through a name-prefix match and is NOT covered here: that is the
progressive-prefix narrowing rule in company_name_index, a matcher-policy decision.

Fixtures are synthetic: the instrument feed is a stub, the registry is a stub, and
no holdings or prices appear anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import inbound_identity_tagger as T  # noqa: E402
import lib.company_name_index as C  # noqa: E402

#: Every symbol the buggy path bound is present, so WITHOUT the stoplist these
#: texts resolve. A test that passes with an empty registry proves nothing.
REG = {
    "entities": {
        "s-ndaq": {"ticker_alias": "NDAQ", "aliases": ["NDAQ"], "subject_guid": "s-ndaq",
                   "security_guid": "s-ndaq", "issuer_guid": "i-ndaq",
                   "identity_status": "CONFIRMED"},
        "s-gl": {"ticker_alias": "GL", "aliases": ["GL"], "subject_guid": "s-gl",
                 "security_guid": "s-gl", "issuer_guid": "i-gl",
                 "identity_status": "CONFIRMED"},
        "s-nyt": {"ticker_alias": "NYT", "aliases": ["NYT"], "subject_guid": "s-nyt",
                  "security_guid": "s-nyt", "issuer_guid": "i-nyt",
                  "identity_status": "CONFIRMED"},
        "s-v": {"ticker_alias": "V", "aliases": ["V"], "subject_guid": "s-v",
                "security_guid": "s-v", "issuer_guid": "i-v",
                "identity_status": "CONFIRMED"},
    },
    "by_symbol": {"NDAQ": "s-ndaq", "GL": "s-gl", "NYT": "s-nyt", "V": "s-v"},
}

#: Stub instrument feed. Descriptions mirror the shape of the live feed; the
#: identifiers are placeholders, not real CUSIPs.
FEED = {
    "NDAQ": {"description": "NASDAQ INC", "identifiers": {"cusip": "TEST00001"}},
    "GL": {"description": "GLOBE LIFE INC", "identifiers": {"cusip": "TEST00002"}},
    "NYT": {"description": "NEW YORK TIMES CO A", "identifiers": {"cusip": "TEST00003"}},
    "V": {"description": "VISA INC A", "identifiers": {"cusip": "TEST00004"}},
}


@pytest.fixture(autouse=True)
def _stub_feed(monkeypatch):
    monkeypatch.setattr(C, "_instruments", lambda: FEED)
    C.refresh()
    yield
    C.refresh()


def _bound(result) -> set[str]:
    return {r["symbol"] for r in result["resolved"]}


# ── the three measured failures ────────────────────────────────────────────

def test_nasdaq_does_not_bind_ndaq():
    r = T.tag_inbound("Stocks closed higher on the NASDAQ today.", registry=REG)
    assert "NDAQ" not in _bound(r)
    assert "NASDAQ" not in r["unresolved_mentions"], "an exchange is not a gap either"


def test_wire_service_name_does_not_bind_gl():
    r = T.tag_inbound("GLOBE NEWSWIRE reports the filing this morning.", registry=REG)
    assert "GL" not in _bound(r)


def test_city_name_does_not_bind_nyt():
    r = T.tag_inbound("The announcement came out of NEW YORK on Friday.", registry=REG)
    assert "NYT" not in _bound(r)


def test_the_fixtures_would_bind_without_the_stoplist(monkeypatch):
    """Proof the stoplist is what stops the binding, not an empty registry."""
    monkeypatch.setattr(T, "NON_ISSUER_PHRASES", frozenset())
    assert "NDAQ" in _bound(T.tag_inbound("NASDAQ closed higher.", registry=REG))
    assert "GL" in _bound(T.tag_inbound("GLOBE NEWSWIRE reports.", registry=REG))
    assert "NYT" in _bound(T.tag_inbound("news out of NEW YORK.", registry=REG))


# ── controls: real issuers with the same words in their names still resolve ─

def test_a_real_company_named_nasdaq_inc_still_resolves():
    """The stoplist is exact, whole-phrase. "Nasdaq Inc" is the issuer."""
    r = T.tag_inbound("What is the analyst target for Nasdaq Inc?", registry=REG)
    assert "NDAQ" in _bound(r)


def test_a_real_company_named_by_ticker_still_resolves():
    r = T.tag_inbound("What is the analyst target for $V?", registry=REG)
    assert "V" in _bound(r)


def test_a_real_company_name_still_resolves_next_to_a_stopped_phrase():
    """A stopped phrase in the same text must not swallow a real mention."""
    r = T.tag_inbound("Analysts said Visa rose in NEW YORK trading today.", registry=REG)
    assert "V" in _bound(r)
    assert "NYT" not in _bound(r)


# ── the phrase test itself ─────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "NASDAQ", "nasdaq", "  Nasdaq  ", "NASDAQ.", "GLOBE NEWSWIRE", "globe  newswire",
    "NEW YORK", "New York", "Wall Street", "United States",
])
def test_stopped_phrases_match_case_space_and_trailing_period(text):
    assert T.is_non_issuer_phrase(text)


@pytest.mark.parametrize("text", [
    "Nasdaq Inc", "NASDAQ INC", "New York Life", "Visa", "V", "NDAQ", "New York Times",
    "Global Net Lease", "", None,
])
def test_real_issuers_and_empty_input_are_not_stopped(text):
    assert not T.is_non_issuer_phrase(text or "")

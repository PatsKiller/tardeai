"""Identity tagging must be two-way, not discovery-only.

Audited 2026-09-06: research and news carried subject_guid/issuer_guid, and the
inbound path carried nothing —

    cio_telegram_bot.py             identity_registry=0  subject_guid=0
    telegram_callback_handler.py    identity_registry=0  subject_guid=0
    run_telegram_callback_poller.py identity_registry=0  subject_guid=0

— with inbound messages not stored at all, only a checkpoint of the last
update_id. Asking "Alex, what's the analyst target for Visa?" produced nothing
tagged, nothing persisted, nothing joinable to the research that would answer it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import inbound_identity_tagger as T  # noqa: E402

#: A registry stub — these tests must not depend on which symbols happen to be
#: minted, which is the test-isolation trap AGENTS.md records for resolve_entity.
REG = {
    "entities": {
        "s-v": {"ticker_alias": "V", "aliases": ["V"], "subject_guid": "s-v",
                "security_guid": "s-v", "issuer_guid": "i-v",
                "identity_status": "CONFIRMED"},
        "s-noc": {"ticker_alias": "NOC", "aliases": ["NOC"], "subject_guid": "s-noc",
                  "security_guid": "s-noc", "issuer_guid": "i-noc",
                  "identity_status": "CONFIRMED"},
    },
    # lookup_symbol resolves through `by_symbol`, not by scanning entities.
    "by_symbol": {"V": "s-v", "NOC": "s-noc"},
}


def _tag(text):
    return T.tag_inbound(text, registry=REG)


# ── the operator's actual question ─────────────────────────────────────────

def test_the_operators_question_resolves_and_carries_topics():
    r = _tag("Alex what is the analyst target for $V, latest support and resistance?")
    assert [x["symbol"] for x in r["resolved"]] == ["V"]
    assert r["resolved"][0]["issuer_guid"] == "i-v"
    assert "analyst_target" in r["topics"]
    assert "support_resistance" in r["topics"]


def test_a_bare_ticker_resolves_too():
    r = _tag("Hey Alex how is my NOC position doing and what is the downside risk?")
    assert [x["symbol"] for x in r["resolved"]] == ["NOC"]
    assert set(r["topics"]) >= {"position", "risk"}


# ── the honest gap ─────────────────────────────────────────────────────────

def test_an_unresolvable_name_is_recorded_as_a_gap_not_silently_dropped():
    """Superseded, deliberately: this test used to assert that "Visa" was
    UNRESOLVABLE, because the registry held ticker aliases only. That premise is
    now false — company names resolve through the broker instrument feed — and a
    test whose premise the fix invalidated must be rewritten, not deleted.

    What must still hold is the honest part: a name the FEED does not carry is
    recorded as a measured gap rather than dropped, because pretending the
    question had no subject makes coverage look better than it is.
    """
    r = _tag("Alex what about Nonesuch Holdings?")
    assert r["resolved"] == []
    assert "Nonesuch Holdings" in r["unresolved_mentions"]


def test_the_agent_name_is_not_a_company():
    for r in (_tag("Alex what is up"), _tag("Hey Maria and Steph")):
        assert not r["resolved"]
        for n in ("Alex", "Maria", "Steph", "Hey"):
            assert n not in r["unresolved_mentions"], f"{n} is not a company"


def test_common_uppercase_words_are_not_symbols():
    """Without a stoplist the first question containing CIO or ETF tags a
    security, and every tag after that is suspect."""
    r = _tag("CIO what ETF should I look AT and IS the RSI OK")
    assert r["resolved"] == []


# ── determinism ────────────────────────────────────────────────────────────

def test_no_model_runs_in_the_tagger():
    """Extraction is a regex, resolution is a lookup. A tag written here is
    always deterministic; ambiguity is the advisor's job and it writes CANDIDATE."""
    src = (ROOT / "scripts" / "lib" / "inbound_identity_tagger.py").read_text(encoding="utf-8")
    low = src.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "generate_with_fallback"):
        assert banned not in low


def test_it_writes_nothing():
    src = (ROOT / "scripts" / "lib" / "inbound_identity_tagger.py").read_text(encoding="utf-8")
    for banned in ("INSERT INTO", "UPDATE ", "write_text", "commit()"):
        assert banned not in src


def test_the_same_issuer_is_not_tagged_twice():
    r = _tag("$V and V again")
    assert len(r["resolved"]) == 1


def test_empty_input_is_safe():
    for v in ("", None):
        r = T.tag_inbound(v, registry=REG)
        assert r["resolved"] == [] and r["topics"] == []


def test_output_is_advisory_and_carries_provenance():
    r = _tag("$V target")
    assert r["authority"] == "READ_ONLY_ADVISORY"
    assert r["financial_action"] is False
    assert r["schema"] == "InboundIdentityTag@v1"


# ── company names, resolved through the BROKER FEED ────────────────────────
#
# The operator's constraint: do not invent a ticker-to-name map. The name comes
# from the same authoritative record as the CUSIP. "Visa" resolving to V is a
# lookup against Schwab's instrument feed, not a table someone typed.

def _tag_named(text, monkeypatch):
    import lib.company_name_index as C
    monkeypatch.setattr(C, "_instruments", lambda: {
        "V": {"description": "VISA INC A", "identifiers": {"cusip": "92826C839"}},
        "NOC": {"description": "NORTHROP GRUMMAN COR", "identifiers": {"cusip": "666807102"}},
    })
    C.refresh()
    return T.tag_inbound(text, registry=REG)


def test_a_company_name_now_resolves_to_the_same_issuer_as_its_ticker(monkeypatch):
    """The point of the whole exercise: both spellings land on ONE issuer_guid."""
    by_name = _tag_named("Alex what is the analyst target for Visa?", monkeypatch)
    by_ticker = T.tag_inbound("Alex what is the analyst target for $V?", registry=REG)
    assert by_name["resolved"] and by_ticker["resolved"]
    assert by_name["resolved"][0]["issuer_guid"] == by_ticker["resolved"][0]["issuer_guid"]


def test_the_match_path_is_recorded(monkeypatch):
    """A consumer must be able to tell a deterministic ticker hit from a
    name lookup without re-deriving it."""
    r = _tag_named("What is the target for Visa?", monkeypatch)
    assert r["resolved"][0]["matched_via"] == "company_name"
    assert r["resolved"][0]["matched_text"] == "Visa"
    t = T.tag_inbound("target for $V", registry=REG)
    assert t["resolved"][0]["matched_via"] == "ticker"


def test_a_multiword_company_is_not_split(monkeypatch):
    r = _tag_named("Alex how is my Northrop Grumman position?", monkeypatch)
    assert [x["symbol"] for x in r["resolved"]] == ["NOC"]
    assert "position" in r["topics"]


def test_the_agent_name_is_peeled_off_a_run(monkeypatch):
    """'Alex what is the target for Northrop Grumman' must yield the company,
    not 'Alex'."""
    r = _tag_named("Alex what is the target for Northrop Grumman", monkeypatch)
    assert [x["symbol"] for x in r["resolved"]] == ["NOC"]
    assert not any("Alex" in m for m in r["unresolved_mentions"])


def test_an_unknown_company_is_still_a_measured_gap(monkeypatch):
    r = _tag_named("Alex what about Nonesuch Holdings?", monkeypatch)
    assert r["resolved"] == []
    assert "Nonesuch Holdings" in r["unresolved_mentions"]

"""Operator turns must bind the company they name, in any case, without chrome leaks.

Measured 2026-09-23: 114 of 114 operator turns in seven days stored a NULL
subject_guid. Three shapes, all real turns:

    393  "...hedge play against AI how is sentinel one doing give me the perspective"
    405  "is mcdonalds a good investment on this pullback give perpective"
    367  "is S a good investment"

The any-case pass cut greedy windows from the LEFT, so 393 produced the one
window "how is sentinel one", which opened with a stop word and was skipped
whole. Lone lowercase names were never tried, and every one-letter token was
dropped. These tests pin the fix AND the 09-22 chrome-leak negatives it must not
reopen ("Price" -> TROW, "Data" -> DAIO, ET, ALERT).

No database, no live feed: the instrument feed, house names and word list are
stubbed so the tests run under the CI's pytest+pyyaml install.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import company_name_index as C  # noqa: E402
from lib import inbound_identity_tagger as T  # noqa: E402

TURN_393 = ("I thinking about invested in cyber security as a hedge play against AI "
            "how is sentinel one doing give me the perspective")
TURN_405 = "is mcdonalds a good investment on this pullback give perpective"

FEED = {
    "S": {"description": "SENTINELONE INC A"},
    "NOC": {"description": "NORTHROP GRUMMAN CORP"},
    "MCD": {"description": "MCDONALDS CORP"},
    "WMT": {"description": "WALMART INC"},
    "PERF": {"description": "PERFECT CORP"},
    "DAIO": {"description": "DATA I/O CORP"},
    "TROW": {"description": "T ROWE PRICE GROUP INC"},
    "ET": {"description": "ENERGY TRANSFER LP"},
    "CYSW": {"description": "CYBER SECURITY WORLDWIDE CORP"},
}


def _entity(sym: str) -> dict:
    return {"ticker_alias": sym, "aliases": [sym], "subject_guid": f"s-{sym.lower()}",
            "security_guid": f"s-{sym.lower()}", "issuer_guid": f"i-{sym.lower()}",
            "identity_status": "CONFIRMED"}


REG = {
    "entities": {f"s-{s.lower()}": _entity(s) for s in FEED},
    "by_symbol": {s: f"s-{s.lower()}" for s in FEED},
}


@pytest.fixture(autouse=True)
def _stub_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_instruments", lambda: FEED)
    monkeypatch.setattr(C, "_house_names", lambda: [])
    C.refresh()
    words = tmp_path / "words"
    # Dictionaries list common words lowercase and proper nouns capitalised.
    words.write_text("\n".join([
        "perfect", "data", "price", "hedge", "play", "security", "doing", "good",
        "investment", "pullback", "Walmart", "Northrop",
    ]) + "\n")
    monkeypatch.setenv("TRADEAI_IDENTITY_WORDLIST", str(words))
    T._common_words.cache_clear()
    yield
    C.refresh()
    T._common_words.cache_clear()


def _syms(text: str, **kw) -> list[str]:
    return [r["symbol"] for r in T.tag_inbound(text, registry=REG, **kw)["resolved"]]


# ── the turns that stored NULL ────────────────────────────────────────────

def test_turn_393_binds_sentinelone_through_a_stop_word_led_window():
    assert _syms(TURN_393, operator_text=True) == ["S"]
    # The fix is the windowing, not the operator flag: agent text binds it too.
    assert _syms(TURN_393) == ["S"]


def test_lowercase_multiword_name_inside_a_sentence_binds():
    assert _syms("how is northrop grumman holding up after earnings",
                 operator_text=True) == ["NOC"]


def test_turn_405_lone_lowercase_name_binds_in_operator_text_only():
    assert _syms(TURN_405, operator_text=True) == ["MCD"]
    assert _syms(TURN_405) == []


@pytest.mark.parametrize("text", [
    "is S a good investment",
    "im thinking of buying  S give me the prespective",
    "I want to invest in S what is the prepective",
])
def test_lone_letter_ticker_binds_in_operator_text(text):
    assert _syms(text, operator_text=True) == ["S"]
    assert _syms(text) == []


def test_lone_letter_joined_by_punctuation_never_binds():
    assert _syms("S&P closed up and the P&L is flat", operator_text=True) == []


# ── chrome-leak negatives (09-22) ─────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Price moved above resistance today",
    "the price moved above resistance today",
    "Data unavailable for this symbol",
    "no fresh data Company filings pending",
    "ALERT: quote refresh failed at 16:05 ET",
    "this looks like the perfect swing setup",
])
def test_chrome_and_ordinary_words_do_not_bind(text):
    assert _syms(text, operator_text=True) == []


def test_lone_word_path_fails_closed_without_a_word_list(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_IDENTITY_WORDLIST", str(tmp_path / "missing"))
    T._common_words.cache_clear()
    assert _syms(TURN_405, operator_text=True) == []


def test_single_name_min_len_is_configurable(monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_SINGLE_NAME_MIN_LEN", "20")
    assert _syms(TURN_405, operator_text=True) == []


def test_is_exact_name_refuses_a_prefix_of_a_longer_name():
    assert C.is_exact_name("northrop grumman")
    assert not C.is_exact_name("northrop")


# ── unresolved mentions are recorded, not dropped ─────────────────────────

def test_unregistered_lone_letter_is_recorded_as_unresolved():
    r = T.tag_inbound("is Q a good investment", registry=REG, operator_text=True)
    assert r["resolved"] == []
    assert "Q" in r["unresolved_mentions"]


def test_prefix_only_multiword_window_is_recorded_in_operator_text():
    # "cyber security" opens exactly one stored name without being it: the
    # operator plausibly meant a company the spine cannot confirm. Recorded.
    r = T.tag_inbound(TURN_393, registry=REG, operator_text=True)
    assert [x["symbol"] for x in r["resolved"]] == ["S"]
    assert "cyber security" in r["unresolved_mentions"]
    # Agent text never records these near misses: its prose would flood the list.
    r = T.tag_inbound(TURN_393, registry=REG)
    assert "cyber security" not in r["unresolved_mentions"]

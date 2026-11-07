"""LQ-20261107-191 / RE-6: one exact-symbol matcher for every lane that finds tickers in text.

Synthetic tickers and a synthetic registry only. The cases are the shapes the 11-07 audit measured:
DRS matched inside "cdrs"/"BDRs", T counted for TSX:T and T-Mobile, OVER/WITH scored as tickers,
VIG left UNRESOLVABLE when it was never in the registry.
"""

from __future__ import annotations

import re

import pytest

from lib import symbol_match as sm

REG = {
    "by_symbol": {"ZQX": "g-zqx", "T": "g-t", "ON": "g-on", "BRK.B": "g-brk", "ORPH": "g-orph", "ZQX.W": "g-w",
                  "QVRB": "g-qvrb", "OVER": "g-over", "WITH": "g-with", "UNRZ": "g-unrz"},
    "entities": {"g-zqx": {"guid": "g-zqx", "identity_status": "CONFIRMED"},
                 "g-t": {"guid": "g-t", "identity_status": "CONFIRMED"},
                 "g-on": {"guid": "g-on", "identity_status": "CONFIRMED"},
                 "g-brk": {"guid": "g-brk", "identity_status": "CONFIRMED"},
                 "g-w": {"guid": "g-w", "identity_status": "CONFIRMED"},
                 "g-qvrb": {"guid": "g-qvrb", "identity_status": "CANDIDATE"},
                 # the live shape: words minted from the watchlist feed as UNRESOLVED entities
                 "g-over": {"guid": "g-over", "identity_status": "UNRESOLVED_WITH_REASON"},
                 "g-with": {"guid": "g-with", "identity_status": "UNRESOLVED_WITH_REASON"},
                 "g-unrz": {"guid": "g-unrz", "identity_status": "UNRESOLVED_WITH_REASON"}},
}


# ── mention(): is THIS symbol named in THIS text ───────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "ZQX jumps 12% after guidance raise",
    "Why $ZQX could double",
    "Shares of Zqx Corp (NASDAQ: ZQX) rose",
    "NYSE:ZQX breaks out",
    "ZQX's quarter beat",
])
def test_whole_word_ticker_matches(text):
    assert sm.mentions(text, "ZQX")


@pytest.mark.parametrize("text", [
    "AZQX completes merger",          # inside a longer upper-case word
    "ZQXA launches product",
    "on my radar: the zqx fund",       # case-folded: never a match
    "Exchange lists new cdrs today",   # the DRS / cdrs shape
    "Exchange lists new BDRs today",
])
def test_substrings_and_case_folds_do_not_match(text):
    assert not sm.mentions(text, "ZQX")
    assert not sm.mentions(text, "DRS")


def test_foreign_exchange_prefix_is_another_security():
    assert not sm.mentions("TELUS (TSX:T) beats estimates", "T")
    assert not sm.mentions("Listed as TSX: ZQX in Toronto", "ZQX")
    assert sm.mentions("Listed as NASDAQ: ZQX in New York", "ZQX")


@pytest.mark.parametrize("text", [
    'Zqx Medical, Inc. ("Zqx") (NasdaqGS: ZQX), a medical technology company',   # press-release long forms
    "ZqxRx Limited (NYSE AMERICAN: ZQX) announced",
    "ZqxRx (NYSEAM:ZQX) - Stock Analysis",
    "Zqx Corp (NYSE MKT: ZQX) files 8-K",
    "SOLZQ (OTCPK:ZQX) - Stock Analysis",
    "Stock Market Today: ZQX rises 4%",                                              # prose before a colon
])
def test_us_venue_long_forms_and_prose_colons_are_not_foreign(text):
    assert sm.mentions(text, "ZQX"), sm.mention(text, "ZQX")


@pytest.mark.parametrize("text", ["Zqx Group Ltd. (TASE: ZQX) announced", "Zqx Bhd (KLSE:ZQX) returns",
                                  "Zqx Resources (TSXV:ZQX) rallies", "Zqx SA (ENXTPA:ZQX) guidance"])
def test_foreign_venue_codes_stay_foreign(text):
    assert sm.mention(text, "ZQX")["reason"] == sm.FOREIGN_LISTING


def test_hyphen_and_ampersand_compounds_are_not_the_ticker():
    assert not sm.mentions("T-Mobile adds subscribers", "T")
    assert not sm.mentions("Sell-T rally", "T")
    assert not sm.mentions("S&P 500 closes higher", "P")


def test_single_letter_and_word_tickers_need_a_cashtag_or_the_name():
    v = sm.mention("T stock rallies", "T")
    assert v["matched"] is False and v["reason"] == sm.AMBIGUOUS
    assert sm.mention("$T rallies", "T")["how"] == "cashtag"
    assert sm.mention("T rallies as AT&T lifts outlook", "T", company_names=["AT&T Inc."])["how"] == "company"
    assert not sm.mentions("Turn ON the lights", "ON")
    assert sm.mentions("$ON beats", "ON")


def test_an_all_caps_headline_trusts_only_cashtags_and_names():
    assert not sm.mentions("MARKETS RALLY AS ZQX AND PEERS SURGE ON NEWS", "ZQX")
    assert sm.mentions("MARKETS RALLY AS $ZQX SURGES", "ZQX")


def test_dotted_class_shares_match_exactly():
    assert sm.mentions("BRK.B hits a record", "BRK.B")
    assert not sm.mentions("BRK.BX hits a record", "BRK.B")
    assert not sm.mentions("BRK.B hits a record", "BRK")


def test_empty_inputs_are_no_match_not_an_error():
    assert sm.mention("", "ZQX")["matched"] is False
    assert sm.mention("ZQX up", "")["matched"] is False
    assert sm.mention(None, "ZQX")["matched"] is False


# ── find_symbols(): which universe symbols does a text name ────────────────────────────────


def test_find_symbols_only_returns_universe_members_in_text_order():
    text = "ZQX and $ON lead; OVER WITH PICKS; ZQX again; T-Mobile lags; TSX:T flat"
    assert sm.find_symbols(text, {"ZQX", "ON", "T", "OVER"}) == ["ZQX", "ON"]


def test_find_symbols_never_reads_an_ambiguous_ticker_without_a_cashtag():
    assert sm.find_symbols("ON the move", {"ON"}) == []


# ── registry_status() / partition(): is it a security at all (LQ-188 facet) ─────────────────


def test_registry_status_separates_the_five_answers():
    assert sm.registry_status("zqx", REG) == sm.IN_REGISTRY
    assert sm.registry_status("QVRB", REG) == sm.IN_REGISTRY
    assert sm.registry_status("OVER", REG) == sm.REGISTRY_UNRESOLVED
    assert sm.registry_status("ORPH", REG) == sm.REGISTRY_NO_ENTITY
    assert sm.registry_status("VIGX", REG) == sm.NOT_IN_REGISTRY
    assert sm.registry_status("OVER!", REG) == sm.NOT_A_SYMBOL
    assert sm.registry_status("", REG) == sm.NOT_A_SYMBOL


def test_reasons_match_the_lookup_reasons_lq188_introduced():
    assert sm.NOT_IN_REGISTRY == "symbol_not_in_registry"
    assert sm.REGISTRY_NO_ENTITY == "registry_answered_no_entity"


def test_partition_drops_words_and_keeps_known_unminted_instruments_separately():
    keep, rejected = sm.partition(["ZQX", "OVER", "WITH", "VIGX", "zqx", "ORPH", "UNRZ", "NOPE"], REG,
                                  known_instruments={"VIGX", "UNRZ"})
    assert keep == ["ZQX", "VIGX", "UNRZ"]
    why = {r["symbol"]: r["status"] for r in rejected}
    assert why == {"OVER": sm.REGISTRY_UNRESOLVED, "WITH": sm.REGISTRY_UNRESOLVED,
                   "ORPH": sm.REGISTRY_NO_ENTITY, "NOPE": sm.NOT_IN_REGISTRY}


def test_registry_membership_alone_never_makes_a_word_a_security():
    # 11-07: the scorer's 10:15 batch scored OVER/WITH because they are minted (UNRESOLVED) registry entries.
    keep, _ = sm.partition(["OVER", "WITH"], REG)
    assert keep == []


def test_an_empty_or_unreadable_registry_raises_instead_of_rejecting_everything():
    with pytest.raises(sm.RegistryUnavailable):
        sm.partition(["ZQX"], {"by_symbol": {}, "entities": {}})
    with pytest.raises(sm.RegistryUnavailable):
        sm.registry_status("ZQX", {"by_symbol": "corrupt"})


# ── pg_word_regex(): the ILIKE '%sym%' replacement ─────────────────────────────────────────


@pytest.mark.parametrize("sym,text,hit", [
    ("DRS", "On My Radar: TMX Group cdrs", False),
    ("DRS", "BDRs na B3", False),
    ("DRS", "Leonardo DRS wins Army contract", True),
    ("DRS", "$DRS rips", True),
    ("BRK.B", "BRK.B and BRKXB", True),
    ("BRK.B", "BRKXB only", False),
])
def test_pg_word_regex_is_a_case_sensitive_whole_word(sym, text, hit):
    # Postgres ARE and Python agree on these classes; the value is passed as a parameter, never interpolated.
    pat = sm.pg_word_regex(sym)
    py = pat.replace("[^[:alnum:]_]", r"[^\w]")
    assert bool(re.search(py, text)) is hit


def test_pg_word_regex_refuses_a_non_symbol():
    with pytest.raises(ValueError):
        sm.pg_word_regex("x'; drop")

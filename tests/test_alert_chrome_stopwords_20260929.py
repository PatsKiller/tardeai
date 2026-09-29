"""2026-09-29: alert title chrome must not resolve as tickers.

READY ENTRY ALERT — ADV previously resolved ENTRY + ALERT + ADV because
_STOP had READY but not ENTRY / ALERT. Telegram footers then deep-linked
to /watch/intelligence/ALERT.
"""
from __future__ import annotations

import scripts.lib.operator_subject_resolver as osr


def test_ready_entry_alert_title_resolves_only_adv():
    book = {"ADV", "ALKS", "INHD", "TROW", "DJCO", "ENTRY", "ALERT"}
    title = "READY ENTRY ALERT — ADV"
    syms = osr.symbols_of(osr.resolve_subjects(title, book=book))
    assert "ADV" in syms
    assert "ALERT" not in syms
    assert "ENTRY" not in syms
    assert "READY" not in syms


def test_multi_symbol_entry_alert_chrome_dropped():
    book = {"ADV", "ALKS", "INHD", "ENTRY", "ALERT", "SETUP"}
    title = "READY ENTRY ALERT — ADV/ALKS/INHD"
    syms = set(osr.symbols_of(osr.resolve_subjects(title, book=book)))
    assert syms == {"ADV", "ALKS", "INHD"}


def test_alert_chrome_stopwords_present():
    for tok in ("ENTRY", "ALERT", "SETUP", "TARGET", "LIMIT", "ADVISORY", "INVALIDATION"):
        assert tok in osr._STOP, f"{tok} missing from _STOP"


def test_plain_advisory_sentence_no_false_tickers():
    book = {"ADV", "TARGET", "LIMIT", "SETUP", "ALERT"}
    text = "advisory only — nothing queued; target and limit are not tickers"
    syms = osr.symbols_of(osr.resolve_subjects(text, book=book))
    assert "TARGET" not in syms
    assert "LIMIT" not in syms
    assert "ALERT" not in syms

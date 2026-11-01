"""A ticker that is also a stopword (A, IT, ON, ARE, BE, AN) must still get a dedupe key.

2026-10-26: the analyst-signal run hit ``A`` (Agilent); ``dedupe.normalize_key("A")`` is empty because ``a`` is a
stopword, ``upsert_candidate`` raised DiscoveryInboxError, and three failures opened the n8n breaker for
hermes-analyst-signal-discovery. No DB: the inbox's ``_exec`` seam records the lookup key and stops.
"""

import pytest

from scripts.lib.hermes_discovery import dedupe, inbox


class _Stop(Exception):
    pass


def _capture(monkeypatch):
    seen = {}

    def fake_exec(sql, params=None, fetch=None):
        seen["params"] = params
        raise _Stop

    monkeypatch.setattr(inbox, "_exec", fake_exec)
    return seen


@pytest.mark.parametrize("sym", ["A", "IT", "ON", "ARE", "BE", "AN"])
def test_stopword_ticker_reaches_the_store_keyed_on_its_symbol(monkeypatch, sym):
    assert dedupe.normalize_key(sym) == ""
    seen = _capture(monkeypatch)
    with pytest.raises(_Stop):
        inbox.upsert_candidate("TICKER_CANDIDATE", sym, actor="test")
    assert sym.lower() in seen["params"]


def test_ordinary_ticker_key_unchanged(monkeypatch):
    seen = _capture(monkeypatch)
    with pytest.raises(_Stop):
        inbox.upsert_candidate("TICKER_CANDIDATE", "BRK.B", actor="test")
    assert dedupe.normalize_key("BRK.B") in seen["params"]


def test_a_trend_made_only_of_stopwords_is_still_refused(monkeypatch):
    _capture(monkeypatch)
    with pytest.raises(inbox.DiscoveryInboxError):
        inbox.upsert_candidate("TREND_CANDIDATE", "the and of", actor="test")

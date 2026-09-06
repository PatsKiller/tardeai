"""Every issuer a document mentions, and whether the document is ABOUT it.

Existing tagging was ONE tag per row from the `symbol` column and never read the
body. Measured 2026-09-06: 58% of tagged news articles mention other tickers.

THE DISTINCTION THIS EXISTS FOR

    "Morgan Stanley estimates Apple foldable iPhone could generate…"

mentions MS and NDAQ; the article is ABOUT Apple. Morgan Stanley is the SOURCE of
the estimate. Recording all three as subjects attaches the article to issuers it
is not about and every downstream join inherits it.

`role='mentioned'` is not a lesser tag — "every document that mentions this
issuer" is a legitimate query. It simply must not be confused with "about".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import document_mentions as DM  # noqa: E402

REG = {
    "entities": {
        "s-aapl": {"ticker_alias": "AAPL", "subject_guid": "s-aapl", "security_guid": "s-aapl",
                   "issuer_guid": "i-aapl", "identity_status": "CONFIRMED"},
        "s-ms": {"ticker_alias": "MS", "subject_guid": "s-ms", "security_guid": "s-ms",
                 "issuer_guid": "i-ms", "identity_status": "CONFIRMED"},
        "s-v": {"ticker_alias": "V", "subject_guid": "s-v", "security_guid": "s-v",
                "issuer_guid": "i-v", "identity_status": "CONFIRMED"},
    },
    "by_symbol": {"AAPL": "s-aapl", "MS": "s-ms", "V": "s-v"},
}

APPLE = "Morgan Stanley estimates AAPL foldable iPhone could generate revenue. MS is bullish."


# ── the canonical case ─────────────────────────────────────────────────────

def test_the_filed_symbol_is_the_subject_and_the_rest_are_mentions():
    rows = DM.extract(APPLE, own_symbol="AAPL", registry=REG)
    by = {r["symbol"]: r["role"] for r in rows}
    assert by["AAPL"] == "subject"
    assert by["MS"] == "mentioned", "the source of an estimate is not the subject"


def test_ms_is_never_the_subject_of_that_article():
    """The failure this table prevents. If this ever passes, an Apple article is
    filed under Morgan Stanley and every join inherits it."""
    rows = DM.extract(APPLE, own_symbol="AAPL", registry=REG)
    assert not any(r["symbol"] == "MS" and r["role"] == "subject" for r in rows)


def test_a_single_mention_is_the_subject():
    rows = DM.extract("AAPL announced a buyback.", own_symbol=None, registry=REG)
    assert len(rows) == 1 and rows[0]["role"] == "subject"


# ── the undecidable case is NOT guessed ────────────────────────────────────

def test_several_mentions_and_none_is_the_filed_symbol_stays_undecided():
    """Guessing a subject here is exactly the wrong-issuer error. role=None means
    'the model's residual', and the caller counts it rather than inventing one."""
    rows = DM.extract("AAPL and MS both moved today.", own_symbol="TSLA", registry=REG)
    assert rows and all(r["role"] is None for r in rows)
    assert all(r["role_source"] is None for r in rows)


def test_an_undecided_row_is_never_persisted(monkeypatch):
    class _Cur:
        def __init__(self): self.n = 0; self.rowcount = 1
        def execute(self, *a, **k): self.n += 1
    class _Conn:
        def __init__(self): self._c = _Cur()
        def cursor(self): return self._c
        def commit(self): pass
    conn = _Conn()
    DM.persist(conn, source_table="t", source_id=1,
               rows=[{"role": None, "role_source": None, "symbol": "X",
                      "subject_guid": "s", "issuer_guid": "i"}])
    assert conn._c.n == 0, "an undecided role must not reach the table"


# ── provenance ─────────────────────────────────────────────────────────────

def test_every_decided_row_records_HOW_it_was_decided():
    """Without role_source a model's guess and a deterministic fact are
    indistinguishable a month later, and the model cannot be re-audited."""
    for r in DM.extract(APPLE, own_symbol="AAPL", registry=REG):
        assert r["role_source"] == "deterministic"
        assert r["role_confidence"] is None


# ── sources with no prose ──────────────────────────────────────────────────

def test_a_filing_is_about_its_symbol_without_a_body():
    """sec_form4 rows are transactions ("P", "S"), not prose. Scanning the body
    found 0 mentions in 300 rows and reported them all unmentioned — false: the
    filing IS about that issuer."""
    rows = DM.subject_from_symbol("AAPL", registry=REG)
    assert len(rows) == 1
    assert rows[0]["role"] == "subject" and rows[0]["role_source"] == "deterministic"


def test_form4_never_scans_the_filer_name():
    """`filer_name` is a PERSON. A director's name must not resolve to a company."""
    assert DM.SOURCES["sec_form4"]["text"] == ()
    assert DM.SOURCES["sec_form4"].get("subject_is_own_symbol") is True
    src = (ROOT / "scripts" / "lib" / "document_mentions.py").read_text(encoding="utf-8")
    assert '"filer_name"' not in src.split("SOURCES", 1)[1].split("NO_ISSUER", 1)[0]


def test_an_unregistered_symbol_yields_nothing_rather_than_a_null_tag():
    assert DM.subject_from_symbol("NOSUCH", registry=REG) == []


# ── macro data has no issuer, by design ────────────────────────────────────

def test_macro_sources_are_declared_as_having_no_issuer():
    """FRED series, CPI, unemployment belong to NO company. Forcing a security
    GUID onto them would be the same invented-mapping error the identity work
    exists to prevent, and every join through it would be false."""
    assert "fred_economic_data" in DM.NO_ISSUER_BY_DESIGN
    assert "topic_monitor" in DM.NO_ISSUER_BY_DESIGN


def test_a_no_issuer_source_is_not_extractable():
    """It must be impossible to point the extractor at macro data by accident."""
    for t in DM.NO_ISSUER_BY_DESIGN:
        assert t not in DM.SOURCES


# ── the web/SEC sources this round added ───────────────────────────────────

def test_the_curated_web_research_sources_are_covered():
    """Curation decides whether a finding is worth keeping; identity decides what
    it is ABOUT. Two different questions, and the second is deterministic."""
    for t in ("hermes_external_research", "research_insights"):
        assert t in DM.SOURCES
        assert DM.SOURCES[t]["own_symbol"] == "symbol"


def test_no_model_runs_in_the_extractor():
    src = (ROOT / "scripts" / "lib" / "document_mentions.py").read_text(encoding="utf-8")
    low = src.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "prompt", "generate_with_fallback"):
        assert banned not in low

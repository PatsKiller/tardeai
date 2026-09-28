"""A one-off wider 8-K window for the SEC ingest (operator 2026-09-27): DELL's Q1 FY27 release
(2026-05-28, $51.3B AI backlog) sits outside the 45-day default, so the thesis had no
quarter-over-quarter backlog comparison. ``--since-days`` threads to the events and to the
exhibit fetcher; the default is unchanged. Hermetic."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import sec_filing_documents as sfd  # noqa: E402

FILINGS = [
    {"form": "8-K", "items": "2.02,9.01", "accession_number": "0001571996-26-000039", "filing_date": "2026-09-01", "cik": "1571996"},
    {"form": "8-K", "items": "2.02,9.01", "accession_number": "0001571996-26-000021", "filing_date": "2026-05-28", "cik": "1571996"},
]


def test_default_window_excludes_q1_and_a_wider_window_includes_it():
    today = date(2026, 9, 27)
    narrow = [f["accession_number"] for f in sfd.filings_needing_documents(FILINGS, since_days=45, today=today)]
    wide = [f["accession_number"] for f in sfd.filings_needing_documents(FILINGS, since_days=150, today=today)]
    assert narrow == ["0001571996-26-000039"]
    assert set(wide) == {"0001571996-26-000039", "0001571996-26-000021"}


def test_ingest_threads_since_days_to_the_fetcher():
    import sec_fundamentals_ingest as ing
    src = (ROOT / "scripts" / "sec_fundamentals_ingest.py").read_text(encoding="utf-8")
    assert '"--since-days"' in src and "since_days=int(a.since_days)" in src
    calls = {}

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): pass
        def fetchone(self): return None

    class _Conn:
        def cursor(self): return _Cur()
        def commit(self): calls["commit"] = True
        def rollback(self): calls["rollback"] = True

    def fake_fetch(sym, cik, filings, *, skip=None, fetch_json=None, fetch_text=None, since_days=45, today=None, max_docs=3):
        calls["since_days"], calls["max_docs"] = since_days, max_docs
        return []

    import importlib
    mods = [importlib.import_module(n) for n in ("lib.sec_filing_documents", "scripts.lib.sec_filing_documents")]
    origs = [m.fetch_documents_for_filings for m in mods]
    for m in mods:
        m.fetch_documents_for_filings = fake_fetch
    try:
        out = ing.ingest_documents(_Conn(), "DELL", "1571996", FILINGS, since_days=150, max_docs=6)
    finally:
        for m, o in zip(mods, origs):
            m.fetch_documents_for_filings = o
    assert out == {"filing_documents_new": 0, "filing_facts_new": 0}
    assert calls["since_days"] == 150 and calls["max_docs"] == 6 and calls.get("commit")

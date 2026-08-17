"""SEC provider adapter tests — read-only, no network, injected fakes."""
from __future__ import annotations

import pytest

from financial_senses.sec_provider import SecEdgarProvider
from financial_senses.result import STATUS_OK, STATUS_PARTIAL, STATUS_UNAVAILABLE


class FakeCursor:
    def __init__(self, rows, cols):
        self._rows = rows
        self.description = [(c,) for c in cols]

    def execute(self, query, params):
        return None

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows, cols):
        self._rows = rows
        self._cols = cols

    def cursor(self):
        return FakeCursor(self._rows, self._cols)

    def close(self):
        pass


class BoomConn:
    def cursor(self):
        raise RuntimeError("db down")


def _conn_factory(rows, cols):
    return lambda: FakeConn(rows, cols)


def _cik(symbol):
    return "0000320193" if symbol == "AAPL" else ""


def _submissions_payload():
    return {
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "cik": "320193",
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "4"],
                "filingDate": ["2024-11-01", "2024-08-01", "2024-09-10"],
                "accessionNumber": ["0000320193-24-000001", "0000320193-24-000002", "0000320193-24-000003"],
                "primaryDocument": ["aapl-10k.htm", "aapl-10q.htm", "aapl-4.xml"],
            }
        },
    }


def _facts_payload():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01", "end": "2023-12-31", "val": 383285000000,
                                "fp": "FY", "form": "10-K", "frame": "CY2023", "filed": "2024-02-01",
                            },
                            {
                                "start": "2024-01-01", "end": "2024-12-31", "val": 391035000000,
                                "fp": "FY", "form": "10-K", "frame": "CY2024", "filed": "2025-02-01",
                            },
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01", "end": "2023-12-31", "val": 96995000000,
                                "fp": "FY", "form": "10-K", "frame": "CY2023", "filed": "2024-02-01",
                            },
                            {
                                "start": "2024-01-01", "end": "2024-12-31", "val": 93736000000,
                                "fp": "FY", "form": "10-K", "frame": "CY2024", "filed": "2025-02-01",
                            },
                        ]
                    }
                },
            }
        }
    }


def _fetcher(url: str) -> dict:
    if "company_tickers" in url:
        return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
    if "/submissions/" in url:
        return _submissions_payload()
    if "/companyfacts/" in url:
        return _facts_payload()
    if "/companyconcept/" in url:
        return {"units": {"USD": [{"end": "2024-12-31", "val": 391035000000}]}}
    return {}


def _make_provider(rows=None, cols=None, fetcher=None, cik=None, conn=None):
    return SecEdgarProvider(
        conn_factory=conn if conn is not None else _conn_factory(rows or [], cols or []),
        cik_resolver=cik or _cik,
        fetcher=fetcher or _fetcher,
    )


def test_resolve_cik_ok():
    p = _make_provider()
    r = p.query("sec.resolve_cik", {"symbol": "AAPL"})
    assert r.status == STATUS_OK
    assert r.data["cik"] == "0000320193"


def test_resolve_cik_unknown_symbol():
    p = _make_provider()
    r = p.query("sec.resolve_cik", {"symbol": "ZZZZ"})
    assert r.status == STATUS_PARTIAL
    assert r.data["cik"] is None


def test_resolve_cik_requires_symbol():
    p = _make_provider()
    r = p.query("sec.resolve_cik", {})
    assert r.status == "INVALID_REQUEST"


def test_get_recent_filings():
    p = _make_provider()
    r = p.query("sec.get_recent_filings", {"symbol": "AAPL", "limit": 3})
    assert r.status == STATUS_OK
    assert len(r.data["filings"]) == 3
    assert r.data["filings"][0]["form"] == "10-K"


def test_get_recent_filings_filter_form():
    p = _make_provider()
    r = p.query("sec.get_recent_filings", {"symbol": "AAPL", "form": "4", "limit": 5})
    assert [f["form"] for f in r.data["filings"]] == ["4"]


def test_get_form4_context_reads_store():
    rows = [("John Doe", "P", "2024-09-10", "https://sec.gov/x")]
    p = _make_provider(rows=rows, cols=["filer_name", "transaction_type", "filing_date", "sec_url"])
    r = p.query("sec.get_form4_context", {"symbol": "AAPL"})
    assert r.status == STATUS_OK
    assert r.data["rows"][0]["filer_name"] == "John Doe"


def test_get_form4_context_empty_not_ingested():
    p = _make_provider(rows=[], cols=["filer_name"])
    r = p.query("sec.get_form4_context", {"symbol": "AAPL"})
    assert r.data["state"] == "NOT_INGESTED"


def test_get_13f_context_empty_not_ingested():
    p = _make_provider(rows=[], cols=["institution"])
    r = p.query("sec.get_13f_context", {"symbol": "AAPL"})
    assert r.data["state"] == "NOT_INGESTED"


def test_db_failure_is_unavailable():
    p = _make_provider(conn=BoomConn())
    r = p.query("sec.get_form4_context", {"symbol": "AAPL"})
    assert r.status == STATUS_UNAVAILABLE


def test_fetcher_timeout_is_unavailable():
    def boom(url):
        raise TimeoutError("429")

    p = _make_provider(fetcher=boom)
    r = p.query("sec.get_recent_filings", {"symbol": "AAPL"})
    assert r.status == STATUS_UNAVAILABLE


def test_get_company_facts():
    p = _make_provider()
    r = p.query("sec.get_company_facts", {"symbol": "AAPL"})
    assert r.status == STATUS_OK
    assert "Revenues" in r.data["facts"]


def test_get_filing_metadata():
    p = _make_provider()
    r = p.query("sec.get_filing_metadata", {"symbol": "AAPL"})
    assert r.status == STATUS_OK
    assert r.data["name"] == "Apple Inc."


def test_compare_filing_facts():
    p = _make_provider()
    r = p.query(
        "sec.compare_filing_facts",
        {"cik": "0000320193", "period_a": "2023-12-31", "period_b": "2024-12-31"},
    )
    assert r.status == STATUS_OK
    assert "revenue" in r.data["comparisons"]
    assert r.data["comparisons"]["revenue"]["comparison_status"] == "OK"
    assert r.data["comparisons"]["revenue"]["delta"] != 0


def test_get_decision_evidence():
    rows = [("Vanguard", 1000, 50000, 2.5, "2024-09-30")]
    p = _make_provider(
        rows=rows,
        cols=["institution", "shares", "value_thousands", "change_pct", "report_date"],
    )
    r = p.query("sec.get_decision_evidence", {"symbol": "AAPL"})
    assert r.status == STATUS_OK
    assert "form4" in r.data["evidence"]
    assert "recent_filings" in r.data["evidence"]


def test_malformed_company_facts_does_not_crash():
    def bad_fetcher(url):
        if "companyfacts" in url:
            return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": "not-a-list"}}}}}
        return _fetcher(url)

    p = _make_provider(fetcher=bad_fetcher)
    r = p.query("sec.get_company_facts", {"symbol": "AAPL"})
    assert r.status in (STATUS_OK, STATUS_PARTIAL)


def test_no_cik_symbol_is_not_found_not_not_configured():
    p = _make_provider()
    r = p.query("sec.get_recent_filings", {"symbol": "ZZZZ"})
    assert r.status == STATUS_PARTIAL
    assert r.data["state"] == "NOT_FOUND"
    assert r.status != "NOT_CONFIGURED"


def test_companyconcept_preserves_tag_case():
    from financial_senses import sec_companyfacts_reader as reader

    captured = {}

    def fetcher(url):
        captured["url"] = url
        return {"units": {"USD": [{"end": "2024-12-31", "val": 100}]}}

    reader.get_company_concept("0000320193", "AccountsPayableCurrent", fetcher=fetcher)
    assert "AccountsPayableCurrent" in captured["url"]
    assert "accountspayablecurrent" not in captured["url"]


def test_facts_at_period_preserves_all_candidate_contexts():
    from financial_senses.sec_provider import SecEdgarProvider

    raw = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2024-01-01", "end": "2024-12-31", "val": 100, "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
                            {"start": "2024-01-01", "end": "2024-12-31", "val": 105, "fp": "FY", "form": "10-K/A", "filed": "2025-03-15"},
                        ]
                    }
                }
            }
        }
    }
    out = SecEdgarProvider._facts_at_period(raw, "2024-12-31")
    # Both candidate rows are preserved; selection happens at the pairing layer.
    assert isinstance(out["Revenues"], list)
    assert len(out["Revenues"]) == 2
    assert {r["value"] for r in out["Revenues"]} == {100, 105}


def test_same_end_quarter_and_ytd_ambiguous_not_cross_matched():
    """Same end date carries a QTD and a YTD row in both periods. Two equally
    valid pairings (QTD↔QTD, YTD↔YTD) remain, so the result must be ambiguous
    rather than silently picking one context."""
    from financial_senses.sec_filing_diff import compare_filing_facts, COMPARISON_UNAVAILABLE

    a = {
        "Revenues": [
            {"value": 100.0, "units": "USD", "start": "2026-04-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
            {"value": 200.0, "units": "USD", "start": "2026-01-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    b = {
        "Revenues": [
            {"value": 110.0, "units": "USD", "start": "2025-04-01", "end": "2025-06-30", "fp": "Q2", "form": "10-Q"},
            {"value": 220.0, "units": "USD", "start": "2025-01-01", "end": "2025-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    r = compare_filing_facts(a, b)
    rev = r["comparisons"]["revenue"]
    assert rev["comparison_status"] == COMPARISON_UNAVAILABLE
    assert rev["reason"] == "ambiguous_context"


def test_quarter_pair_single_context_ok():
    """A unique quarter-length pairing across periods compares cleanly."""
    from financial_senses.sec_filing_diff import compare_filing_facts, COMPARISON_OK

    a = {
        "Revenues": [
            {"value": 100.0, "units": "USD", "start": "2026-04-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    b = {
        "Revenues": [
            {"value": 110.0, "units": "USD", "start": "2025-04-01", "end": "2025-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    r = compare_filing_facts(a, b)
    rev = r["comparisons"]["revenue"]
    assert rev["comparison_status"] == COMPARISON_OK
    assert rev["delta"] == 10.0


def test_amended_rows_latest_filed_wins_after_context_equivalence():
    """Two rows in the SAME context (10-K vs 10-K/A): the latest filed wins."""
    from financial_senses.sec_filing_diff import compare_filing_facts

    a = {
        "Revenues": [
            {"value": 100.0, "units": "USD", "start": "2024-01-01", "end": "2024-12-31", "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
            {"value": 105.0, "units": "USD", "start": "2024-01-01", "end": "2024-12-31", "fp": "FY", "form": "10-K/A", "filed": "2025-03-15"},
        ]
    }
    b = {
        "Revenues": [
            {"value": 120.0, "units": "USD", "start": "2023-01-01", "end": "2023-12-31", "fp": "FY", "form": "10-K", "filed": "2024-02-01"},
        ]
    }
    r = compare_filing_facts(a, b)
    rev = r["comparisons"]["revenue"]
    # Both A rows are ANNUAL context; latest filed (105) is selected.
    assert rev["a"] == 105.0
    assert rev["b"] == 120.0


def test_mixed_context_no_clean_pair_unavailable():
    """A period with QTD+YTD vs a period with only YTD leaves the QTD fact
    unmatched, so the result is fail-closed rather than a partial comparison."""
    from financial_senses.sec_filing_diff import (
        compare_filing_facts,
        COMPARISON_UNAVAILABLE,
    )

    a = {
        "Revenues": [
            {"value": 100.0, "units": "USD", "start": "2026-04-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
            {"value": 200.0, "units": "USD", "start": "2026-01-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    b = {
        "Revenues": [
            {"value": 220.0, "units": "USD", "start": "2026-01-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    r = compare_filing_facts(a, b)
    rev = r["comparisons"]["revenue"]
    assert rev["comparison_status"] == COMPARISON_UNAVAILABLE
    assert rev["reason"] == "no_like_for_like_pair"


def test_quarter_only_vs_ytd_only_unavailable():
    """A quarter-only period vs a YTD-only period cannot be compared."""
    from financial_senses.sec_filing_diff import (
        compare_filing_facts,
        COMPARISON_UNAVAILABLE,
    )

    a = {
        "Revenues": [
            {"value": 100.0, "units": "USD", "start": "2026-04-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    b = {
        "Revenues": [
            {"value": 220.0, "units": "USD", "start": "2026-01-01", "end": "2026-06-30", "fp": "Q2", "form": "10-Q"},
        ]
    }
    r = compare_filing_facts(a, b)
    rev = r["comparisons"]["revenue"]
    assert rev["comparison_status"] == COMPARISON_UNAVAILABLE
    assert rev["reason"] == "duration_context_mismatch QUARTERLY vs YTD"

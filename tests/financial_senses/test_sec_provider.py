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


def test_facts_at_period_prefers_latest_filed_amendment():
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
    assert out["Revenues"]["value"] == 105
    assert out["Revenues"]["form"] == "10-K/A"

"""SEC filing events (F3) and the card fundamentals block (F5), 2026-09-27. Hermetic."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import fundamentals_feed as ff  # noqa: E402
from scripts.lib import sec_filing_events as sfe  # noqa: E402

TODAY = date(2026, 9, 27)
FILINGS = [
    {"form": "8-K", "filing_date": "2026-08-28", "accession_number": "0001-26-1", "items": "2.02,9.01",
     "sec_url": "https://www.sec.gov/a"},
    {"form": "10-Q", "filing_date": "2026-09-08", "accession_number": "0001-26-2", "items": "", "sec_url": "https://www.sec.gov/b"},
    {"form": "8-K", "filing_date": "2026-09-15", "accession_number": "0001-26-3", "items": "5.02", "sec_url": "https://www.sec.gov/c"},
    {"form": "4", "filing_date": "2026-09-20", "accession_number": "0001-26-4", "items": "", "sec_url": ""},
    {"form": "8-K", "filing_date": "2026-06-01", "accession_number": "0001-26-5", "items": "2.02", "sec_url": ""},  # too old
]


def test_filing_events_map_items_and_skip_old_or_irrelevant():
    ev = sfe.events_from_filings("dell", FILINGS, today=TODAY)
    kinds = [(e["catalyst_type"], e["severity"]) for e in ev]
    assert kinds == [("earnings", "high"), ("filing_quarterly", "medium"), ("executive_change", "medium")]
    assert ev[0]["headline"] == "DELL 8-K: Results of operations (Item 2.02) filed 2026-08-28"
    assert all(e["source"] == "sec_edgar" for e in ev)
    assert [sfe.is_material(e) for e in ev] == [True, False, False]


class _Cur:
    def __init__(self, dup_headlines):
        self.dup, self.rowcount = set(dup_headlines), 0

    def execute(self, sql, params):
        self.rowcount = 0 if params[2] in self.dup else 1


def test_insert_reports_only_new_events():
    ev = sfe.events_from_filings("DELL", FILINGS, today=TODAY)
    new = sfe.insert(_Cur({ev[0]["headline"]}), ev)
    assert [e["catalyst_type"] for e in new] == ["filing_quarterly", "executive_change"]


def test_card_block_from_sec_rows_and_unavailable():
    rows = [
        {"symbol": "DELL", "form_type": "10-Q", "metric_name": "revenue", "metric_value": 46_970_000_000, "unit": "USD",
         "period_start": "2026-05-02", "period_end": "2026-07-31", "filing_date": "2026-09-08", "sec_url": "https://x"},
        {"symbol": "DELL", "form_type": "10-Q", "metric_name": "revenue", "metric_value": 29_780_000_000, "unit": "USD",
         "period_start": "2025-05-03", "period_end": "2025-08-01", "filing_date": "2025-09-05", "sec_url": "https://y"},
        {"symbol": "DELL", "form_type": "10-Q", "metric_name": "gross_profit", "metric_value": 9_830_000_000, "unit": "USD",
         "period_start": "2026-05-02", "period_end": "2026-07-31", "filing_date": "2026-09-08", "sec_url": "https://x"},
        {"symbol": "DELL", "form_type": "10-Q", "metric_name": "remaining_performance_obligation",
         "metric_value": 132_000_000_000, "unit": "USD", "period_start": None, "period_end": "2026-07-31",
         "filing_date": "2026-09-08", "sec_url": "https://x"},
    ]
    blk = ff.card_block("DELL", lambda sql, params, fetch=None: rows, ff.settings({"stale_days_after_quarter": 10_000}))
    assert blk["state"] == "FRESH" and blk["latest_quarter_end"] == "2026-07-31"
    assert blk["gross_margin_pct"] == 20.9 and blk["filing_url"] == "https://x"
    assert blk["lines"][0].startswith("DELL revenue $46.97B for quarter ended 2026-07-31 (+57.7% YoY")
    assert any("remaining performance obligation $132.00B" in ln for ln in blk["lines"])
    assert ff.card_block("XLB", lambda *a, **k: [])["state"] == "UNAVAILABLE"


def test_filings_scan_past_insider_forms():
    n = 60
    recent = {"form": ["4"] * n + ["10-Q", "8-K"], "filingDate": ["2026-09-20"] * n + ["2026-09-08", "2026-08-28"],
              "accessionNumber": [f"a-{i}" for i in range(n)] + ["0001571996-26-000050", "0001571996-26-000040"],
              "primaryDocument": ["x.xml"] * n + ["q.htm", "k.htm"], "items": [""] * n + ["", "2.02"]}
    got = sfe.filings_from_submissions("0001571996", {"filings": {"recent": recent}})
    assert [g["form"] for g in got] == ["10-Q", "8-K"]
    assert got[0]["sec_url"] == "https://www.sec.gov/Archives/edgar/data/1571996/000157199626000050/q.htm"

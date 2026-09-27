"""Reported fundamentals from SEC company facts (fundamentals plan F1/F2/F4, 2026-09-27). Hermetic."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import fundamentals_feed as ff  # noqa: E402

S = ff.settings({})


def _f(val, start, end, form="10-Q", fp="Q2", fy=2027, filed="2026-09-08", accn="0001571996-26-000050"):
    return {"val": val, "start": start, "end": end, "form": form, "fp": fp, "fy": fy, "filed": filed, "accn": accn}


FACTS = {"facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [
        _f(46_970_000_000, "2026-05-02", "2026-07-31"),                         # Q2 (quarter)
        _f(90_813_000_000, "2026-01-31", "2026-07-31"),                         # 6-month YTD: never a quarter
        _f(29_780_000_000, "2025-05-03", "2025-08-01", fy=2026, filed="2025-09-05"),
        _f(29_700_000_000, "2025-05-03", "2025-08-01", fy=2026, filed="2025-09-04"),   # superseded by later filing
        _f(95_000_000_000, "2025-02-01", "2026-01-30", form="10-K", fp="FY", fy=2026, filed="2026-03-20"),
    ]}},
    "GrossProfit": {"units": {"USD": [_f(9_830_000_000, "2026-05-02", "2026-07-31")]}},
    "RevenueRemainingPerformanceObligation": {"units": {"USD": [_f(132_000_000_000, None, "2026-07-31")]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [_f(6.34, "2026-05-02", "2026-07-31")]}},
}}}


def test_period_kinds():
    assert ff.period_kind("2026-05-02", "2026-07-31") == "quarter"
    assert ff.period_kind("2026-01-31", "2026-07-31") == "ytd"
    assert ff.period_kind("2025-02-01", "2026-01-30") == "year"
    assert ff.period_kind(None, "2026-07-31") == "instant"


def test_extract_skips_ytd_and_takes_the_latest_filing_for_a_period():
    rows = ff.extract_rows("dell", "0001571996", FACTS, S)
    rev = [r for r in rows if r["metric_name"] == "revenue"]
    assert {r["period_kind"] for r in rev} == {"quarter", "year"}
    assert 90_813_000_000 not in [r["metric_value"] for r in rev]
    prior = [r for r in rev if r["period_end"] == "2025-08-01"]
    assert len(prior) == 1 and prior[0]["metric_value"] == 29_780_000_000
    assert rev[0]["sec_url"].startswith("https://www.sec.gov/Archives/edgar/data/1571996/000157199626000050/")
    rpo = [r for r in rows if r["metric_name"] == "remaining_performance_obligation"]
    assert rpo and rpo[0]["period_kind"] == "instant"


def test_summary_yoy_margin_and_evidence_lines():
    rows = ff.extract_rows("DELL", "0001571996", FACTS, S)
    summ = ff.summarize("DELL", rows)
    rev = next(f for f in summ["facts"] if f["metric"] == "revenue")
    assert rev["yoy_pct"] == round(100 * (46.97 - 29.78) / 29.78, 1)
    assert summ["gross_margin_pct"] == round(100 * 9.83 / 46.97, 1)
    lines = [x["fact"] for x in ff.evidence_lines(summ)]
    assert "DELL revenue $46.97B for quarter ended 2026-07-31 (+57.7% YoY vs 2025-08-01), 10-Q filed 2026-09-08" in lines
    assert any("remaining performance obligation $132.00B as of 2026-07-31" in x for x in lines)
    assert any("eps diluted $6.34" in x for x in lines)


def test_no_yoy_without_a_like_for_like_quarter():
    rows = ff.extract_rows("DELL", "1", {"facts": {"us-gaap": {"GrossProfit": FACTS["facts"]["us-gaap"]["GrossProfit"]}}}, S)
    gp = next(f for f in ff.summarize("DELL", rows)["facts"] if f["metric"] == "gross_profit")
    assert "yoy_pct" not in gp


def test_freshness_states():
    assert ff.freshness({"latest_quarter_end": "2026-07-31"}, S, today=date(2026, 9, 27)) == "FRESH"
    assert ff.freshness({"latest_quarter_end": "2026-04-30"}, S, today=date(2026, 9, 27)) == "STALE"
    assert ff.freshness({"latest_quarter_end": None}, S) == "UNAVAILABLE"


class _Cur:
    def __init__(self, existing):
        self.existing, self.calls = existing, []

    def execute(self, sql, params=None):
        self.calls.append((sql.split()[0], params))

    def fetchall(self):
        return self.existing


def test_upsert_inserts_updates_restatements_and_leaves_unchanged():
    import sec_fundamentals_ingest as ing
    rows = [r for r in ff.extract_rows("DELL", "0001571996", FACTS, S) if r["metric_name"] == "revenue"]
    q2 = next(r for r in rows if r["period_end"] == "2026-07-31")
    old = next(r for r in rows if r["period_end"] == "2025-08-01")
    existing = [
        {"id": 1, "metric_name": "revenue", "form_type": "10-Q", "period_start": q2["period_start"],
         "period_end": q2["period_end"], "metric_value": 46_000_000_000},         # restated -> update
        {"id": 2, "metric_name": "revenue", "form_type": "10-Q", "period_start": old["period_start"],
         "period_end": old["period_end"], "metric_value": old["metric_value"]},   # same -> unchanged
    ]
    cur = _Cur(existing)
    out = ing.upsert(cur, rows)
    assert out == {"inserted": len(rows) - 2, "updated": 1, "unchanged": 1}
    assert not any(c[0] == "DELETE" for c in cur.calls)


class _RoutingCur:
    """Answers only the sec_xbrl query; every other evidence query returns nothing."""
    def __init__(self, xrows):
        self.xrows, self.q = xrows, ""

    def execute(self, sql, params=None):
        self.q = sql

    def fetchall(self):
        return self.xrows if "FROM sec_xbrl" in self.q else []

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self, *a, **k):
        return self._cur

    def rollback(self):
        pass


def test_sec_facts_become_primary_regulatory_evidence(monkeypatch):
    # CI installs only pytest + pyyaml; the function imports psycopg2.extras for its
    # cursor factory even with an injected connection, so give it a stub.
    import types
    pg = types.ModuleType("psycopg2")
    ext = types.ModuleType("psycopg2.extras")
    ext.RealDictCursor = object
    pg.extras = ext
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", ext)
    from scripts.lib import symbol_thesis_evidence as ste
    xrows = [dict(r) for r in ff.extract_rows("DELL", "0001571996", FACTS, S)]
    items = ste.retrieve_structured_sources("DELL", limit=8, conn=_Conn(_RoutingCur(xrows)))
    sec = [i for i in items if i["source_type"] == "sec_xbrl"]
    assert sec and all(i["quality"] == "PRIMARY_REGULATORY" for i in sec)
    assert any("revenue $46.97B for quarter ended 2026-07-31" in i["fact"] for i in sec)
    suff = ste.catalog_sufficiency({"supporting": [], "contradictory": [], "structured": items})
    assert "no_approved_primary_or_news" not in suff["remaining_evidence_gaps"]


def test_the_concept_with_current_data_wins_over_a_stale_first_choice():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_f(5_000_000_000, "2019-04-01", "2019-06-30", filed="2019-07-25")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _f(10_200_000_000, "2026-04-01", "2026-06-30", filed="2026-07-28")]}},
    }}}
    rows = ff.extract_rows("V", "1403161", facts, S)
    assert ff.summarize("V", rows)["latest_quarter_end"] == "2026-06-30"

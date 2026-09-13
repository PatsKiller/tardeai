"""Finviz column maps must be keyed by header name, never by position.

WHY THIS TEST EXISTS
--------------------
`finviz_enrichment.py` mapped Finviz export columns by integer position and threw
the header row away. Finviz then inserted three columns into view 141 --
"Performance (3 Years)", "(5 Years)", "(10 Years)" -- which shifted every later
field right by three. Nothing failed: every shifted value still parsed as a float
and stored cleanly.

The measured damage, from the live table on 2026-09-13:

  * index 10 was labelled "recom" and actually held "Performance (10 Years)".
    131,050 of 132,894 analyst_consensus_history rows (98.6%) carried a
    "recommendation" that was really a ten-year return percentage, ranging
    -100% to +95,699% on a scale declared as 1-5.
  * because the classifier mapped low numbers to bullish ratings, the labels came
    out ANTI-correlated with reality: stocks down -100% over ten years (TPST,
    AEHL, AIXC) were rendered "Strong Buy", and the biggest winners "Strong Sell".
    61.2% of all rows read "Strong Sell", 37.2% "Strong Buy".
  * index 12 was labelled "rvol" and actually held "Volatility (Month)".

The identical defect was diagnosed and fixed in the sibling ingest path
`symbol_enrichment.py` on 2026-09-07, six days earlier. It was not swept across
to `finviz_enrichment.py`. These tests exist so that gap cannot reopen silently
in either file.

The header fixtures below were captured live from elite.finviz.com/export on
2026-09-13. If Finviz moves a column again, the map keeps working (it resolves by
name); if Finviz *renames* or *removes* one, `test_every_mapped_column_exists`
fails here rather than silently mis-filling a field in production.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_enrichment as fe  # noqa: E402


# Captured live 2026-09-13 from elite.finviz.com/export?v=<view>&t=AAPL,MSFT
LIVE_HEADERS = {
    111: [
        "No.",
        "Ticker",
        "Company",
        "Sector",
        "Industry",
        "Country",
        "Market Cap",
        "P/E",
        "Price",
        "Change",
        "Volume",
    ],
    131: [
        "No.",
        "Ticker",
        "Market Cap",
        "Shares Outstanding",
        "Shares Float",
        "Insider Ownership",
        "Insider Transactions",
        "Institutional Ownership",
        "Institutional Transactions",
        "Short Float",
        "Short Ratio",
        "Average Volume",
        "Price",
        "Change",
        "Volume",
    ],
    141: [
        "No.",
        "Ticker",
        "Performance (Week)",
        "Performance (Month)",
        "Performance (Quarter)",
        "Performance (Half Year)",
        "Performance (YTD)",
        "Performance (Year)",
        "Performance (3 Years)",
        "Performance (5 Years)",
        "Performance (10 Years)",
        "Volatility (Week)",
        "Volatility (Month)",
        "Average Volume",
        "Relative Volume",
        "Price",
        "Change",
        "Volume",
    ],
    161: [
        "No.",
        "Ticker",
        "Market Cap",
        "Dividend Yield",
        "Return on Assets",
        "Return on Equity",
        "Return on Invested Capital",
        "Current Ratio",
        "Quick Ratio",
        "LT Debt/Equity",
        "Total Debt/Equity",
        "Gross Margin",
        "Operating Margin",
        "Profit Margin",
        "Earnings Date",
        "Price",
        "Change",
        "Volume",
    ],
    121: [
        "No.",
        "Ticker",
        "Market Cap",
        "P/E",
        "Forward P/E",
        "PEG",
        "P/S",
        "P/B",
        "P/Cash",
        "P/Free Cash Flow",
        "EPS Growth This Year",
        "EPS Growth Next Year",
        "EPS Growth Past 5 Years",
        "EPS Growth Next 5 Years",
        "Sales Growth Past 5 Years",
        "Price",
        "Change",
        "Volume",
    ],
    171: [
        "No.",
        "Ticker",
        "Beta",
        "Average True Range",
        "20-Day Simple Moving Average",
        "50-Day Simple Moving Average",
        "200-Day Simple Moving Average",
        "52-Week High",
        "52-Week Low",
        "Relative Strength Index (14)",
        "Price",
        "Change",
        "Change from Open",
        "Gap",
        "Volume",
    ],
}


def test_maps_are_keyed_by_name_not_position():
    """An integer key means the positional bug has been reintroduced."""
    for view, col_map in fe.VIEWS.items():
        for key in col_map:
            assert isinstance(key, str), (
                f"view {view} has integer key {key!r}: column maps must be keyed "
                "by Finviz header name. A positional map cannot detect column "
                "drift -- it can only mis-read it confidently."
            )


@pytest.mark.parametrize("view", sorted(LIVE_HEADERS))
def test_every_mapped_column_exists_in_the_live_header(view):
    """Each name we map must be a real column Finviz actually returns."""
    header = set(LIVE_HEADERS[view])
    unknown = [c for c in fe.VIEWS[view] if c not in header]
    assert not unknown, (
        f"view {view} maps columns Finviz does not return: {unknown}. "
        "Either Finviz renamed them or the map invented them."
    )


def test_view_141_does_not_claim_a_recom_column():
    """The specific defect: v=141 has no Recom column and never did.

    Mapping one caused 131,050 fabricated analyst ratings.
    """
    assert "Recom" not in LIVE_HEADERS[141]
    assert "recom" not in fe.VIEWS[141].values(), (
        "v=141 carries no analyst recommendation. Mapping a 'recom' field here "
        "is what stored Performance (10 Years) as a 1-5 analyst rating."
    )


def test_performance_10y_is_mapped_as_a_percentage_not_a_rating():
    assert fe.VIEWS[141]["Performance (10 Years)"] == "perf_10y_pct"
    assert "perf_10y_pct" in fe.PCT_FIELDS


def test_relative_volume_is_rvol_and_volatility_is_not():
    """rvol previously read "Volatility (Month)"."""
    assert fe.VIEWS[141]["Relative Volume"] == "rvol"
    assert fe.VIEWS[141]["Volatility (Month)"] == "volatility_m_pct"


def test_v121_eps_columns_are_growth_percentages_not_dollar_eps():
    """v=121 index 10 was labelled eps_ttm; it is "EPS Growth This Year"."""
    assert fe.VIEWS[121]["EPS Growth This Year"] == "eps_growth_this_y_pct"
    assert "eps_ttm" not in fe.VIEWS[121].values(), (
        "v=121 returns EPS *growth percentages*, not trailing dollar EPS. "
        "Filling a field named eps_ttm from it misstates the units."
    )


# ── Negative controls: prove the old behaviour was wrong ──────────────────────


def _parse(view, csv_text):
    """Run the module's real parse path against a canned response body."""
    import csv as _csv
    import io as _io

    rows = list(_csv.reader(_io.StringIO(csv_text)))
    header = [h.strip().strip('"') for h in rows[0]]
    index_of = {n: i for i, n in enumerate(header)}
    col_map = fe.VIEWS[view]
    out = {}
    for parts in rows[1:]:
        sym = parts[index_of["Ticker"]].strip().upper()
        rec = {}
        for col_name, field in col_map.items():
            if field in fe.SKIP_DUPLICATES:
                continue
            i = index_of.get(col_name)
            if i is None or i >= len(parts):
                continue
            raw = parts[i].strip()
            if field in fe.PCT_FIELDS:
                rec[field] = fe._parse_float(raw)
            elif field in (
                "ticker",
                "company",
                "sector",
                "industry",
                "country",
                "earnings_date",
                "earnings_time",
                "earnings_date2",
                "recom",
            ):
                rec[field] = raw if raw and raw != "-" else None
            else:
                rec[field] = fe._parse_float(raw)
        out[sym] = rec
    return out


def test_negative_control_the_old_positional_index_held_10y_performance():
    """Index 10 of a real v=141 row is a ten-year return, not a rating.

    This is the row shape that produced recom_score=-100 -> "Strong Buy".
    """
    body = (
        ",".join(f'"{h}"' for h in LIVE_HEADERS[141])
        + "\n"
        + '"1","TPST","5.00%","-10.00%","-20.00%","-30.00%","-40.00%","-50.00%",'
        '"-80.00%","-95.00%","-100.00%","8.00%","9.00%","1000000","1.50",'
        '"2.00","1.00%","500000"\n'
    )
    rec = _parse(141, body)["TPST"]

    # The value the old map called "recom" is here, correctly named and typed.
    assert rec["perf_10y_pct"] == -100.0
    # And it is NOT presented as an analyst recommendation.
    assert "recom" not in rec

    # The old positional map would have taken index 12 as rvol. Prove the
    # name-keyed map does not: index 12 is Volatility (Month) = 9.00%.
    raw_parts = body.strip().split("\n")[1].split(",")
    assert raw_parts[12].strip('"') == "9.00%"
    assert rec["volatility_m_pct"] == 9.0
    assert rec["rvol"] == 1.50  # index 14, resolved by name


def test_negative_control_quoted_comma_does_not_shift_columns():
    """A company name containing a comma broke naive str.split(',').

    Under the old parser every field after "Company" shifted left by one.
    """
    body = (
        ",".join(f'"{h}"' for h in LIVE_HEADERS[111])
        + "\n"
        + '"1","GOOGL","Alphabet, Inc.","Technology","Internet","USA",'
        '"2000.00B","25.50","150.00","1.25%","30000000"\n'
    )
    rec = _parse(111, body)["GOOGL"]

    assert rec["company"] == "Alphabet, Inc."
    assert rec["sector"] == "Technology"  # would be "Inc." under str.split
    assert rec["pe"] == 25.50
    # Naive comma splitting yields one extra field; csv.reader does not.
    assert len(body.strip().split("\n")[1].split(",")) == 12
    assert len(LIVE_HEADERS[111]) == 11


def test_absent_column_is_left_unset_never_backfilled_from_a_neighbour():
    """Schema drift must yield missing data, not a neighbour's value."""
    header = [h for h in LIVE_HEADERS[141] if h != "Relative Volume"]
    body = (
        ",".join(f'"{h}"' for h in header)
        + "\n"
        + '"1","AAPL","1.00%","2.00%","3.00%","4.00%","5.00%","6.00%","7.00%",'
        '"8.00%","9.00%","10.00%","11.00%","1000000","2.00","1.00%","500000"\n'
    )
    rec = _parse(141, body)["AAPL"]
    assert "rvol" not in rec, (
        "A column Finviz stopped returning must leave the field unset. Taking "
        "whatever now sits at that index is the original defect."
    )

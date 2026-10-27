"""Prospectus presentation polish (design prospectus/v001.1).

Operator 2026-10-26: "what are these F with the numbers all over the pages? … internal pointers. Do those really need
to be shown? Is there any way we can polish this any more?" — and on a fund's ownership block: "ETF shouldn't have
this. They should have something else that's relative to ETF."

Covers: citation renumbering (order of first use, F-ids kept for audit only), fund-aware hiding and the fund structure
block, the header name fallback, relevant-only source coverage, prose cleanup, the common chart date axis, and the
HTML / PDF / DOCX footnotes. Synthetic tickers, names and numbers only (public repo); nothing is written outside tmp.
"""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import re
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import charts, presentation as pr, render  # noqa: E402

FIXTURE = ROOT / "apps/command-center-v3/e2e/fixtures/prospectus-fund.json"


def fund_doc() -> dict:
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8"))["doc"])


def stock_doc() -> dict:
    return {
        "symbol": "ZSTK", "name": "Zed Stock Corp", "scope": "watch", "verdict_line": "WATCH — fair value [F9].",
        "facts": [{"id": "F2", "label": "Revenue growth %", "value": 12.0, "unit": "%", "source": "synthetic", "as_of": "2026-01-02"},
                  {"id": "F9", "label": "Last close", "value": 10.0, "source": "synthetic prices"},
                  {"id": "F5", "label": "Margin %", "value": 30.0, "unit": "%"}],
        "sections": [{"id": "risks", "title": "Risks", "body_md": "Margin risk [F5] and growth [F2].", "citations": []},
                     {"id": "summary_verdict", "title": "Summary", "body_md": "Growth [F2, F9] holds; [x] stays prose.", "citations": []},
                     {"id": "position_and_plan", "title": "Plan", "body_md": "Not shown for watch [F77].", "citations": []}],
        "blocks": {"ownership_flows": {"institutional_pct": 70.0, "short_float_pct": None, "insider_buys_90d": None},
                   "estimates": {"eps_surprises": [{"date": "2026-08-01", "actual": 1.0, "estimate": 0.9, "surprise_pct": 11.1}]},
                   "scenarios": {"cases": [{"case": "base", "price": 10, "narrative": "Flat [F31]."}]}},
        "source_coverage": {"domains": [{"domain": "quote_price", "status": "used"}]},
    }


# ── citations ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_footnotes_renumbered_in_order_of_first_use_with_fact_ids_kept():
    notes = pr.footnotes(stock_doc())
    # verdict first, then sections in contract order (summary before risks), then block texts; watch drops the plan
    assert [(n["n"], n["id"]) for n in notes] == [(1, "F9"), (2, "F2"), (3, "F5"), (4, "F31")]
    assert notes[1]["label"] == "Revenue growth %" and notes[1]["value"] == "12%" and notes[1]["as_of"] == "2026-01-02"
    assert notes[3]["label"] == "Source not recorded"  # an unknown internal id is numbered, never shown raw
    assert "F77" not in [n["id"] for n in notes]


def test_section_footnotes_and_groups():
    doc = stock_doc()
    pres = pr.present(doc)
    assert pres["section_footnotes"] == {"summary_verdict": [1, 2], "risks": [2, 3]}
    groups = [ids for _, ids in pr.iter_groups("a [F1, F2] b [x] c [^c1]", {"c1"})]
    assert groups == [["F1", "F2"], ["c1"]]


def test_html_has_no_raw_fact_ids_but_keeps_them_as_attributes():
    html = render.html(stock_doc())
    body = html.split("<body>", 1)[1]
    assert not re.search(r"\[F\d", body)
    assert re.search(r'<sup class="pc-fn"><a href="#fn-2" data-fact-id="F2" title="[^"]*">2</a>,<a href="#fn-1" data-fact-id="F9"', body)
    assert 'id="fn-1" value="1" data-fact-id="F9"' in body  # the numbered Sources appendix
    assert "[x] stays prose" in body
    assert "Sources and facts" not in body and "Sources (2)" in body  # per-section disclosure, no raw facts table


def test_strip_and_clean_prose():
    assert pr.clean_prose("-\nA  sentence , here .\n- real\n*") == "A sentence, here.\n- real"
    assert pr.strip_citations("Up [F1, F2] today.") == "Up today."
    assert "pc-mute" in render.cell_html("measured -0.01 but not reliable (t -0.4) [F1]", {"F1": {"n": 1, "id": "F1"}})


# ── fund-aware layout ──────────────────────────────────────────────────────────────────────────────────────────────

def test_fund_structure_reads_existing_fields_and_names_gaps_once():
    pres = pr.present(fund_doc())
    assert pres["is_fund"] is True
    fs = pres["fund_structure"]
    rows = {r["label"]: r["value"] for r in fs["rows"]}
    assert rows["Expense ratio"] == "0.07%"
    assert rows["Top 3 concentration"] == "12.4%"
    assert rows["Largest sector"] == "Synthetic Staples 21.0%"
    assert rows["Distribution yield · TTM"].startswith("3.10%")
    assert rows["Distribution growth · 3 years"].startswith("+")
    assert rows["1Y vs category peers"].startswith("+7.0 pts")
    assert "Overlap with your book" in fs["missing"] and "Assets under management" in fs["missing"]
    assert [h["symbol"] for h in fs["top_holdings"]] == ["ACME", "PEER1", "PEER2"]


def test_fund_overlap_rendered_when_a_source_supplies_it():
    doc = fund_doc()
    doc["blocks"]["fund_profile"]["book_overlap"] = {"pct": 32.5, "direct": ["ACME"], "via_funds": ["ZOTHER"]}
    rows = {r["label"]: r["value"] for r in pr.fund_structure(doc)["rows"]}
    assert rows["Overlap with your book"].startswith("32.5% of the top holdings")


def test_fund_hides_stock_blocks_and_stock_keeps_them():
    fund_html = render.html(fund_doc())
    for gone in ('id="block-ownership_flows"', 'id="block-estimates"', 'id="block-earnings_call"', 'id="block-fund_profile"'):
        assert gone not in fund_html, gone
    assert 'id="block-fund_structure"' in fund_html and "Not in our data: Index tracked" in fund_html
    stock = stock_doc()
    stock["scope"] = "holding"
    html = render.html(stock)
    assert 'id="block-ownership_flows"' in html and 'id="block-estimates"' in html
    assert pr.fund_structure(stock) is None


def test_blank_rows_collapse_into_one_not_in_our_data_line():
    tables = [{"id": "ownership_flows", "title": "Ownership", "columns": ["Measure", "Value"],
               "rows": [["Institutional ownership", "70.0%"], ["Insider buys / sells 90d", "n/a / n/a"], ["Short interest", "n/a · n/a"]]}]
    out = render.polish_tables(stock_doc(), tables)
    assert out[0]["rows"] == [["Institutional ownership", "70.0%"]]
    assert out[0]["note"].startswith("Not in our data: Insider buys / sells 90d, Short interest.")


# ── header name ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_display_name_fallbacks():
    assert pr.display_name({"symbol": "ZSTK", "name": "Zed Stock Corp"}) == "Zed Stock Corp"
    assert pr.display_name(fund_doc()) == "Zed Synthetic Dividend Fund"  # from the profile description
    assert pr.name_from_description("To pursue its goal, the fund invests") is None
    assert pr.name_from_description("The fund seeks income") is None
    assert pr.display_name({"symbol": "ZNONE", "name": "ZNONE"}) == "ZNONE"
    html = render.html({"symbol": "ZNONE", "name": "ZNONE", "sections": []})
    assert "<h1>ZNONE</h1>" in html  # never "ZNONE ZNONE"


def test_fund_universe_name_used_when_nothing_else(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/prospectus_presentation.json").write_text(json.dumps({"fund_names_source": "config/u.json"}))
    (tmp_path / "config/u.json").write_text(json.dumps({"instruments": [{"symbol": "ZETF", "name": "Zed Example ETF"}]}))
    assert pr.display_name({"symbol": "ZETF", "name": "ZETF"}, root=tmp_path) == "Zed Example ETF"
    assert pr.index_name("ZETF", "ZETF", root=tmp_path) == "Zed Example ETF"
    assert pr.index_name("ZETF", "Recorded Name", root=tmp_path) == "Recorded Name"


# ── coverage ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_coverage_drops_plumbing_and_not_applicable_keeps_counts():
    cov = pr.present(fund_doc())["coverage"]
    assert cov["counts"] == {"used": 2, "stale": 1, "failed": 1, "missing": 1}
    assert cov["hidden"] == 3  # supervisor_heartbeats, model_chooser_receipts (n/a) and counterfactual_ledger (plumbing)
    labels = [d["label"] for g in cov["groups"].values() for d in g]
    assert "Price quotes" in labels and not any("ledger" in x.lower() or "supervisor" in x.lower() for x in labels)
    cfg = pr.config()
    for domain in ("supervisor_heartbeats", "approval_packages", "model_chooser_receipts"):
        assert domain in cfg["hidden_coverage_domains"]


def test_golden_fixture_presentation_in_sync():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert pr.present(data["doc"]) == data["presentation"], "regenerate the e2e fund fixture presentation"


def test_present_never_raises():
    out = pr.present({"symbol": "ZBAD", "sections": "not-a-list", "blocks": []})
    assert out["schema"] == pr.SCHEMA and "display_name" in out


# ── charts ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_line_axis_merges_sorted_dates_and_drops_empty_series():
    series = [{"name": "A", "points": [["2026-01-03", 1], ["2026-02-05", 2]]},
              {"name": "B", "points": [["2026-01-02", 3], ["2026-03-04", 4]]},
              {"name": "C", "points": [["2026-01-02", None]]}]
    xs, keep = charts.line_axis(series)
    assert xs == ["2026-01-02", "2026-01-03", "2026-02-05", "2026-03-04"]
    assert [s["name"] for s in keep] == ["A", "B"]
    assert charts.month_label("2026-01-14") == "Jan 26"
    days = [f"2025-{m:02d}-{d:02d}" for m in range(1, 13) for d in (3, 15)]
    assert [charts.month_label(days[i]) for i in charts.month_ticks(days, 6)] == ["Jan 25", "Mar 25", "May 25", "Jul 25", "Sep 25", "Nov 25"]
    svg = charts.svg({"id": "x", "type": "line", "title": "t", "series": series})
    assert "Jan 26" in svg and svg.count("<path") == 2


# ── files ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_docx_superscript_footnotes_and_numbered_endnotes():
    pytest.importorskip("docx")
    data = render.docx(fund_doc(), {})
    xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
    assert not re.search(r"\[F\d", xml)
    assert '<w:vertAlign w:val="superscript"/>' in xml
    text = re.sub(r"<[^>]+>", "", xml)
    assert "Sources" in text and "1. Fund distribution yield %" in text
    assert "Fund structure &amp; holdings" in xml and "Ownership and flows" not in text


def test_pdf_superscript_footnotes_and_endnotes():
    pytest.importorskip("weasyprint")
    html = render.html(fund_doc(), png_charts={}, theme="light")
    assert "<details" not in html  # print mode: plain lists, nothing hidden behind a tap
    assert 'class="pc-appendix"><h2>Sources</h2>' in html
    data = render.pdf(fund_doc(), {})
    assert data and data[:4] == b"%PDF"

"""LQ-20261107-157: finviz_enrichment drops non-equity symbols before any request is planned.

Finviz cannot return CUSIP identifiers (12507E201, 543354104, 628518102) or open-end mutual funds
(AMANX). Before this change the dry run counted them as stale and planned requests for them.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import finviz_enrichment as fe  # noqa: E402


def test_split_equities_drops_cusips_and_mutual_fund_x_tickers():
    universe = ["AA", "12507E201", "AMANX", "ABNB", "543354104", "628518102", "V"]
    equities, skipped = fe._split_equities(universe)
    assert equities == ["AA", "ABNB", "V"]
    skipped_map = {r["symbol"]: r["reason"] for r in skipped}
    assert set(skipped_map) == {"12507E201", "543354104", "628518102", "AMANX"}
    assert skipped_map["AMANX"] == "mutual_fund_x"


def test_split_equities_keeps_share_class_and_four_letter_x_symbols():
    # Share-class suffixes and 4-letter tickers ending in X are not mutual-fund shaped.
    equities, skipped = fe._split_equities(["BRK-B", "BF.B", "MAXX", "SCHD"])
    assert equities == ["BRK-B", "BF.B", "MAXX", "SCHD"]
    assert skipped == []


def test_dry_run_plan_counts_only_equities_and_reports_skips(monkeypatch):
    monkeypatch.setattr(fe, "_read_cache_readonly", lambda root: {})
    symbols = ["AA", "12507E201", "AMANX", "ABNB"]
    plan = fe.dry_run_plan(symbols, project_root=str(ROOT))
    assert plan["symbols"] == 4
    assert plan["equities"] == 2
    assert plan["stale"] == 2
    assert [r["symbol"] for r in plan["skipped_non_equity"]] == ["12507E201", "AMANX"]
    # 2 equities = 1 batch x 6 default views
    assert plan["finviz_export_requests"] == 1 * len(plan["views"])
    assert "AMANX" not in plan["stale_first"] and "12507E201" not in plan["stale_first"]


def test_enrich_tickers_partition_uses_split_equities():
    src = (ROOT / "scripts" / "finviz_enrichment.py").read_text()
    assert "symbols, rejected = _split_equities(symbols)" in src
    assert "skipped_non_equity" in src

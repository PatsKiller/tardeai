"""source_litmus_vs_yahoo.evaluate: stored closes against an independent close. Pure, offline."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import source_litmus_vs_yahoo as lit  # noqa: E402

COVERS = ["scripts/source_litmus_vs_yahoo.py"]


def test_matching_closes_pass():
    samples = [("AAPL", "market_quotes", 332.55), ("HPE", "finviz", 62.08), ("XLI", "portfolio_repricer", 172.37)]
    ref = {"AAPL": 332.27, "HPE": 62.09, "XLI": 172.37}
    out = lit.evaluate(samples, ref)
    assert out["block"] == []
    assert out["sources"]["market_quotes"]["within"] == 1


def test_a_source_with_too_many_wrong_closes_blocks_and_lists_them():
    samples = [(f"S{i}", "market_quotes", 10.0) for i in range(20)] + [("XLI", "portfolio_repricer", 7.51)]
    ref = {f"S{i}": (10.0 if i >= 3 else 20.0) for i in range(20)}
    ref["XLI"] = 172.37
    out = lit.evaluate(samples, ref)
    assert any(b.startswith("market_quotes: 3/20") for b in out["block"])
    assert any(b.startswith("portfolio_repricer: 1/1") for b in out["block"])
    worst = out["sources"]["portfolio_repricer"]["worst"][0]
    assert worst["symbol"] == "XLI" and worst["deviation_pct"] > 90


def test_small_differences_are_off_but_not_blocking():
    samples = [("BRKL", "market_quotes", 26.34)] + [(f"S{i}", "market_quotes", 10.0) for i in range(60)]
    ref = {"BRKL": 24.74, **{f"S{i}": 10.0 for i in range(60)}}
    out = lit.evaluate(samples, ref)
    st = out["sources"]["market_quotes"]
    assert st["off"] == 1 and st["badly_off"] == 0 and out["block"] == []


def test_no_reference_is_counted_not_compared():
    out = lit.evaluate([("DELISTED", "market_quotes", 1.0)], {"DELISTED": None})
    st = out["sources"]["market_quotes"]
    assert st["no_reference"] == 1 and st["compared"] == 0 and out["block"] == []

"""StockTwits holdings requests omit dead CUSIP rows.

ANCHOR: LQ1438_STOCKTWITS_DEAD_CUSIP_20261109

Lane social-ingest-all asks the StockTwits ticker stream for the first 15
holdings symbols. A holding known only by a CUSIP, with no price and no market
value, is not a ticker: the stream answers HTTP 404. The filter is
security_identity.is_dead_cusip_holding. A priced CUSIP stays. Synthetic rows
only. No network and no live holdings file.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import social_ingest as si  # noqa: E402

DEAD = "000000000"
PRICED = "11111AA19"


def _book() -> list[dict]:
    rows = [{"symbol": f"T{i:02d}", "current_price": 1, "market_value": 1} for i in range(15)]
    rows.insert(1, {"symbol": DEAD})
    rows.append({"symbol": PRICED, "current_price": 4, "market_value": 40})
    rows.append({"symbol": "CASH", "is_cash": True, "current_price": 1, "market_value": 1})
    rows.append({"symbol": "FUNDX", "is_fund": True, "current_price": 1, "market_value": 1})
    return rows


def test_dead_cusip_is_omitted_and_priced_cusip_stays():
    kept = si.stocktwits_symbols(_book())
    assert DEAD not in kept
    assert PRICED in kept
    assert "CASH" not in kept
    assert "FUNDX" not in kept
    window = kept[:15]
    assert len(window) == 15
    assert DEAD not in window
    assert "T14" in window
    assert si.stocktwits_symbols(None) == []
    assert si.stocktwits_symbols("nope") == []


def test_source_all_requests_the_filtered_window(tmp_path, monkeypatch):
    rows = _book()
    dest = tmp_path / "data" / "portfolios" / "state" / "holdings.json"
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps({"holdings": rows}), encoding="utf-8")
    monkeypatch.setattr(si, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    captured: dict[str, list] = {}

    def capture(syms):
        captured["syms"] = list(syms)
        return {"inserted": 1, "skipped": 0, "errors": []}

    monkeypatch.setattr(si, "ingest_stocktwits", capture)
    monkeypatch.setattr(si, "ingest_stocktwits_discovery", lambda: {"inserted": 0, "skipped": 0, "errors": []})
    monkeypatch.setattr(
        si,
        "ingest_reddit_with_discovery",
        lambda: {"inserted": 0, "skipped": 0, "errors": [], "configured": False},
    )
    registry = types.ModuleType("pipeline_registry")
    registry.run_start = lambda *_a, **_k: 1
    registry.run_complete = lambda *_a, **_k: None
    registry.run_fail = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "pipeline_registry", registry)

    assert si.main(["--source", "all"]) == 0
    assert captured["syms"] == si.stocktwits_symbols(rows)[:15]
    assert DEAD not in captured["syms"]
    assert "T14" in captured["syms"]
    symbols, state = si.holdings_universe()
    assert state == "ok"
    assert symbols == si.stocktwits_symbols(rows)
    receipt = (tmp_path / "data" / "runtime" / "social-ingest-all_last.json").read_text(encoding="utf-8")
    assert DEAD not in receipt


def test_parent_slice_would_have_included_the_dead_symbol():
    """The pre-filter list comprehension, copied here, is what the parent shipped.

    This pins the fixture shape: without the predicate, the first 15 include the dead CUSIP
    and leave T14 out. The live parent probe confirms the same on the assigned SHA.
    """
    raw = [
        h["symbol"]
        for h in _book()
        if h.get("symbol") and not h.get("is_cash") and not h.get("is_fund")
    ]
    assert raw[:15][1] == DEAD
    assert "T14" not in raw[:15]

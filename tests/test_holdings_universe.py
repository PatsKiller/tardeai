"""R0 — one holdings denominator. CASH is not a thesis ticker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.holdings_universe import (
    held_cash_rows,
    held_equity_tickers,
    held_unresolved_cusips,
    is_held_equity_ticker,
    snapshot,
    write_snapshot,
)
from scripts.research_scheduler import _is_symbol


def _write_holdings(root: Path, rows: list[dict]) -> None:
    p = root / "data" / "portfolios" / "state"
    p.mkdir(parents=True)
    (p / "holdings.json").write_text(json.dumps({"holdings": rows}), encoding="utf-8")


def test_filters():
    assert is_held_equity_ticker("SCHD")
    assert is_held_equity_ticker("BRK.B")
    assert not is_held_equity_ticker("CASH")
    assert not is_held_equity_ticker("12507E201")
    assert not is_held_equity_ticker("")
    assert not _is_symbol("CASH")
    assert not _is_symbol("SPAXX")
    assert _is_symbol("JEPI")
    assert _is_symbol("BRK.B")


def test_snapshot_collapses_accounts_and_drops_cash_cusip(tmp_path: Path):
    _write_holdings(tmp_path, [
        {"symbol": "SCHD", "account": "ira", "is_cash": False, "market_value": 1},
        {"symbol": "SCHD", "account": "taxable", "is_cash": False, "market_value": 2},
        {"symbol": "CASH", "account": "ira", "is_cash": True, "asset_type": "cash", "market_value": 9},
        {"symbol": "12507E201", "account": "ira", "is_cash": False, "market_value": 0},
        {"symbol": "JEPI", "account": "ira", "is_cash": False, "market_value": 3},
    ])
    assert held_equity_tickers(root=tmp_path) == ["JEPI", "SCHD"]
    assert len(held_cash_rows(root=tmp_path)) == 1
    assert held_unresolved_cusips(root=tmp_path) == ["12507E201"]
    snap = snapshot(root=tmp_path)
    assert snap["held_equity_ticker_n"] == 2
    assert snap["cash_rows"] == 1
    assert snap["position_rows"] == 5
    path = write_snapshot(root=tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["held_equity_tickers"] == ["JEPI", "SCHD"]
    assert saved["schema"] == "HoldingsUniverse@v1"


def test_coverage_list_held_tickers_delegates(tmp_path: Path):
    from scripts.lib.cio_held_thesis_coverage import list_held_tickers

    _write_holdings(tmp_path, [
        {"symbol": "V", "is_cash": False},
        {"symbol": "CASH", "is_cash": True, "asset_type": "cash"},
    ])
    assert list_held_tickers(root=tmp_path) == ["V"]


def test_coverage_write_also_writes_universe_snapshot(tmp_path: Path):
    from scripts.lib.cio_held_thesis_coverage import write_coverage_report

    _write_holdings(tmp_path, [{"symbol": "V", "is_cash": False}])
    path = write_coverage_report(
        {"schema": "HeldBookThesisCoverage@v1", "as_of": "t", "held_count": 1},
        root=tmp_path,
    )
    assert path.is_file()
    uni = json.loads((tmp_path / "data" / "cio" / "holdings_universe_latest.json").read_text())
    assert uni["held_equity_tickers"] == ["V"]

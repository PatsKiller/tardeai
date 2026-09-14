"""check_finviz_view_contracts.evaluate: the drift gate for Finviz saved views. Pure, offline."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_finviz_view_contracts as c  # noqa: E402

COVERS = ["scripts/check_finviz_view_contracts.py"]

HEAD = ('No.,Ticker,Company,Sector,Industry,Country,Market Cap,P/E,Shares Float,Gap,'
        'Average Volume,Relative Volume,Price,Change,Volume\r\n')
AAPL = '1,"AAPL","Apple Inc","Technology","Consumer Electronics","USA",4842453.75,35.1,14576.2,0.10%,53806.13,1.13,333.89,0.49%,7936368\r\n'
MSFT = '2,"MSFT","Microsoft Corporation","Technology","Software","USA",3661990.84,33.0,7310.24,0.20%,35434.72,0.9,502.27,1.4%,5000000\r\n'
HPE = '3,"HPE","Hewlett Packard Enterprise Co","Technology","Communication Equipment","USA",74722.99,29.35,1321.79,-10.44%,21374.39,2.91,55.96,-9.87%,7714327\r\n'
GOOD = HEAD + AAPL + MSFT + HPE
QUOTES = {"AAPL": 334.2, "MSFT": 502.3, "HPE": 55.9}


def test_current_layout_passes():
    r = c.evaluate(152, GOOD, QUOTES)
    assert r["block"] == [] and "Relative Volume" in r["headers"]


def test_a_moved_column_blocks():
    r = c.evaluate(152, GOOD.replace("Relative Volume", "Volatility (Month)"), QUOTES)
    assert any(b.startswith("contract:") for b in r["block"])


def test_market_cap_in_billions_blocks():
    r = c.evaluate(152, GOOD.replace("4842453.75", "4842.45"), QUOTES)
    assert any("Market Cap" in b for b in r["block"])


def test_average_volume_in_shares_blocks():
    r = c.evaluate(152, GOOD.replace("53806.13", "53806130"), QUOTES)
    assert any("Average Volume" in b for b in r["block"])


def test_price_far_from_the_independent_quote_blocks():
    r = c.evaluate(152, GOOD, {**QUOTES, "HPE": 120.0})
    assert any(b.startswith("price: HPE") for b in r["block"])


def test_no_database_is_said_not_hidden():
    r = c.evaluate(152, GOOD, None)
    assert r["block"] == [] and any("skipped" in w for w in r["warn"])

"""v1.2.2 P1-4 — eConfirm per-fill parser against SANITIZED fixtures (pure)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from schwab_econfirm_reconcile import parse_fills

FIX = ROOT / "tests" / "fixtures" / "econfirm"


def test_bjdx_multifill_purchase_and_charged_sale():
    fills = parse_fills((FIX / "bjdx_multifill.txt").read_text())
    buys = [f for f in fills if f["action"] == "Purchase"]
    sells = [f for f in fills if f["action"] == "Sale"]
    assert [f["price"] for f in buys] == [1.40, 1.43, 1.62]          # every fill row
    assert all(f["charge_or_interest"] == 0.0 for f in buys)          # zero-charge purchases
    assert len(sells) == 1 and sells[0]["price"] == 1.41
    assert sells[0]["charge_or_interest"] == 0.23                     # charged sale
    assert all(f["quantity"] == 1000.0 for f in fills)
    # section totals were NOT emitted as fills
    assert not any(f["quantity"] == 3000.0 for f in fills)
    # ordinals stable for versioned dedupe keys
    assert [f["fill_ordinal"] for f in buys] == [0, 1, 2]


def test_fcntx_fractional_mutual_fund():
    fills = parse_fills((FIX / "fcntx_fractional.txt").read_text())
    assert len(fills) == 1
    f = fills[0]
    assert f["quantity"] == 4034.942 and f["price"] == 26.53
    assert f["trade_date"] == "07/13/26" and f["settle_date"] == "07/14/26"


def test_malformed_yields_nothing_not_garbage():
    assert parse_fills((FIX / "malformed.txt").read_text()) == []

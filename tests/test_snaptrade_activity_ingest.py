import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/snaptrade_activity_ingest.py"
API = ROOT / "scripts/api_v2.py"


def load_module():
    spec = importlib.util.spec_from_file_location("snaptrade_activity_ingest", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_fidelity_dividend_activity_maps_to_trade_transactions_shape():
    mod = load_module()
    row = mod.normalize_activity(
        {
            "id": "div-schd-20260629",
            "date": "2026-06-29",
            "description": "DIVIDEND RECEIVED SCHWAB US DIVIDEND EQUITY ETF (SCHD) (Cash)",
            "amount": 505.00,
            "type": "DIVIDEND",
        },
        "fidelity_rollover_ira",
    )
    assert row["trade_date"] == "2026-06-29"
    assert row["action"] == "Dividend"
    assert row["symbol"] == "SCHD"
    assert row["amount"] == 505.00
    assert row["account"] == "fidelity_rollover_ira"


def test_fidelity_full_sell_activity_maps_to_sell_row():
    mod = load_module()
    row = mod.normalize_activity(
        {
            "id": "sell-hpe-20260629",
            "date": "2026-06-29",
            "description": "YOU SOLD HEWLETT PACKARD ENTERPRISE CO COM (HPE) (Cash)",
            "symbol": "HPE",
            "quantity": 1000,
            "price": 42.58912,
            "amount": 42589.12,
            "type": "SELL",
        },
        "fidelity_rollover_ira",
    )
    assert row["action"] == "Sell"
    assert row["symbol"] == "HPE"
    assert row["quantity"] == 1000
    assert row["price"] == 42.5891
    assert row["amount"] == 42589.12


def test_snaptrade_activity_ingest_is_read_only_and_dry_by_default():
    src = SCRIPT.read_text()
    assert "dry-run by default" in src
    assert "sr.activities" in src
    assert "import_source='snaptrade_activity'" in src
    assert "trade_transactions" in src
    assert "place_order" not in src
    assert "submit_order" not in src
    assert "execute_order" not in src


def test_portfolio_api_suppresses_stale_fidelity_holding_after_full_sell():
    src = API.read_text()
    assert "_latest_fidelity_trade" in src
    assert "action IN ('Buy','Sell')" in src
    assert "fully sold the stale holding" in src
    assert "_sold_qty >= _shares" in src


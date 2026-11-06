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


def test_fidelity_reinvested_dividend_keeps_drip_classification_and_lot_data():
    mod = load_module()
    row = mod.normalize_activity(
        {
            "id": "drip-schd-20260629",
            "date": "2026-06-29",
            "description": "DIVIDEND REINVESTMENT SCHWAB US DIVIDEND EQUITY ETF (SCHD) (Cash)",
            "symbol": "SCHD",
            "quantity": 12.5,
            "amount": 505.00,
            "type": "DIVIDEND REINVESTMENT",
        },
        "fidelity_rollover_ira",
    )
    assert row["action"] == "Reinvested Dividend"
    assert row["symbol"] == "SCHD"
    assert row["quantity"] == 12.5
    assert row["price"] == 40.4
    assert row["amount"] == 505.00


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
    assert "Reinvested Dividend" in src


def test_portfolio_api_suppresses_stale_fidelity_holding_after_full_sell():
    src = API.read_text()
    assert "_latest_fidelity_trade" in src
    assert "action IN ('Buy','Sell')" in src
    assert "fully sold the stale holding" in src
    assert "_sold_qty >= _shares" in src


def test_the_providers_own_event_id_is_stored_as_its_own_column():
    """Operator grant 2026-11-04: the id the ingester already reads becomes provider_uid, the only stable identity a
    transaction has (the composite dedupe_key contains the mutable quantity)."""
    mod = load_module()
    row = mod.normalize_activity(
        {"id": "act-9f2", "date": "2026-10-30", "description": "SOLD 100 SPCX", "type": "SELL",
         "symbol": "SPCX", "units": 100, "price": 80.0, "amount": 8000.0},
        "schwab_taxable",
    )
    assert row["provider_uid"] == "act-9f2"


def test_a_manufactured_fallback_id_is_never_written_as_a_provider_uid():
    """The synthetic fallback is built from the MUTABLE quantity, so it is a dedupe aid and never an identity: the
    column is NULL, which is the fact 'the provider supplied no reference'."""
    mod = load_module()
    row = mod.normalize_activity(
        {"date": "2026-10-30", "description": "SOLD 100 SPCX", "type": "SELL",
         "symbol": "SPCX", "units": 100, "price": 80.0, "amount": 8000.0},   # no id in the activity
        "schwab_taxable",
    )
    assert row["provider_uid"] is None, row["provider_uid"]
    assert str(row["uid"]).startswith("snap:"), row["uid"]      # the dedupe aid still works

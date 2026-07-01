import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "scripts/journal_ticker_lifecycle.py"
WATCH = ROOT / "scripts/stop_out_reentry_watch.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def lifecycle():
    jl = load(LIFECYCLE, "journal_ticker_lifecycle")
    rows = [
        {"trade_date": "2026-06-18", "action": "Buy", "symbol": "HPE", "quantity": 800, "price": 47.495, "amount": -37996.00},
        {"trade_date": "2026-06-18", "action": "Buy", "symbol": "HPE", "quantity": 200, "price": 47.4999, "amount": -9499.98},
        {"trade_date": "2026-06-29", "action": "Sell", "symbol": "HPE", "quantity": 1000, "price": 42.58912, "amount": 42589.12},
        {"trade_date": "2026-06-18", "action": "Buy", "symbol": "GCTS", "quantity": 1000, "price": 5.97, "amount": -5970.00},
        {"trade_date": "2026-06-26", "action": "Sell", "symbol": "GCTS", "quantity": 1000, "price": 4.5999, "amount": 4599.90},
    ]
    return jl.aggregate_ticker_activity(rows)


def test_hpe_and_gcts_create_stop_out_reviews():
    sw = load(WATCH, "stop_out_reentry_watch")
    reviews = sw.build_stop_out_reviews(lifecycle())
    by_symbol = {r["symbol"]: r for r in reviews}
    assert set(by_symbol) == {"GCTS", "HPE"}
    assert by_symbol["HPE"]["decision"] == "STOPPED_OUT_REVIEW"
    assert by_symbol["HPE"]["realized_pnl"] == -4906.86
    assert "initial-risk cap was too loose" in by_symbol["HPE"]["policy_quality"]
    assert by_symbol["GCTS"]["realized_pnl"] == -1370.10


def test_api_route_registered_for_reentry_watch():
    api = (ROOT / "scripts/api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/stops/reentry-watch"' in api
    assert "def _stops_reentry_watch_api" in api
    assert "build_stop_out_reviews" in api
    assert "build_reentry_watch" in api


def test_reentry_watch_is_wait_and_advisory_only():
    sw = load(WATCH, "stop_out_reentry_watch")
    watch = sw.build_reentry_watch(sw.build_stop_out_reviews(lifecycle()))
    by_symbol = {w["symbol"]: w for w in watch}
    assert by_symbol["HPE"]["status"] == "WAIT"
    assert by_symbol["GCTS"]["status"] == "WAIT"
    assert by_symbol["HPE"]["advisory_only"] is True
    assert "reclaim stop level" in by_symbol["HPE"]["triggers"]
    assert "Finviz setup hit" in by_symbol["GCTS"]["triggers"]

"""Portfolio → Stop Management aggregation endpoint (`/api/v2/stops/management`).

Read-only aggregation of broker-actual + advisor-planned stops with Yellow/Amber/Red alerting. These tests
pin the route, its read-only-ness (no broker order), and the alert-level logic against synthetic holdings.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
API = ROOT / "scripts/api_v2.py"
UI = ROOT / "apps/command-center-v3/src/components/StopManagement.tsx"


def test_01_route_registered_and_read_only():
    api = API.read_text(encoding="utf-8")
    assert '"/api/v2/stops/management"' in api
    assert "def _stops_management_api" in api
    fn = api.split("def _stops_management_api")[1].split("\ndef _after_hours_override_enabled")[0]
    for bad in ("place_order", "submit_order", "schwab_transport.submit", "INSERT INTO", "UPDATE ", "DELETE "):
        assert bad not in fn, f"management endpoint must be read-only — found {bad!r}"


def test_02_ui_tab_present():
    src = UI.read_text(encoding="utf-8")
    assert "Stop Management" in src or "Total Open Risk" in src
    assert "/api/v2/stops/management" in src
    for card in ("Total Open Risk", "Portfolio Heat", "Trailing Not Active"):
        assert card in src
    hub = (ROOT / "apps/command-center-v3/src/pages/PortfolioHub.tsx").read_text(encoding="utf-8")
    assert "Stop Management" in hub and "StopManagement" in hub


def test_03_alert_levels_from_synthetic_holdings(monkeypatch):
    import api_v2
    # a core hold 2% above its stop with no broker stop should be AMBER (within 3%); one 4% above -> YELLOW.
    holdings = {"holdings": [
        {"symbol": "TESTA", "account": "schwab_taxable", "current_price": 100.0, "shares": 10, "is_cash": False},
        {"symbol": "TESTB", "account": "schwab_taxable", "current_price": 100.0, "shares": 10, "is_cash": False},
    ]}
    monkeypatch.setattr(api_v2, "portfolio_holdings", lambda: holdings)
    # feed planned stops via the advisory join by monkeypatching _db_query for the advisory query only
    real_dbq = api_v2._db_query

    def fake_dbq(sql, params=None, fetch="all"):
        if "protection_advisory" in sql:
            return [
                {"symbol": "TESTA", "evidence_json": {"recommendation": {"stop_price": 98.0}, "inputs": {"atr": 5.0}}},
                {"symbol": "TESTB", "evidence_json": {"recommendation": {"stop_price": 96.0}, "inputs": {"atr": 1.0}}},
            ]
        return real_dbq(sql, params, fetch)
    monkeypatch.setattr(api_v2, "_db_query", fake_dbq)

    out = api_v2._stops_management_api({})
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["TESTA"]["alert_level"] == "amber"   # 2% from stop (within 3%)
    assert by["TESTB"]["alert_level"] == "yellow"  # 4% from stop, core-hold naked -> yellow
    assert by["TESTA"]["broker_stop"] is None and by["TESTA"]["planned_stop"] == 98.0
    assert out["summary"]["positions"] == 2
    assert out["summary"]["total_open_risk"] == 20.0 + 40.0   # (100-98)*10 + (100-96)*10

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
    fn = api.split("def _stops_management_api")[1].split("\ndef _replace_order_id_from_body")[0]
    for bad in ("place_order", "submit_order", "schwab_transport.submit", "INSERT INTO", "UPDATE ", "DELETE "):
        assert bad not in fn, f"management endpoint must be read-only — found {bad!r}"


def test_02_ui_tab_present():
    src = UI.read_text(encoding="utf-8")
    assert "Stop Management" in src or "Total open risk" in src
    assert "/api/v2/stops/management" in src
    # Current semantic summary cards: aggregate risk, protection coverage, trailing coverage.
    for card in ("Needs action", "Active stops", "Total open risk", "Trailing live"):
        assert card in src
    # Degraded broker-read state must be surfaced, not hidden behind an empty table.
    assert "broker_stops_degraded" in src
    assert "Schwab live stop read failed" in src
    # Trail-upgrade copy is only for lots that already have a live stop.
    cta = src.split("function derivePrimaryCta", 1)[1].split("\nfunction ", 1)[0]
    assert "fixed stop still on book" in cta
    trail_idx = cta.find("fixed stop still on book")
    before = cta[:trail_idx]
    assert "has_active_stop" in before
    assert "planned_stop == null" in cta or "planned_stop == null" in src
    assert "No live broker stop and no advisory" in cta


def test_07_naked_no_advisory_still_renders_2fa_panel():
    """SCHD IRA had no advisory → HoldingProtectionActions returned null, so Open adjust had no 2FA form."""
    src = (ROOT / "apps/command-center-v3/src/components/HoldingProtectionActions.tsx").read_text(encoding="utf-8")
    assert "if (!stop && !needsSellAll" not in src
    assert "Enter a stop $ — this lot has no advisory price" in src
    assert "const showProtect = !logic.isFundLike" in src
    hub = (ROOT / "apps/command-center-v3/src/pages/PortfolioHub.tsx").read_text(encoding="utf-8")
    assert "Stop Management" in hub and "StopManagement" in hub


def test_04_reasons_subrow_not_table_column():
    src = UI.read_text(encoding="utf-8")
    assert "ReasonsSubRow" in src
    assert "rowHasReasons" in src
    assert "Expanded-row panel" in src
    assert "rowHasReasons() gating is unchanged" in src
    # Reasons live in a full-width sub-row under each position, not a table header column.
    first_head = src.split("thead", 1)[1].split("</thead>", 1)[0] if "thead" in src else ""
    assert "'Reasons'" not in first_head
    assert "<ReasonsSubRow r={r}" in src


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
        # Pin the regime — a live risk-off regime escalates naked holds amber→red and flakes the test.
        if "market_regime_snapshots" in sql:
            return {"regime_label": "risk_on", "trend_state": "", "confidence": None}
        return real_dbq(sql, params, fetch)
    monkeypatch.setattr(api_v2, "_db_query", fake_dbq)

    out = api_v2._stops_management_api({})
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["TESTA"]["alert_level"] == "amber"   # 2% from stop (within 3%)
    assert by["TESTB"]["alert_level"] == "yellow"  # 4% from stop, core-hold naked -> yellow
    assert by["TESTA"]["broker_stop"] is None and by["TESTA"]["planned_stop"] == 98.0
    assert out["summary"]["positions"] == 2
    assert out["summary"]["total_open_risk"] == 20.0 + 40.0   # (100-98)*10 + (100-96)*10
    assert out["summary"].get("omitted", 0) == 0


def test_05_unprotected_lot_without_advisory_still_listed(monkeypatch):
    """SCHD IRA-class: no live stop + no 5-day advisory must still be a NO STOP row."""
    import api_v2
    api_v2._STOPS_MGMT_CACHE.update(ts=0.0, data=None)
    holdings = {"holdings": [
        {"symbol": "SCHD", "account": "schwab_rollover_ira", "current_price": 35.14,
         "shares": 10000.25, "is_cash": False, "cost_basis": 313341.86},
        {"symbol": "SCHD", "account": "schwab_taxable", "current_price": 35.14,
         "shares": 406.54, "is_cash": False, "cost_basis": 12687.73},
        {"symbol": "CASH", "account": "schwab_rollover_ira", "current_price": 1.0,
         "shares": 585917.8, "is_cash": True},
    ]}
    monkeypatch.setattr(api_v2, "portfolio_holdings", lambda: holdings)
    monkeypatch.setattr(api_v2, "_holdings_live_stops", lambda *a, **k: {
        "by_key": {
            "SCHD:schwab_taxable": {
                "symbol": "SCHD", "account": "schwab_taxable", "stop_price": 34.69,
                "order_type": "STOP", "qty": 406.0, "status": "WORKING",
            }
        },
        "fetched_at": "2026-08-28T00:00:00+00:00",
        "degraded": False,
        "error": None,
        "broker_stop_read_ok_accounts": ["schwab_rollover_ira", "schwab_taxable"],
    })
    monkeypatch.setattr(api_v2, "_stops_lifecycle_db_snapshot", lambda: {"stops": []})

    real_dbq = api_v2._db_query

    def fake_dbq(sql, params=None, fetch="all"):
        if "protection_advisory" in sql:
            return []
        if "market_regime_snapshots" in sql:
            return {"regime_label": "risk_on", "trend_state": "", "confidence": None}
        try:
            return real_dbq(sql, params, fetch)
        except Exception:
            return [] if fetch != "one" else None

    monkeypatch.setattr(api_v2, "_db_query", fake_dbq)
    out = api_v2._stops_management_api_build({})
    keys = {(r["symbol"], r["account"]) for r in out["rows"]}
    assert ("SCHD", "schwab_rollover_ira") in keys
    assert ("SCHD", "schwab_taxable") in keys
    assert ("CASH", "schwab_rollover_ira") not in keys
    ira = next(r for r in out["rows"] if r["account"] == "schwab_rollover_ira")
    tax = next(r for r in out["rows"] if r["account"] == "schwab_taxable")
    assert ira["has_active_stop"] is False
    assert ira["broker_stop"] is None
    assert ira["planned_stop"] is None
    assert ira["stop"] is None
    assert ira["alert_level"] == "red"
    assert any("no broker stop" in str(x) for x in (ira.get("alert_reasons") or []))
    assert ira.get("trailing_should_be_active") is False
    assert "invented" in str(ira.get("next_action") or "").lower() or "Set 2FA" in str(ira.get("next_action") or "")
    assert tax["has_active_stop"] is True
    assert tax["broker_stop"] == 34.69
    assert out["summary"]["positions"] == 2
    assert out["summary"]["omitted"] == 0
    assert out["summary"]["non_cash_holdings"] == 2


def test_06_cash_and_zero_qty_still_excluded(monkeypatch):
    import api_v2
    api_v2._STOPS_MGMT_CACHE.update(ts=0.0, data=None)
    holdings = {"holdings": [
        {"symbol": "SPAXX", "account": "schwab_taxable", "current_price": 1.0, "shares": 100, "is_cash": False},
        {"symbol": "ARKX", "account": "schwab_rollover_ira", "current_price": 32.0, "shares": 0, "is_cash": False},
        {"symbol": "ARKX", "account": "schwab_taxable", "current_price": 32.0, "shares": 10, "is_cash": False},
    ]}
    monkeypatch.setattr(api_v2, "portfolio_holdings", lambda: holdings)
    monkeypatch.setattr(api_v2, "_holdings_live_stops", lambda *a, **k: {
        "by_key": {}, "fetched_at": "2026-08-28T00:00:00+00:00", "degraded": False, "error": None,
    })
    monkeypatch.setattr(api_v2, "_stops_lifecycle_db_snapshot", lambda: {"stops": []})

    def fake_dbq(sql, params=None, fetch="all"):
        if "protection_advisory" in sql:
            return []
        if "market_regime_snapshots" in sql:
            return {"regime_label": "risk_on", "trend_state": "", "confidence": None}
        return [] if fetch != "one" else None

    monkeypatch.setattr(api_v2, "_db_query", fake_dbq)
    out = api_v2._stops_management_api_build({})
    keys = {(r["symbol"], r["account"]) for r in out["rows"]}
    assert ("SPAXX", "schwab_taxable") not in keys
    assert ("ARKX", "schwab_rollover_ira") not in keys
    assert ("ARKX", "schwab_taxable") in keys


def test_08_naked_large_notional_ranks_above_looser_small_stop(monkeypatch):
    """$351k SCHD IRA with no stop must outrank tightening BAH ($134 at risk)."""
    import api_v2
    api_v2._STOPS_MGMT_CACHE.update(ts=0.0, data=None)
    holdings = {"holdings": [
        {"symbol": "SCHD", "account": "schwab_rollover_ira", "current_price": 35.14,
         "shares": 10000.25, "is_cash": False, "cost_basis": 313341.86},
        {"symbol": "BAH", "account": "schwab_taxable", "current_price": 74.87,
         "shares": 9, "is_cash": False, "cost_basis": 698.0},
        {"symbol": "XLI", "account": "schwab_rollover_ira", "current_price": 180.40,
         "shares": 201.0442, "is_cash": False, "cost_basis": 35000.0},
    ]}
    monkeypatch.setattr(api_v2, "portfolio_holdings", lambda: holdings)
    monkeypatch.setattr(api_v2, "_holdings_live_stops", lambda *a, **k: {
        "by_key": {
            "BAH:schwab_taxable": {
                "symbol": "BAH", "account": "schwab_taxable", "stop_price": 59.99,
                "order_type": "STOP", "qty": 9, "status": "WORKING",
            }
        },
        "fetched_at": "2026-08-28T00:00:00+00:00",
        "degraded": False, "error": None,
        "broker_stop_read_ok_accounts": ["schwab_rollover_ira", "schwab_taxable"],
    })
    monkeypatch.setattr(api_v2, "_stops_lifecycle_db_snapshot", lambda: {"stops": []})

    def fake_dbq(sql, params=None, fetch="all"):
        if "protection_advisory" in sql:
            return [
                {"symbol": "BAH", "evidence_json": {"recommendation": {"stop_price": 69.64}, "inputs": {"atr": 2.0}}},
                {"symbol": "XLI", "evidence_json": {"recommendation": {"stop_price": 160.92}, "inputs": {"atr": 2.0}}},
            ]
        if "market_regime_snapshots" in sql:
            return {"regime_label": "risk_on", "trend_state": "", "confidence": None}
        return [] if fetch != "one" else None

    monkeypatch.setattr(api_v2, "_db_query", fake_dbq)
    out = api_v2._stops_management_api_build({})
    actions = out["summary"]["next_actions"]
    assert actions[0]["symbol"] == "SCHD"
    assert actions[0]["account"] == "schwab_rollover_ira"
    assert actions[0]["dollars_at_risk"] > 300000
    symbols = [a["symbol"] for a in actions]
    assert "XLI" in symbols
    # BAH tighten may appear, but never ahead of the naked $351k lot.
    if "BAH" in symbols:
        assert symbols.index("SCHD") < symbols.index("BAH")

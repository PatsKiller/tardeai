import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.reentry_shared_context import (  # noqa: E402
    CACHE_KEY,
    infer_event,
    refresh_shared_symbol_context,
)


def test_infer_event_recognizes_stopped_out_from_broker_evidence():
    event_type, reason = infer_event({
        "action": "SELL",
        "description": "Trailing stop order executed after risk limit breach",
    })
    assert event_type == "stopped_out"
    assert "Trailing stop" in reason


def test_infer_event_keeps_partial_trim_and_scalp_separate():
    assert infer_event({"action": "SELL", "description": "Partial trim into strength"})[0] == "partial_trim"
    assert infer_event({"action": "SELL", "description": "Intraday momentum scalp"})[0] == "momentum_scalp"


def test_refresh_shared_context_persists_classification_and_auto_annotations():
    prefs = {
        "portfolio.reentry.exit-universe.v1": {
            "rows": [{
                "event_key": "exit:CSWC:1",
                "symbol": "CSWC",
                "trade_date": "2026-07-23",
                "action": "SELL",
                "description": "Protective stop-loss executed",
                "account": "schwab_taxable",
                "import_source": "schwab_transactions",
            }],
        },
        "portfolio.reentry.mandates.v4": {
            "CSWC": {
                "mandate": "core",
                "flags": {"growth": True, "dividend": True},
                "targetAccount": "schwab_taxable",
                "targetWeightPct": 3,
                "priority": "NORMAL",
                "thesis": "Income plus growth",
                "updatedAt": "2026-07-23T20:00:00Z",
            },
        },
        "portfolio.reentry.event-classifications.v1": {},
        "portfolio.reentry.dispositions.v1": {},
        "portfolio.reentry.resistance.v1": {
            "symbols": {
                "CSWC": {
                    "state": "BELOW",
                    "resistance": 24.2,
                    "distance_pct": -3.1,
                    "hold_days": 0,
                    "reason": "Below 20-session pivot",
                    "as_of": "2026-07-23",
                },
            },
        },
    }
    writes = {}

    def ex(sql, params=None, fetch=None):
        if "SELECT value FROM ui_prefs" in sql:
            return {"value": prefs.get(params[0], {})}
        if "FROM watchlist_items" in sql:
            return [{
                "symbol": "CSWC",
                "synthesis_recommendation": "ADD_ON_PULLBACK",
                "profile_sector": "Financial Services",
                "rsi": 44.2,
                "trend_state": "improving",
                "market_regime": "risk_off",
                "catalyst_headline": "Dividend coverage remains stable",
                "catalyst_at": "2026-07-23T16:00:00Z",
                "last_enriched_at": "2026-07-23T16:00:00Z",
            }]
        if "INSERT INTO ui_prefs" in sql:
            writes[params[0]] = json.loads(params[1])
            return None
        raise AssertionError(sql)

    payload = refresh_shared_symbol_context(ex)
    assert payload["symbol_count"] == 1
    row = payload["symbols"]["CSWC"]
    assert row["classification_status"] == "CLASSIFIED"
    assert row["latest_event"]["event_type"] == "stopped_out"
    assert row["watch"]["recommendation"] == "ADD ON PULLBACK"
    assert row["resistance"]["state"] == "BELOW"
    labels = {item["label"] for item in row["annotations"]}
    assert "STOPPED OUT" in labels
    assert "WATCH ADD ON PULLBACK" in labels
    assert "REGIME RISK OFF" in labels
    assert CACHE_KEY in writes


def test_auto_tagged_is_not_misrepresented_as_operator_classified():
    prefs = {
        "portfolio.reentry.exit-universe.v1": {
            "rows": [{
                "event_key": "exit:FATN:1",
                "symbol": "FATN",
                "trade_date": "2026-07-23",
                "action": "SELL",
                "description": "Sold after setup invalidation",
            }],
        },
        "portfolio.reentry.mandates.v4": {},
        "portfolio.reentry.event-classifications.v1": {},
        "portfolio.reentry.dispositions.v1": {},
        "portfolio.reentry.resistance.v1": {},
    }

    def ex(sql, params=None, fetch=None):
        if "SELECT value FROM ui_prefs" in sql:
            return {"value": prefs.get(params[0], {})}
        if "FROM watchlist_items" in sql:
            return [{"symbol": "FATN", "rsi": 41.9, "trend_state": "mixed"}]
        if "INSERT INTO ui_prefs" in sql:
            return None
        raise AssertionError(sql)

    row = refresh_shared_symbol_context(ex)["symbols"]["FATN"]
    assert row["classification_status"] == "AUTO_TAGGED"
    assert row["classified"] is False
    assert row["auto_tagged"] is True

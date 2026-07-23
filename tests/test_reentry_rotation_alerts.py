from __future__ import annotations

import datetime as dt
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.reentry_rotation_alerts import (
    ALERT_PREF_KEY,
    ROTATION_PREF_KEY,
    compute_rotation_gates,
    evaluate_armed_rotation_alerts,
)


class FakeExecute:
    def __init__(self, *, include_zone=True, confirmed=True, deduped=False):
        self.include_zone = include_zone
        self.deduped = deduped
        self.inserted = []
        self.source = "SCHG"
        self.destination = "SCHD"
        self.link_id = "rotation:schg-schd"
        self.rotations = {
            self.link_id: {
                "id": self.link_id,
                "sourceSymbol": self.source,
                "destinationSymbol": self.destination,
                "confirmed": confirmed,
                "rsThresholdPct": 0,
                "taxClear": True,
                "accountClear": True,
                "settlementClear": True,
                "updatedAt": "2026-07-23T12:00:00Z",
            }
        }
        self.alerts = {
            self.link_id: {
                "linkId": self.link_id,
                "armed": True,
                "createdAt": "2026-07-23T12:00:00Z",
                "updatedAt": "2026-07-23T12:00:00Z",
            }
        }
        start = dt.date(2026, 3, 1)
        # Source rises faster than destination and closes with MA20 > MA50.
        self.prices = {
            self.source: [
                {"price_date": start + dt.timedelta(days=i), "close_price": 100 + i * 0.8}
                for i in range(90)
            ],
            self.destination: [
                {"price_date": start + dt.timedelta(days=i), "close_price": 100 + i * 0.2}
                for i in range(90)
            ],
        }

    def __call__(self, sql, params=(), fetch=None):
        normalized = " ".join(sql.split()).lower()
        if "select value from ui_prefs" in normalized:
            key = params[0]
            if key == ROTATION_PREF_KEY:
                return {"value": self.rotations}
            if key == ALERT_PREF_KEY:
                return {"value": self.alerts}
            return None
        if "from ticker_prices" in normalized:
            return self.prices.get(str(params[0]).upper(), [])
        if "from watchlist_items" in normalized:
            return {"rsi": 55, "first_seen_at": "2026-07-23T15:00:00Z"}
        if "from watchlist_entry_plans" in normalized:
            if not self.include_zone:
                return None
            source_last = self.prices[self.source][-1]["close_price"]
            return {
                "entry_zone_low": source_last - 1,
                "entry_zone_high": source_last + 1,
                "created_at": "2026-07-23T14:00:00Z",
                "urgency": "ready",
                "confidence": 0.8,
            }
        if "select 1 from alert_events" in normalized:
            return {"?column?": 1} if self.deduped else None
        if "insert into alert_events" in normalized:
            self.inserted.append((sql, params))
            return None
        raise AssertionError(f"unexpected SQL: {normalized}")


def install_constructive_regime(monkeypatch):
    module = types.SimpleNamespace(current_regime=lambda: {
        "posture": "risk_on",
        "label": "RISK_ON",
        "stale": False,
        "generated_at": "2026-07-23T15:00:00Z",
    })
    monkeypatch.setitem(sys.modules, "holding_family", module)


def test_all_six_gates_pass_and_scheduled_evaluator_fires(monkeypatch):
    install_constructive_regime(monkeypatch)
    ex = FakeExecute()

    result = evaluate_armed_rotation_alerts(ex, today="2026-07-23")

    assert result["fired"] == [ex.link_id]
    assert len(result["lines"]) == 1
    assert "6/6 gates PASS" in result["lines"][0]
    assert len(ex.inserted) == 1
    evaluation = result["evaluations"][ex.link_id]
    assert evaluation["all_pass"] is True
    assert [gate["state"] for gate in evaluation["gates"]] == ["PASS"] * 6


def test_missing_entry_zone_is_unavailable_and_never_fires(monkeypatch):
    install_constructive_regime(monkeypatch)
    ex = FakeExecute(include_zone=False)

    result = evaluate_armed_rotation_alerts(ex, today="2026-07-23")

    assert result["fired"] == []
    assert ex.inserted == []
    evaluation = result["evaluations"][ex.link_id]
    assert evaluation["all_pass"] is False
    assert evaluation["has_unavailable"] is True
    assert next(g for g in evaluation["gates"] if g["key"] == "entry_zone")["state"] == "UNAVAILABLE"


def test_unconfirmed_capital_lineage_suppresses_evaluation(monkeypatch):
    install_constructive_regime(monkeypatch)
    ex = FakeExecute(confirmed=False)

    result = evaluate_armed_rotation_alerts(ex, today="2026-07-23")

    assert result["fired"] == []
    assert result["evaluations"][ex.link_id]["error"] == "capital_lineage_not_confirmed"
    assert ex.inserted == []


def test_daily_uid_dedupes_repeated_passes(monkeypatch):
    install_constructive_regime(monkeypatch)
    ex = FakeExecute(deduped=True)

    result = evaluate_armed_rotation_alerts(ex, today="2026-07-23")

    assert result["fired"] == []
    assert ex.inserted == []


def test_constraint_gate_blocks_when_operator_clearance_missing(monkeypatch):
    install_constructive_regime(monkeypatch)
    ex = FakeExecute()
    link = dict(ex.rotations[ex.link_id])
    link["taxClear"] = False

    result = compute_rotation_gates(ex, link)

    assert result["all_pass"] is False
    assert result["has_block"] is True
    constraint = next(g for g in result["gates"] if g["key"] == "constraints")
    assert constraint["state"] == "BLOCK"

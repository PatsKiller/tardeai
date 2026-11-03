"""Synthetic approved Home v007 stored-data contract; no real holdings or calls.
ANCHOR: HOME_V007_DATA_20261103
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2032, 3, 9, 21, 0, tzinfo=timezone.utc)
ASOF = "2032-03-09T20:59:00Z"


@pytest.fixture
def mod(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real external process or network forbidden")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    spec = importlib.util.spec_from_file_location(
        "home_v007_under_test", ROOT / "scripts/lib/market_risk_home_context.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def projection():
    return {
        "as_of": ASOF,
        "score": 56,
        "tier": "YELLOW",
        "categories": [],
        "positions": {},
        "history": [{"as_of": "2032-03-09T20:00:00Z", "score": 51, "tier": "YELLOW"}],
        "reentry_watch": {
            "SYNX": {
                "exit_date": "2032-03-01",
                "exit_price": 10,
                "as_of": ASOF,
                "stance": "RE_ENTER_IF",
                "headline": "Two recorded conditions remain",
                "stages": {"sma10": 11, "sma20": 12, "invalidation_level": 9},
                "current_quote": {
                    "price": 12,
                    "prev_close": 11,
                    "volume": 200,
                    "session": "regular_close",
                    "session_date": "2032-03-09",
                    "as_of": ASOF,
                    "source": "synthetic_daily_close",
                },
            }
        },
    }


def test_current_observation_is_separate_from_stage_close_and_inputs_unchanged(mod):
    p = projection()
    p["reentry_watch"]["SYNX"]["stages"]["last_close"] = 7
    before = deepcopy(p)
    result = mod.build(p, {}, now=NOW)
    symbol = result["symbols"]["SYNX"]
    assert symbol["quote"]["value"] == 12 and symbol["quote"]["session"] == "regular_close"
    assert symbol["day_change"]["value"]["price"] == 1
    assert symbol["since_exit"]["value"]["distance_pct"] == 20
    assert symbol["analysis_references"]["value"]["invalidation_level"]["reference_price"] == 9
    assert p == before and result["advisory_only"] is True


def test_missing_values_are_unknown_with_remediation_never_zero_samples(mod):
    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    symbol = mod.build(p, {}, now=NOW)["symbols"]["SYNX"]
    for field in ("quote", "day_change", "since_exit", "volume_vs_20d", "headlines", "next_event"):
        assert symbol[field]["value"] is None and symbol[field]["state"] == "unknown"
        assert symbol[field]["remediation"]["action"]


def test_future_or_unzoned_quote_never_becomes_current(mod):
    p = projection()
    p["reentry_watch"]["SYNX"].pop("current_quote")
    rows = [
        {"symbol": "SYNX", "price": 99, "as_of": "2032-03-09T22:00:00Z"},
        {"symbol": "SYNX", "price": 88, "as_of": "2032-03-09T20:50:00"},
    ]
    assert mod.build(p, {}, quotes=rows, now=NOW)["symbols"]["SYNX"]["quote"]["value"] is None


def test_volume_uses_twenty_completed_sessions_and_labels_actual_input(mod):
    p = projection()
    rows = []
    for index in range(20):
        rows.append(
            {
                "symbol": "SYNX",
                "date": (NOW.date() - timedelta(days=index + 1)).isoformat(),
                "volume": 100,
                "close": 10,
                "source": "synthetic_bars",
            }
        )
    rows.append({"symbol": "SYNX", "date": "2032-03-09", "volume": 999999, "close": 12, "provisional": True})
    volume = mod.build(p, {}, daily_bars=rows, now=NOW)["symbols"]["SYNX"]["volume_vs_20d"]
    assert volume["value"] == {"volume": 200, "average_volume_20d": 100, "ratio": 2}
    rows.pop(0)
    assert mod.build(p, {}, daily_bars=rows, now=NOW)["symbols"]["SYNX"]["volume_vs_20d"]["value"] is None


def test_all_nine_category_chips_survive_missing_measurement(mod):
    p = projection()
    p["categories"] = [
        {"category": "technical", "state": "STRESS", "as_of": ASOF, "score": 80},
        {"category": "breadth", "state": "UNKNOWN", "as_of": ASOF, "detail": "collector unavailable"},
    ]
    result = mod.build(p, {}, now=NOW)["risk"]
    assert len(result["categories"]) == 9
    by_key = {row["category"]: row for row in result["categories"]}
    assert by_key["technical"]["chip"] == "STRESS"
    assert by_key["breadth"]["state"] == "unknown" and by_key["breadth"]["remediation"]
    assert result["score_change"] == 5


def test_news_and_event_source_clock_is_not_fabricated_from_render_time(mod):
    p = projection()
    result = mod.build(
        p,
        {},
        headlines={"SYNX": {"rows": [{"title": "SYNX synthetic event"}]}},
        events={"SYNX": {"value": {"date": "2032-03-12"}}},
        now=NOW,
    )
    for field in ("headlines", "next_event"):
        assert result["symbols"]["SYNX"][field]["as_of"] is None
        assert result["symbols"]["SYNX"][field]["state"] == "unknown"


def test_budget_clear_condition_is_description_and_unverified_write_is_unavailable(mod):
    joined = {
        "budgets_detail": [
            {
                "budget": "single_sector_pct",
                "actual": 40,
                "limit": 30,
                "unit": "%",
                "account_label": "Synthetic account",
            }
        ]
    }
    row = mod.build(projection(), joined, now=NOW)["budgets"][0]
    assert row["plain_breach"] == "single sector pct is above its recorded limit"
    assert row["clears_when"] == "single sector pct is at or below 30%"
    assert row["operator_decision"]["state"] == "unavailable" and row["operator_decision"]["requires_operator"]
    assert joined["budgets_detail"][0]["limit"] == 30


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), None, "missing"])
def test_invalid_numeric_values_do_not_become_zero(mod, bad):
    assert mod.number(bad) is None

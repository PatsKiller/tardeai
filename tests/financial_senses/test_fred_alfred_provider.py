"""FRED/ALFRED macro + vintage provider tests (no network — injected client)."""
from __future__ import annotations

import pytest

from financial_senses.macro_provider import FredAlfredProvider, FredClient
from financial_senses.result import STATUS_NOT_CONFIGURED, STATUS_OK


class FakeFredClient:
    """Simulates FRED/ALFRED with vintage-aware responses."""

    def __init__(self, observations, vintage_by_date=None, vintages=None):
        self._observations = observations  # list of {date, value}
        self.vintage_by_date = vintage_by_date or {}
        self.vintages = vintages or []

    def observations(self, series_id, realtime_start=None, realtime_end=None):
        # Vintage path: return only observations known as of realtime_end.
        if realtime_end:
            return [o for o in self._observations if o["date"] <= realtime_end]
        return list(self._observations)

    def vintage_dates(self, series_id, limit=10):
        return self.vintages

    def latest(self, series_id):
        return self._observations[-1] if self._observations else None

    def value_as_of(self, series_id, decision_date):
        eligible = [o for o in self._observations if o["date"] <= decision_date]
        return eligible[-1] if eligible else None


def test_not_configured_without_key():
    p = FredAlfredProvider(api_key=None)
    r = p.query("macro.get_series", {"series_id": "DFF"})
    assert r.status == STATUS_NOT_CONFIGURED


def test_get_series():
    client = FakeFredClient([{"date": "2024-01-01", "value": 5.25}, {"date": "2024-02-01", "value": 5.5}])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_series", {"series_id": "DFF"})
    assert r.status == STATUS_OK
    assert len(r.data["observations"]) == 2


def test_latest_observation_has_provenance():
    client = FakeFredClient([{"date": "2024-02-01", "value": 5.5}])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_latest_observation", {"series_id": "DFF"})
    assert r.status == STATUS_OK
    assert r.data["latest"]["value"] == 5.5
    assert r.facts[0].source_type == "PRIMARY_GOVERNMENT"


def test_vintage_does_not_leak_future_revision():
    # A later revision (5.9 on 2025-01-01) must not appear in a 2024 decision.
    client = FakeFredClient(
        [
            {"date": "2024-01-01", "value": 5.25},
            {"date": "2024-06-01", "value": 5.5},
            {"date": "2025-01-01", "value": 5.9},
        ]
    )
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_vintage", {"series_id": "DFF", "decision_date": "2024-12-31"})
    assert r.status == STATUS_OK
    assert r.data["decision_time_value"]["value"] == 5.5
    assert r.data["decision_time_value"]["value"] != 5.9


def test_compare_vintages_reports_revision_delta():
    client = FakeFredClient(
        [
            {"date": "2024-06-01", "value": 5.5},
            {"date": "2025-01-01", "value": 5.9},
        ]
    )
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-12-31"})
    assert r.data["decision_time_value"] == 5.5
    assert r.data["latest_revised_value"] == 5.9
    assert r.data["revision_delta"] == 0.4


def test_decision_time_snapshot():
    client = FakeFredClient([{"date": "2024-01-01", "value": 5.25}, {"date": "2024-06-01", "value": 5.5}])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query(
        "macro.get_decision_time_snapshot",
        {"series_ids": ["DFF", "DGS10"], "decision_date": "2024-12-31"},
    )
    assert r.status == STATUS_OK
    assert r.data["snapshot"]["DFF"]["value"] == 5.5


def test_series_snapshot_missing_is_unavailable_state():
    client = FakeFredClient([])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_series_snapshot", {"series_ids": ["DFF"]})
    assert r.data["snapshot"]["DFF"]["state"] == "DATA_UNAVAILABLE"


def test_requires_series_id():
    client = FakeFredClient([])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_series", {})
    assert r.status == "INVALID_REQUEST"

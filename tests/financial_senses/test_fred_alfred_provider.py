"""FRED/ALFRED macro + vintage provider tests (no network — injected client)."""
from __future__ import annotations

import pytest

from financial_senses.macro_provider import FredAlfredProvider, FredClient
from financial_senses.result import STATUS_NOT_CONFIGURED, STATUS_OK


class FakeFredClient:
    """Models FRED with optional per-observation vintages.

    latest_observations: list of {date, value} under the LATEST vintage.
    as_of: dict keyed by (observation_date, realtime_end) -> value, modeling
           "what value was known as-of realtime_end for observation_date".
    _vintage_dates: list of date strings (official shape).
    """

    def __init__(self, latest_observations=None, as_of=None, vintage_dates=None):
        self.latest_observations = latest_observations or []
        self.as_of = as_of or {}
        self._vintage_dates = vintage_dates or []

    def observations(self, series_id, realtime_start=None, realtime_end=None,
                     observation_start=None, observation_end=None):
        obs = list(self.latest_observations)
        if observation_start:
            obs = [o for o in obs if o["date"] >= observation_start]
        if observation_end:
            obs = [o for o in obs if o["date"] <= observation_end]
        if realtime_end:
            obs = [
                {"date": o["date"], "value": self.as_of.get((o["date"], realtime_end), o["value"])}
                for o in obs
            ]
        return obs

    def latest(self, series_id):
        return self.latest_observations[-1] if self.latest_observations else None

    def latest_as_of(self, series_id, decision_date):
        obs = [o for o in self.latest_observations if o["date"] <= decision_date]
        if not obs:
            return None
        o = obs[-1]
        value = self.as_of.get((o["date"], decision_date), o["value"])
        return {"date": o["date"], "value": value}

    def observation_value(self, series_id, observation_date, realtime_end=None):
        for o in self.latest_observations:
            if o["date"] == observation_date:
                return self.as_of.get((observation_date, realtime_end), o["value"])
        return None

    def vintage_dates(self, series_id, limit=10):
        return self._vintage_dates


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


def test_get_series_result_validates():
    client = FakeFredClient([{"date": "2024-02-01", "value": 5.5}])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_series", {"series_id": "DFF"})
    assert r.validate() == []


def test_vintage_does_not_leak_future_revision():
    # A later observation (2025-01-01 = 5.9) must not appear in a 2024 decision.
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


def test_compare_vintages_same_observation_revision():
    # A TRUE revision: same observation date, two vintages.
    client = FakeFredClient(
        latest_observations=[{"date": "2024-06-01", "value": 5.7}],  # latest revised
        as_of={("2024-06-01", "2024-07-01"): 5.5},                   # as-of decision time
    )
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-07-01"})
    assert r.status == STATUS_OK
    assert r.data["observation_date"] == "2024-06-01"
    assert r.data["decision_time_value"] == 5.5
    assert r.data["latest_revised_value"] == 5.7
    assert r.data["revision_delta"] == 0.2


def test_revision_fact_as_of_not_decision_date():
    # The decision observation and the later revision are two distinct knowledge
    # times: the revision must NOT be stamped as_of=decision_date.
    client = FakeFredClient(
        latest_observations=[{"date": "2024-06-01", "value": 5.7}],
        as_of={("2024-06-01", "2024-07-01"): 5.5},
    )
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-07-01"})
    decision_fact = next(f for f in r.facts if f.key == "DFF@2024-06-01")
    revision_fact = next(f for f in r.facts if f.key == "DFF@revision_delta")
    assert decision_fact.as_of == "2024-07-01"
    assert revision_fact.as_of != "2024-07-01"
    assert revision_fact.as_of == r.requested_at


def test_compare_vintages_no_future_leak():
    # Different observation dates are NOT a revision.
    client = FakeFredClient(
        [
            {"date": "2024-06-01", "value": 5.5},
            {"date": "2025-01-01", "value": 5.9},
        ]
    )
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.compare_vintages", {"series_id": "DFF", "decision_date": "2024-12-31"})
    assert r.data["observation_date"] == "2024-06-01"
    # Same observation date (2024-06-01) has no revision => delta 0, not 0.4.
    assert r.data["revision_delta"] == 0.0


def test_vintage_dates_official_shape():
    client = FakeFredClient(vintage_dates=["2024-06-01", "2024-07-01"])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.get_vintage_dates", {"series_id": "DFF"})
    assert r.status == STATUS_OK
    assert r.data["vintage_dates"] == ["2024-06-01", "2024-07-01"]


def test_no_release_dates_capability():
    p = FredAlfredProvider(api_key="k", client=FakeFredClient())
    names = [c.name for c in p.capabilities()]
    assert "macro.get_release_dates" not in names
    assert "macro.get_vintage_dates" in names


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


def test_malformed_decision_date_rejected():
    client = FakeFredClient([{"date": "2024-06-01", "value": 5.5}])
    p = FredAlfredProvider(api_key="k", client=client)
    r = p.query("macro.compare_vintages", {"series_id": "DFF", "decision_date": "not-a-date"})
    assert r.status == "INVALID_REQUEST"

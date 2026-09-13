"""An empty JSON payload that looks fresh must be measurable.

analyst_data_history accumulated 18,772 rows with payload = {} from 2026-08-01.
Every one had a current as_of, so every freshness check read the table as live
while it carried nothing. No range/min/max/finite rule can see this: there is no
value to be off-scale. `required_fields` counts payloads that say nothing inside
a window and fails when they exceed the contract's share.

The SQL builder and the threshold arithmetic are pure; the cursor is faked. No
database is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import data_plausibility_monitor as dpm  # noqa: E402

CONTRACTS = json.loads((ROOT / "config" / "data_plausibility_contracts.json").read_text())["contracts"]

MOTIVATING = {
    "table": "analyst_data_history",
    "column": "payload",
    "rule": "required_fields",
    "window_column": "as_of",
    "window_days": 30,
    "max_empty_pct": 50.0,
    "severity": "BLOCK",
}


class _Cursor:
    """A cursor that returns one prepared (empty, total) row and records the SQL."""

    def __init__(self, empty, total):
        self.row = (empty, total)
        self.sql = None

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.row


# ── the SQL ──────────────────────────────────────────────────────────────────


def test_empty_payload_predicate_counts_null_empty_object_null_literal_and_empty_array():
    pred = dpm._empty_payload_predicate(MOTIVATING)
    assert '"payload" IS NULL' in pred
    assert "'{}'::jsonb" in pred
    assert "'null'::jsonb" in pred
    assert "'[]'::jsonb" in pred


def test_declared_fields_are_required_to_be_present_and_non_null():
    c = dict(MOTIVATING, fields=["recommendation_mean", "target_mean"])
    pred = dpm._empty_payload_predicate(c)
    assert "->> 'recommendation_mean') IS NULL" in pred
    assert "->> 'target_mean') IS NULL" in pred


def test_a_field_name_with_a_quote_is_escaped_not_injected():
    c = dict(MOTIVATING, fields=["o'brien"])
    assert "'o''brien'" in dpm._empty_payload_predicate(c)


def test_the_query_is_windowed_on_the_declared_column():
    sql = dpm._required_fields_sql(MOTIVATING)
    assert 'FROM analyst_data_history' in sql
    assert '"as_of" > now() - interval \'30 days\'' in sql
    assert "count(*) FILTER (WHERE" in sql


def test_window_defaults_are_created_at_and_30_days():
    sql = dpm._required_fields_sql({"table": "t", "column": "c", "rule": "required_fields"})
    assert '"created_at" > now() - interval \'30 days\'' in sql


def test_violation_predicate_returns_empty_for_the_population_rule_like_single_scale():
    assert dpm._violation_predicate(MOTIVATING) == ""
    assert dpm._violation_predicate({"column": "c", "rule": "single_scale"}) == ""


def test_an_unknown_rule_still_raises():
    with pytest.raises(ValueError):
        dpm._violation_predicate({"column": "c", "rule": "vibes"})


# ── the threshold ────────────────────────────────────────────────────────────


def test_the_motivating_case_is_a_violation():
    """18,772 empty of ~19,000 in the window: the majority, so a violation."""
    cur = _Cursor(18772, 19100)
    r = dpm._check_required_fields(cur, MOTIVATING)
    assert r["violations"] == 18772
    assert r["total"] == 19100
    assert "98.3%" in r["detail"]
    assert "analyst_data_history" in cur.sql


def test_a_minority_of_empty_payloads_is_NOT_a_violation():
    """Negative control: a symbol with no coverage legitimately yields {}; a few are fine."""
    r = dpm._check_required_fields(_Cursor(300, 19100), MOTIVATING)
    assert r["violations"] == 0
    assert r["total"] == 19100


def test_exactly_at_the_threshold_is_not_a_violation_and_one_more_is():
    c = dict(MOTIVATING, max_empty_pct=50.0)
    assert dpm._check_required_fields(_Cursor(50, 100), c)["violations"] == 0
    assert dpm._check_required_fields(_Cursor(51, 100), c)["violations"] == 51


def test_an_empty_window_is_not_a_violation():
    """Zero rows in the window is a freshness problem for another gate, not an empty-payload one."""
    r = dpm._check_required_fields(_Cursor(0, 0), MOTIVATING)
    assert r["violations"] == 0 and r["total"] == 0


def test_a_zero_tolerance_contract_fails_on_a_single_empty_payload():
    c = dict(MOTIVATING, max_empty_pct=0)
    assert dpm._check_required_fields(_Cursor(1, 1000), c)["violations"] == 1


def test_null_counts_from_the_driver_are_tolerated():
    r = dpm._check_required_fields(_Cursor(None, None), MOTIVATING)
    assert r["violations"] == 0


# ── the contract file ────────────────────────────────────────────────────────


def test_the_motivating_contract_is_declared():
    c = next(x for x in CONTRACTS if x["table"] == "analyst_data_history" and x["column"] == "payload")
    assert c["rule"] == "required_fields"
    assert c["severity"] == "BLOCK"
    assert c["window_column"] == "as_of"
    assert 0 < c["max_empty_pct"] < 100
    assert "18,772" in c["_why"]


def test_every_declared_rule_is_one_the_monitor_implements():
    for c in CONTRACTS:
        if c["rule"] in ("single_scale", "required_fields"):
            continue
        dpm._violation_predicate(c)  # raises on an unknown rule

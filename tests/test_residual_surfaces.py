#!/usr/bin/env python3
"""The five residual surfaces, under every state they must survive.

Each surface previously had the same failure: a number that read as settled while
the thing behind it was unresolved, absent, or two different things sharing a
label. These tests drive each projection through populated, empty, partial,
stale, malformed, disconnected, unauthorized, forbidden and error, and pin the
specific lie each one replaces.

No network, broker, order, scheduler or production path.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.residual_surfaces import (  # noqa: E402
    BLOCKED_GATE,
    DEGRADED,
    DISCONNECTED,
    ERROR,
    FORBIDDEN,
    HELD,
    INFERRED,
    LEGITIMATE_EMPTY,
    LOADING,
    MALFORMED,
    MANUAL,
    OBSERVED,
    PARTIAL,
    POPULATED,
    PRODUCING_NOT_ADOPTED,
    READY,
    STALE,
    STALE_INPUT,
    TERMINAL_STATES,
    UNAUTHORIZED,
    WASH_BLOCKED,
    WORKING_END_TO_END,
    closed_loop_separation,
    reentry_infer_historical,
    reentry_projection,
    reentry_row_status,
    research_provenance,
    watch_projection,
    writer_status,
)

NOW = datetime(2026, 9, 3, 20, 0, 0, tzinfo=timezone.utc)


def ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


# ── Watch ────────────────────────────────────────────────────────────────────


def _watch(n=5, **over):
    items = [
        {"symbol": f"S{i}", "held": i < 2, "starred": i == 0, "in_directive_watch": True, "status": "researched"}
        for i in range(n)
    ]
    d = {"items": items, "count": n, "as_of": ago(1)}
    d.update(over)
    return d


def test_watch_counts_all_come_from_one_population():
    r = watch_projection(_watch(5), now=NOW)
    assert r["state"] == POPULATED
    c = r["counts"]
    assert c["catalog"] == 5 and c["held"] == 2 and c["starred"] == 1 and c["matched"] == 5
    assert r["counts_authoritative"] is True
    assert "none is read" in r["counts_population_rule"]


def test_watch_withholds_counts_while_loading():
    """The defect: summary counts stayed authoritative while the list resolved."""
    r = watch_projection(None)
    assert r["state"] == LOADING
    assert r["counts"] is None
    assert r["counts_authoritative"] is False


def test_watch_loading_always_terminates_into_a_named_state():
    for payload, status, err, expected in [
        (_watch(3), None, None, POPULATED),
        (_watch(0, count=0), None, None, LEGITIMATE_EMPTY),
        (_watch(3, as_of=ago(48)), None, None, STALE),
        ({"items": "nope"}, None, None, MALFORMED),
        (None, 401, None, UNAUTHORIZED),
        (None, 403, None, FORBIDDEN),
        (None, 500, None, ERROR),
        (None, None, "socket hang up", DISCONNECTED),
    ]:
        r = watch_projection(payload, http_status=status, error=err, now=NOW)
        assert r["state"] == expected, (expected, r["state"])
        assert r["terminal"] is True
        assert r["state_reason"]


def test_watch_filter_that_empties_the_catalog_is_degraded_not_empty():
    """An initial filter must not silently look like an empty watchlist."""
    r = watch_projection(_watch(5), filters={"status": "no-such-status"}, now=NOW)
    assert r["state"] == DEGRADED
    assert r["filters_eliminate_catalog"] is True
    assert "the filter is" in r["state_reason"]
    assert r["counts"]["catalog"] == 5, "the catalogue is still 5; only the filtered view is 0"


def test_watch_declared_total_mismatch_is_partial():
    r = watch_projection(_watch(3, count=99), now=NOW)
    assert r["state"] == PARTIAL
    assert "declares 99" in r["state_reason"]


def test_watch_makes_no_provider_calls():
    r = watch_projection(_watch(2), now=NOW)
    assert r["provider_calls_on_load"] == 0
    assert "calls no provider" in r["provider_call_rule"]


# ── Closed Loop ──────────────────────────────────────────────────────────────


def test_closed_loop_has_four_named_lanes():
    r = closed_loop_separation({}, now=NOW)
    assert {x["lane"] for x in r["lanes"]} == {
        "cio_decision_lineage",
        "hermes_outcome_feedback",
        "research_to_thesis",
        "outcome_to_lesson",
    }
    for lane in r["lanes"]:
        assert lane["authority_ceiling"]
        assert lane["state_reason"]


def test_a_stale_hermes_lane_does_not_age_cio_lineage():
    """The exact defect: one loop's silence made the other read as stale."""
    r = closed_loop_separation(
        {
            "hermes_outcome_feedback": {"latest_artifact_at": ago(24 * 30), "count": 3, "producer": "hermes"},
            "cio_decision_lineage": {"latest_artifact_at": ago(1), "count": 12, "producer": "cio"},
        },
        now=NOW,
    )
    states = r["lane_states"]
    assert states["hermes_outcome_feedback"] == STALE
    assert states["cio_decision_lineage"] == POPULATED
    assert "never propagates" in r["independence_rule"]


def test_a_lane_with_nothing_is_empty_not_stale():
    r = closed_loop_separation({"outcome_to_lesson": {}}, now=NOW)
    lane = next(x for x in r["lanes"] if x["lane"] == "outcome_to_lesson")
    assert lane["state"] == LEGITIMATE_EMPTY


def test_a_lane_error_is_reported_as_error():
    r = closed_loop_separation({"cio_decision_lineage": {"error": "producer unreachable"}}, now=NOW)
    lane = next(x for x in r["lanes"] if x["lane"] == "cio_decision_lineage")
    assert lane["state"] == ERROR and "unreachable" in lane["state_reason"]


def test_an_unparseable_lane_timestamp_is_malformed():
    r = closed_loop_separation({"research_to_thesis": {"latest_artifact_at": "whenever", "count": 1}}, now=NOW)
    lane = next(x for x in r["lanes"] if x["lane"] == "research_to_thesis")
    assert lane["state"] == MALFORMED


# ── Research provenance ──────────────────────────────────────────────────────


def test_stale_topics_and_missing_coverage_are_different_answers():
    r = research_provenance(
        {
            "as_of": ago(1),
            "by_category": {
                "has_stale": {"count": 5, "stale": 2, "fresh": 3, "avg_age_h": 100},
                "uncovered": {"count": 0, "stale": 0, "fresh": 0},
                "current": {"count": 4, "stale": 0, "fresh": 4, "needs_refresh": 0, "avg_age_h": 2},
            },
        },
        now=NOW,
    )
    assert r["stale_topics"] == ["has_stale"]
    assert r["missing_coverage"] == ["uncovered"]
    assert r["decision_eligible"] is False


def test_an_expected_category_that_is_absent_is_missing_coverage():
    r = research_provenance(
        {"as_of": ago(1), "by_category": {"a": {"count": 3, "fresh": 3, "avg_age_h": 1}}},
        expected_categories=["a", "never_ran"],
        now=NOW,
    )
    assert "never_ran" in r["missing_coverage"]


def test_the_four_freshness_layers_are_reported_separately():
    r = research_provenance(
        {
            "as_of": ago(1),
            "artifact_as_of": ago(30),
            "adopted_as_of": ago(200),
            "by_category": {"a": {"count": 1, "fresh": 1, "avg_age_h": 1}},
        },
        now=NOW,
    )
    layers = r["freshness_layers"]
    assert set(layers) == {"source_acquisition", "research_row", "durable_artifact", "consumer_adoption"}
    assert layers["source_acquisition"]["age_hours"] < layers["durable_artifact"]["age_hours"]
    assert layers["durable_artifact"]["age_hours"] < layers["consumer_adoption"]["age_hours"]


def test_research_is_evidence_not_canonical_financial_truth():
    r = research_provenance({"as_of": ago(1), "by_category": {}}, now=NOW)
    assert r["evidence_class"] == "EVIDENCE_NOT_CANONICAL_FINANCIAL_TRUTH"
    assert "never become a canonical financial fact" in r["evidence_note"]


def test_malformed_research_payload_is_named():
    assert research_provenance({"by_category": []}, now=NOW)["state"] == MALFORMED
    assert research_provenance(None)["state"] == LOADING


# ── Writer status ────────────────────────────────────────────────────────────


def test_a_manual_writer_never_implies_automatic_minting():
    """The specific lie: a thesis surface implying a schedule mints output."""
    r = writer_status({"thesis": {"kind": "thesis", "declared": True, "configured": True, "manual": True}}, now=NOW)
    row = r["writers"][0]
    assert row["state"] == MANUAL
    assert row["implies_automatic_minting"] is False
    assert r["manual_writers"] == ["thesis"]
    assert "never be rendered as if a schedule mints" in r["rule"]


def test_producing_is_not_adopting():
    r = writer_status(
        {
            "council": {
                "declared": True,
                "configured": True,
                "scheduled": True,
                "enabled": True,
                "last_attempt": ago(2),
                "last_success": ago(2),
                "last_nonempty_output": ago(2),
                "last_durable_write": ago(2),
            }
        },
        now=NOW,
    )
    assert r["writers"][0]["state"] == PRODUCING_NOT_ADOPTED


def test_a_fully_working_writer_is_named_as_such():
    r = writer_status(
        {
            "specialist": {
                "declared": True,
                "configured": True,
                "scheduled": True,
                "enabled": True,
                "last_attempt": ago(1),
                "last_success": ago(1),
                "last_nonempty_output": ago(1),
                "last_durable_write": ago(1),
                "last_adopted_output": ago(1),
            }
        },
        now=NOW,
    )
    assert r["writers"][0]["state"] == WORKING_END_TO_END


@pytest.mark.parametrize(
    "spec,expected",
    [
        ({"declared": False}, "ABSENT"),
        ({"declared": True, "configured": False}, "ABSENT"),
        ({"declared": True, "configured": True, "scheduled": True, "enabled": False}, "PAUSED"),
        ({"declared": True, "configured": True, "enabled": True, "failure_reason": "boom"}, "BROKEN"),
        ({"declared": True, "configured": True, "enabled": True, "last_attempt": ago(1)}, "BROKEN"),
        ({"declared": True, "configured": True, "enabled": True}, "UNKNOWN"),
    ],
)
def test_each_writer_state_is_reachable(spec, expected):
    r = writer_status({"w": spec}, now=NOW)
    assert r["writers"][0]["state"] == expected


def test_a_writer_that_has_gone_quiet_is_stale_not_working():
    r = writer_status(
        {
            "w": {
                "declared": True,
                "configured": True,
                "scheduled": True,
                "enabled": True,
                "last_attempt": ago(500),
                "last_success": ago(500),
                "last_durable_write": ago(500),
                "last_adopted_output": ago(500),
            }
        },
        now=NOW,
    )
    assert r["writers"][0]["state"] == STALE


def test_all_eight_signals_are_exposed():
    r = writer_status({"w": {"declared": True, "configured": True}}, now=NOW)
    row = r["writers"][0]
    for f in (
        "declared",
        "configured",
        "scheduled",
        "enabled",
        "last_attempt",
        "last_success",
        "last_nonempty_output",
        "last_durable_write",
        "last_adopted_output",
        "freshness_hours",
        "failure_reason",
        "authority",
    ):
        assert f in row


# ── Re-entry ─────────────────────────────────────────────────────────────────


def _row(**over):
    d = {
        "symbol": "AAA",
        "gates": [{"id": "fresh", "pass": True, "label": "Fresh quote"}],
        "price_age_h": 0.1,
        "held": False,
        "wash_blocked": False,
    }
    d.update(over)
    return d


def test_every_row_gets_one_canonical_status():
    """The defect: the served desk carries gates and no status at all."""
    r = reentry_row_status(_row())
    assert r["status"] == READY
    assert r["state_reason"]
    assert r["observation_class"] == OBSERVED
    assert r["contributing_gates"]
    assert r["account_scope"]


@pytest.mark.parametrize(
    "over,expected",
    [
        ({"held": True}, HELD),
        ({"wash_blocked": True, "wash_until": "2026-09-30"}, WASH_BLOCKED),
        ({"gates": [{"id": "rsi", "pass": False, "label": "RSI"}]}, BLOCKED_GATE),
        ({"gates": []}, "UNKNOWN"),
        ({"price_age_h": 99}, STALE_INPUT),
    ],
)
def test_each_reentry_status_is_reachable(over, expected):
    assert reentry_row_status(_row(**over))["status"] == expected


def test_held_beats_every_other_signal():
    r = reentry_row_status(_row(held=True, wash_blocked=True, price_age_h=99))
    assert r["status"] == HELD


def test_the_projection_carries_version_scope_and_calculated_time():
    payload = {
        "version": "reentry-desk-v2",
        "computed_at": ago(0.5),
        "criteria": {"stale_hours": 6},
        "rows": [_row(), _row(symbol="BBB", held=True)],
    }
    r = reentry_projection(payload, now=NOW)
    assert r["state"] == POPULATED
    assert r["contract_version"] == "reentry-desk-v2"
    assert r["calculated_at"] == payload["computed_at"]
    assert r["calculated_age_hours"] is not None
    assert r["criteria"]["stale_hours"] == 6
    assert r["status_counts"] == {HELD: 1, READY: 1}


def test_historical_inference_is_never_rewritten_as_observed():
    r = reentry_infer_historical({"symbol": "OLD", "held": True, "date": "2025-01-01"})
    assert r["observation_class"] == INFERRED
    assert r["never_rewritten_as_observed"] is True
    assert r["inference_rule"] and r["inference_rule_version"]
    assert r["status"] == HELD


@pytest.mark.parametrize(
    "status,err,expected",
    [(401, None, UNAUTHORIZED), (403, None, FORBIDDEN), (500, None, ERROR), (None, "reset", DISCONNECTED)],
)
def test_reentry_transport_states(status, err, expected):
    r = reentry_projection(None, http_status=status, error=err)
    assert r["state"] == expected and r["terminal"] is True


def test_reentry_malformed_and_empty():
    assert reentry_projection({"rows": "nope"})["state"] == MALFORMED
    assert reentry_projection({"rows": []})["state"] == LEGITIMATE_EMPTY
    assert reentry_projection(None)["state"] == LOADING


# ── wiring ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "route",
    [
        "/api/v2/watch/projection",
        "/api/v2/closed-loop/separation",
        "/api/v2/research-intelligence/provenance",
        "/api/v2/writers/status",
        "/api/v2/reentry/status",
    ],
)
def test_each_surface_is_registered_in_the_route_table(route):
    assert f'"{route}"' in (ROOT / "scripts" / "api_v2.py").read_text(errors="replace")


def test_the_surface_wrapper_fails_closed():
    import ast

    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_residual_surface")
    src = ast.dump(fn)
    assert "ERROR" in src and "state_reason" in src
    assert any(isinstance(h, ast.ExceptHandler) for h in ast.walk(fn))


def test_every_projection_declares_read_only_authority():
    for fn, args in (
        (watch_projection, (_watch(1),)),
        (closed_loop_separation, ({},)),
        (research_provenance, ({"by_category": {}},)),
        (writer_status, ({},)),
        (reentry_projection, ({"rows": []},)),
    ):
        assert fn(*args)["authority"] == "READ_ONLY_ADVISORY"


def test_terminal_states_do_not_include_loading():
    assert LOADING not in TERMINAL_STATES

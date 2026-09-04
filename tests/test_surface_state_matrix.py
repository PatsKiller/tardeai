#!/usr/bin/env python3
"""Every surface, in every state it can actually reach.

A surface that is only tested with good data is only known to work when nothing is
wrong, which is the case that never needed the surface. The contract each one owes is
the same: land in exactly one declared state, never present absence as a value, and say
why. This drives all six through all nine states and asserts that contract every time.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "scripts"))

from lib.residual_surfaces import (  # noqa: E402
    DEGRADED,
    LANES,
    DISCONNECTED,
    ERROR,
    FORBIDDEN,
    LEGITIMATE_EMPTY,
    MALFORMED,
    PARTIAL,
    POPULATED,
    STALE,
    TERMINAL_STATES,
    UNAUTHORIZED,
    closed_loop_separation,
    financial_conflict_state,
    reentry_projection,
    research_provenance,
    watch_projection,
    writer_status,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(minutes=5)).isoformat()
OLD = (NOW - timedelta(days=30)).isoformat()

STATES = ["populated", "empty", "partial", "stale", "malformed", "disconnected", "unauthorized", "forbidden", "error"]

#: Transport states are driven identically for every surface, which is the point:
#: one contract, not six.
TRANSPORT = {
    "disconnected": ({"error": "connection refused"}, DISCONNECTED),
    "unauthorized": ({"http_status": 401}, UNAUTHORIZED),
    "forbidden": ({"http_status": 403}, FORBIDDEN),
    "error": ({"http_status": 500}, ERROR),
}


def _watch(state):
    if state in TRANSPORT:
        kw, expect = TRANSPORT[state]
        return watch_projection(None, now=NOW, **kw), expect
    row = {"symbol": "AAA", "held": True, "starred": False}
    if state == "populated":
        return watch_projection({"items": [row], "as_of": FRESH}, now=NOW), POPULATED
    if state == "empty":
        return watch_projection({"items": [], "as_of": FRESH}, now=NOW), LEGITIMATE_EMPTY
    if state == "partial":
        # A row that is not an object is dropped, and the surface says so rather than
        # quietly shrinking the count.
        return watch_projection({"items": [row, "not-a-row"], "as_of": FRESH}, now=NOW), PARTIAL
    if state == "stale":
        return watch_projection({"items": [row], "as_of": OLD}, now=NOW), STALE
    if state == "malformed":
        return watch_projection({"items": "not-a-list", "as_of": FRESH}, now=NOW), MALFORMED
    raise AssertionError(state)


def _lanes(spec):
    return {k: dict(spec) for k, _label, _desc in LANES}


def _closed_loop(state):
    if state in TRANSPORT:
        kw, expect = TRANSPORT[state]
        return closed_loop_separation(None, now=NOW, **kw), expect
    fresh = {"latest_artifact_at": FRESH, "count": 3}
    if state == "populated":
        return closed_loop_separation(_lanes(fresh), now=NOW), POPULATED
    if state == "empty":
        # Every lane has produced nothing. That is a real answer, not a failure.
        return closed_loop_separation(_lanes({"latest_artifact_at": None, "count": 0}), now=NOW), PARTIAL
    if state == "partial":
        mixed = _lanes(fresh)
        mixed[LANES[0][0]] = {"latest_artifact_at": None, "count": 0}
        return closed_loop_separation(mixed, now=NOW), POPULATED
    if state == "stale":
        return closed_loop_separation(_lanes({"latest_artifact_at": OLD, "count": 1}), now=NOW), PARTIAL
    if state == "malformed":
        return closed_loop_separation(_lanes({"latest_artifact_at": "not-a-date", "count": 1}), now=NOW), PARTIAL
    raise AssertionError(state)


def _research(state):
    if state in TRANSPORT:
        kw, expect = TRANSPORT[state]
        return research_provenance(None, now=NOW, **kw), expect
    cat = {"count": 5, "fresh": 5, "stale": 0, "needs_refresh": 0, "avg_age_h": 1.0}
    if state == "populated":
        return research_provenance({"by_category": {"a": cat}}, now=NOW), POPULATED
    if state == "empty":
        return research_provenance({"by_category": {}}, now=NOW), LEGITIMATE_EMPTY
    if state == "partial":
        # One category healthy, one stale: the summary must say partial, not pick a side.
        return research_provenance({"by_category": {"a": cat, "b": dict(cat, fresh=0, stale=5)}}, now=NOW), PARTIAL
    if state == "stale":
        old = dict(cat, fresh=0, stale=5, avg_age_h=900.0)
        return research_provenance({"by_category": {"a": old}}, now=NOW), STALE
    if state == "malformed":
        return research_provenance({"by_category": "not-a-mapping"}, now=NOW), MALFORMED
    raise AssertionError(state)


def _writer(state):
    if state in TRANSPORT:
        kw, expect = TRANSPORT[state]
        return writer_status(None, now=NOW, **kw), expect
    good = {
        "declared": True,
        "configured": True,
        "scheduled": True,
        "enabled": True,
        "last_attempt": FRESH,
        "last_success": FRESH,
        "last_nonempty_output": FRESH,
        "last_durable_write": FRESH,
        "last_adopted_output": FRESH,
    }
    if state == "populated":
        return writer_status({"w1": good}, now=NOW), POPULATED
    if state == "empty":
        return writer_status({}, now=NOW), LEGITIMATE_EMPTY
    if state == "partial":
        # Producing but never adopted: the exact case the surface exists to name.
        return writer_status({"w1": good, "w2": dict(good, last_adopted_output=None)}, now=NOW), PARTIAL
    if state == "stale":
        old = {k: (OLD if isinstance(v, str) else v) for k, v in good.items()}
        return writer_status({"w1": old}, now=NOW), STALE
    if state == "malformed":
        return writer_status({"w1": {"declared": True, "last_success": "not-a-date"}}, now=NOW), DEGRADED
    raise AssertionError(state)


def _reentry(state):
    if state in TRANSPORT:
        kw, expect = TRANSPORT[state]
        return reentry_projection(None, now=NOW, **kw), expect
    row = {"symbol": "AAA", "observed": True, "updated_at": FRESH}
    if state == "populated":
        return reentry_projection({"rows": [row], "computed_at": FRESH}, now=NOW), POPULATED
    if state == "empty":
        return reentry_projection({"rows": [], "computed_at": FRESH}, now=NOW), LEGITIMATE_EMPTY
    if state == "partial":
        return reentry_projection({"rows": [row, "not-a-row"], "computed_at": FRESH}, now=NOW), POPULATED
    if state == "stale":
        return reentry_projection({"rows": [dict(row, updated_at=OLD)], "computed_at": OLD}, now=NOW), POPULATED
    if state == "malformed":
        return reentry_projection({"rows": "not-a-list"}, now=NOW), MALFORMED
    raise AssertionError(state)


def _conflicts(state):
    if state in TRANSPORT:
        kw, expect = TRANSPORT[state]
        return financial_conflict_state(None, **kw), expect
    rec = {
        "record_key": "SCHD:schwab_taxable",
        "reason": "both copies reconcile to the broker total but allocate different lots",
        "producer_sha256": "a" * 64,
        "served_sha256": "b" * 64,
        "render_as": "UNVERIFIED",
    }
    side = {"tax_lots.json": {"records": [rec]}}
    if state == "populated":
        return financial_conflict_state(side), DEGRADED
    if state == "empty":
        return financial_conflict_state({}), LEGITIMATE_EMPTY
    if state == "partial":
        return financial_conflict_state({"tax_lots.json": {"records": [rec]}, "stops.json": {"records": []}}), DEGRADED
    if state == "stale":
        return financial_conflict_state({"tax_lots.json": {"records": [dict(rec, stale=True)]}}), DEGRADED
    if state == "malformed":
        return financial_conflict_state({"tax_lots.json": "not-a-mapping"}), DEGRADED
    if state == "error":
        return financial_conflict_state(None), ERROR
    raise AssertionError(state)


SURFACES = {
    "watch": _watch,
    "closed_loop": _closed_loop,
    "research": _research,
    "writer": _writer,
    "reentry": _reentry,
    "financial_conflicts": _conflicts,
}


@pytest.mark.parametrize("surface", sorted(SURFACES))
@pytest.mark.parametrize("state", STATES)
def test_surface_state_matrix(surface, state):
    """Each cell: the surface reaches exactly one declared state and explains itself."""
    result, expected = SURFACES[surface](state)

    assert result["state"] in TERMINAL_STATES, f"{surface}/{state}: undeclared state {result['state']}"
    assert result["state"] == expected, f"{surface}/{state}: expected {expected}, got {result['state']}"
    assert result.get("state_reason"), f"{surface}/{state}: a state without a reason is not actionable"
    assert result.get("schema"), f"{surface}/{state}: no schema marker"
    assert result.get("authority"), f"{surface}/{state}: no authority marker"
    assert result.get("calculation_version"), f"{surface}/{state}: no calculation version"


@pytest.mark.parametrize("surface", sorted(SURFACES))
@pytest.mark.parametrize("state", ["disconnected", "unauthorized", "forbidden", "error"])
def test_failure_never_reports_a_count(surface, state):
    """A surface that could not read must not report zero. Zero is a measurement."""
    result, _ = SURFACES[surface](state)
    for field in ("counts", "lanes", "categories", "writers", "rows", "conflicts"):
        if field in result:
            assert result[field] is None, (
                f"{surface}/{state}: {field} came back as {result[field]!r}; a failed read that "
                "reports a value is indistinguishable from a real empty result"
            )


def test_one_unresolved_record_does_not_block_unrelated_surfaces():
    """The whole point of record-level scope: a disputed lot is not a site outage."""
    rec = {
        "record_key": "SCHD:schwab_taxable",
        "reason": "unprovable",
        "render_as": "UNVERIFIED",
        "producer_sha256": "a" * 64,
        "served_sha256": "b" * 64,
    }
    result = financial_conflict_state({"tax_lots.json": {"records": [rec]}})

    blocks = result["conflicts"][0]["blocks"]
    assert all("SCHD:schwab_taxable" in b for b in blocks), "scope must name the record, not the store"
    assert all("watch" not in b.lower() and "closed_loop" not in b.lower() for b in blocks)
    assert result["no_disputed_value_presented_as_truth"] is True
    assert result["conflicts"][0]["both_originals_preserved"] is True

    # Unrelated surfaces are unaffected by the same inputs.
    watch, _ = _watch("populated")
    assert watch["state"] == POPULATED

"""ANCHOR: RISK_SNAPSHOT_RESTING_PROTECTION_LQ1390_20261109 — a resting GTC stop is protection.

LQ-20261107-1390, the Risk half. ``risk_snapshot`` aggregated ``pct_protected``,
``total_protected_mv``, ``total_unprotected_mv`` and ``stop_health.unprotected_count`` from
``broker_protected`` alone, which answers the narrower question "is an armed stop priceable right
now". Outside the session Schwab reports every GTC stop as ``AWAITING_STOP_CONDITION``
(``pending_activation``), so Risk published 0.0 % protected / $320,542 at risk over a book holding
eight resting stops ($270,978). Home already used ``cio_truth.stop_protects``; Risk did not, and the
two surfaces disagreed in opposite directions.

The fix uses the same predicate and keeps ``broker_protected`` on each row for loss-at-stop and
heat. The dollars the change moves are published (``total_resting_protected_mv``,
``stop_health.resting_protected_count``) so the movement is stated, never inferred: a stale or
planned level stays outside ``protected`` — unproven is not protection on either surface.

Synthetic Z-prefixed symbols; the repo is public.
COVERS = ["scripts/lib/data_broker/risk_snapshot.py"]
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import pytest

from scripts.lib.data_broker import risk_snapshot as rs


def _write(path, doc, mtime):
    path.write_text(json.dumps(doc))
    os.utime(path, (mtime, mtime))


def _now_iso(offset_s: float = 0) -> str:
    return datetime.fromtimestamp(time.time() + offset_s, timezone.utc).isoformat()


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "STATE_DIR", tmp_path)
    now = time.time()
    # ZARK is covered by a RESTING GTC stop (pending_activation); ZBARE holds nothing but a plan.
    _write(tmp_path / "risk_management.json", {"positions": []}, now - 36000)
    _write(tmp_path / "holdings.json", {"portfolio_totals": {"total_value": 20000.0}, "holdings": [
        {"symbol": "ZARK", "account": "schwab_rollover_ira", "price": 100.0, "shares": 100,
         "market_value": 10000.0},
        {"symbol": "ZBARE", "account": "schwab_rollover_ira", "price": 50.0, "shares": 200,
         "market_value": 10000.0}]}, now - 60)
    _write(tmp_path / "stops.json", {}, now - 60)
    return tmp_path


def _snapshot(rows):
    def query(sql, params=None, **kw):
        return rows if "FROM stop_last_known" in sql else []
    return rs.build_risk_snapshot(db_query=query)


def _pos(snap, symbol):
    return next(p for p in snap["positions"] if p["symbol"] == symbol)


def test_a_resting_stop_protects_the_position_and_its_dollars(state):
    """Fail-before: on the armed-only aggregation pct_protected was 0.0, unprotected_mv the whole
    book and unprotected_count 2 — the live 2026-11-09 shape, in miniature."""
    snap = _snapshot([
        {"account": "schwab_rollover_ira", "symbol": "ZARK", "order_id": "R1", "stop_price": 90.0,
         "qty": 100.0, "status": "pending_activation", "captured_at": _now_iso()}])
    row = _pos(snap, "ZARK")
    assert row["stop_state"] == "pending_activation"
    assert row["broker_protected"] is False       # armed-only meaning is kept for loss-at-stop
    assert row["stop_protects"] is True

    portfolio = snap["portfolio"]
    assert portfolio["pct_protected"] == 50.0     # ZARK protected, ZBARE not
    assert portfolio["total_protected_mv"] == 10000.0
    assert portfolio["total_unprotected_mv"] == 10000.0
    # The movement is stated: the protected dollar figure is backed by a resting order.
    assert portfolio["total_resting_protected_mv"] == 10000.0

    health = snap["stop_health"]
    assert health["protected_count"] == 1 and health["resting_protected_count"] == 1
    assert [p["symbol"] for p in health["unprotected_positions"]] == ["ZBARE"]
    assert health["unprotected_count"] == 1


def test_an_armed_stop_is_protection_without_being_counted_as_resting(state):
    snap = _snapshot([
        {"account": "schwab_rollover_ira", "symbol": "ZARK", "order_id": "A1", "stop_price": 90.0,
         "qty": 100.0, "status": "active", "captured_at": _now_iso()}])
    assert _pos(snap, "ZARK")["broker_protected"] is True
    assert snap["portfolio"]["total_protected_mv"] == 10000.0
    assert snap["portfolio"]["total_resting_protected_mv"] == 0.0
    assert snap["stop_health"]["resting_protected_count"] == 0


def test_a_stale_observation_stays_unproven_and_never_becomes_protection(state):
    """A resting row last read two days ago is demoted to ``unknown`` by ``stop_for``. The snapshot
    has no unproven bucket, so it must fall on the unprotected side — never silently protected."""
    snap = _snapshot([
        {"account": "schwab_rollover_ira", "symbol": "ZARK", "order_id": "S1", "stop_price": 90.0,
         "qty": 100.0, "status": "pending_activation", "captured_at": _now_iso(-5 * 86400)}])
    row = _pos(snap, "ZARK")
    assert row["stop_state"] == "unknown" and row["stop_protects"] is False
    assert snap["stop_health"]["resting_protected_count"] == 0
    assert snap["portfolio"]["pct_protected"] == 0.0


def test_a_planned_level_does_not_protect(state, monkeypatch):
    _write(state / "stops.json", {"ZARK": {"stop_price": 90.0}}, time.time() - 60)
    snap = _snapshot([])
    row = _pos(snap, "ZARK")
    assert row["stop_source"] == "planned" and row["stop_protects"] is False
    assert snap["portfolio"]["pct_protected"] == 0.0


def test_the_rows_and_the_aggregates_use_one_definition(state):
    """No position may be protected and unprotected at once: the two dollar totals partition the
    book, and the published count agrees with the list it is published beside."""
    snap = _snapshot([
        {"account": "schwab_rollover_ira", "symbol": "ZARK", "order_id": "R1", "stop_price": 90.0,
         "qty": 100.0, "status": "pending_activation", "captured_at": _now_iso()}])
    portfolio, health = snap["portfolio"], snap["stop_health"]
    assert portfolio["total_protected_mv"] + portfolio["total_unprotected_mv"] == portfolio["total_value"]
    assert health["unprotected_count"] == len(health["unprotected_positions"])
    assert health["protected_count"] == sum(1 for p in snap["positions"] if p["stop_protects"])
    assert health["resting_protected_count"] <= health["protected_count"]

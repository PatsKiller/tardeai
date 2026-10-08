"""Stop-health recovery requires exact, fresh positive evidence; never absence.

All saved reads, writes, broker scans and delivery boundaries are isolated.
Production timestamps, accounts and orders are neither read nor modified.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import alert_event_writer as writer
import positions_sync
import stop_health_check as health

# Construct the double without importing the adapter or installing it globally.
# Each test fixture owns the sys.modules patch and restores any prior module.
db_adapter = types.ModuleType("db_adapter")

NOW = datetime.now(timezone.utc)
CFG = {"stale_after_minutes_market": 30, "stale_after_hours_closed": 72, "qty_tolerance": 0.001}


def evidence(alert_id=11, **changes):
    row = {
        "alert_id": alert_id,
        "created_at": NOW - timedelta(hours=20),
        "lifecycle_state": "active",
        "symbol": "XYZ",
        "parsed_payload": {
            "kind": "stop_health",
            "condition": "OVERSIZED",
            "symbol": "XYZ",
            "account": "account_a",
            "order_id": "order_1",
            "broker": "test_broker",
        },
        "stop_account": "account_a",
        "stop_symbol": "XYZ",
        "stop_order_id": "order_1",
        "stop_status": "working",
        "stop_lifecycle": "working",
        "stop_health": "ok",
        "stop_coverage": "full",
        "stop_flags": [],
        "stop_qty": 100,
        "stop_held_qty": 100,
        "stop_snapshot_at": NOW - timedelta(minutes=1),
        "position_qty": 100,
        "position_as_of": NOW - timedelta(minutes=3),
        "position_source": "test_broker_read",
        "sync_run_id": 3,
        "sync_status": "complete",
        "sync_promoted": True,
        "sync_finished_at": NOW - timedelta(minutes=2),
        "account_sync_ok": True,
    }
    row.update(changes)
    return row


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unmocked external or mutation boundary")

    monkeypatch.setitem(sys.modules, "db_adapter", db_adapter)
    monkeypatch.setattr(db_adapter, "_get_conn", forbidden, raising=False)
    monkeypatch.setattr(writer, "resolve_alert_event_ids", forbidden)
    monkeypatch.setattr(writer, "save_alert_event", forbidden)
    monkeypatch.setattr(positions_sync, "load_sync_config", lambda: dict(CFG))


def plan(monkeypatch, rows, ids=None):
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda requested: deepcopy(rows))
    ids = ids if ids is not None else sorted({row["alert_id"] for row in rows})
    return health.plan_stop_recovery(ids, max_ids=10)


def test_exact_fresh_working_recovery_supports_legacy_structured_alert(monkeypatch):
    row = evidence()
    original = deepcopy(row)
    result = plan(monkeypatch, [row])

    assert result["dry_run"] is True
    assert result["blocked"] == []
    assert result["candidates"][0]["alert_id"] == 11
    assert result["candidates"][0]["reason"] == "fresh_exact_position_confirms_coverage"
    assert result["candidates"][0]["condition_key"].startswith("siem:v1:")
    assert row == original
    assert "account_a" not in str(result) and "order_1" not in str(result)


@pytest.mark.parametrize("status", ["cancelled", "canceled", "replaced", "rejected", "expired"])
def test_exact_terminal_observation_does_not_require_a_remaining_holding(monkeypatch, status):
    row = evidence(stop_status=status, stop_lifecycle="cancelled", stop_coverage="closed", position_qty=None)
    result = plan(monkeypatch, [row])
    assert result["candidates"][0]["reason"] == "terminal_stop_observed"


def test_stale_fill_uses_existing_monitor_age_policy(monkeypatch):
    row = evidence(stop_status="filled", stop_lifecycle="filled", stop_coverage="closed", stop_flags=["filled_stale"])
    assert plan(monkeypatch, [row])["candidates"][0]["reason"] == "filled_alert_window_elapsed"
    row["created_at"] = NOW - timedelta(hours=1)
    result = plan(monkeypatch, [row])
    assert result["candidates"] == []
    assert result["blocked"][0]["reason"] == "fill_not_proven_stale"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"stop_order_id": "other_order"}, "missing_exact_stop_observation"),
        ({"stop_account": "other_account"}, "missing_exact_stop_observation"),
        ({"stop_symbol": None}, "missing_exact_stop_observation"),
        ({"stop_health": "alert"}, "stop_still_unhealthy"),
        ({"stop_health": "warn"}, "stop_still_unhealthy"),
        ({"stop_flags": None}, "missing_condition_observation"),
        ({"stop_flags": "not-json"}, "missing_condition_observation"),
        ({"stop_qty": float("nan")}, "missing_positive_position"),
        ({"position_qty": None}, "missing_positive_position"),
        ({"position_qty": 0}, "missing_positive_position"),
        ({"position_qty": 200}, "position_quantity_conflict"),
        ({"stop_qty": 200}, "position_quantity_conflict"),
        ({"sync_status": "partial"}, "position_sync_incomplete"),
        ({"sync_status": "failed"}, "position_sync_incomplete"),
        ({"sync_promoted": False}, "position_sync_incomplete"),
        ({"account_sync_ok": False}, "position_sync_incomplete"),
        ({"sync_run_id": None}, "position_observation_not_coherent"),
        ({"position_as_of": NOW}, "position_observation_not_coherent"),
        ({"stop_snapshot_at": NOW - timedelta(days=4)}, "observation_not_newer"),
        ({"stop_snapshot_at": NOW + timedelta(days=1)}, "observation_not_newer"),
        ({"lifecycle_state": "acknowledged"}, "not_active"),
        ({"lifecycle_state": "resolved"}, "not_active"),
    ],
)
def test_incomplete_conflicting_or_unhealthy_evidence_never_resolves(monkeypatch, change, reason):
    result = plan(monkeypatch, [evidence(**change)])
    assert result["candidates"] == []
    assert result["blocked"] == [{"alert_id": 11, "reason": reason}]


def test_absence_and_duplicate_exact_rows_are_not_recovery(monkeypatch):
    assert plan(monkeypatch, [], ids=[11])["candidates"] == []
    duplicate = plan(monkeypatch, [evidence(), evidence()])
    assert duplicate["candidates"] == []
    assert duplicate["blocked"][0]["reason"] == "missing_or_conflicting_observations"


def test_stale_positions_fail_existing_freshness_contract(monkeypatch):
    row = evidence(
        created_at=NOW - timedelta(days=6),
        position_as_of=NOW - timedelta(days=4),
        sync_finished_at=NOW - timedelta(days=4),
    )
    result = plan(monkeypatch, [row])
    assert result["candidates"] == []
    assert result["blocked"][0]["reason"] == "stale_position_observation"


def test_stale_stop_snapshot_cannot_recover_even_when_positions_are_fresh(monkeypatch):
    row = evidence(created_at=NOW - timedelta(days=6), stop_snapshot_at=NOW - timedelta(days=4))
    result = plan(monkeypatch, [row])
    assert result["candidates"] == []
    assert result["blocked"][0]["reason"] == "stale_stop_observation"


def test_current_scan_requires_a_newly_persisted_snapshot(monkeypatch):
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda requested: [evidence()])
    result = health.plan_stop_recovery([11], max_ids=1, minimum_snapshot_at=NOW)
    assert result["candidates"] == []
    assert result["blocked"][0]["reason"] == "scan_not_persisted"


def test_fresh_shares_do_not_prove_a_near_trigger_price_recovered(monkeypatch):
    row = evidence()
    row["parsed_payload"]["condition"] = "NEAR_TRIGGER"
    result = plan(monkeypatch, [row])
    assert result["candidates"] == []
    assert result["blocked"][0]["reason"] == "fresh_price_or_terminal_evidence_required"


@pytest.mark.parametrize("ids,cap", [([11, 12], 1), ([11, 11], 2), ([True], 1), ([0], 1), ([11], 201)])
def test_invalid_or_over_cap_plan_is_refused_before_any_read(monkeypatch, ids, cap):
    def forbidden(ids):
        raise AssertionError("must reject before reads")

    monkeypatch.setattr(health, "_read_stop_recovery_rows", forbidden)
    with pytest.raises(ValueError):
        health.plan_stop_recovery(ids, max_ids=cap)


def test_read_error_is_not_a_clear_result(monkeypatch):
    def unavailable(ids):
        raise RuntimeError("saved observation unavailable")

    monkeypatch.setattr(health, "_read_stop_recovery_rows", unavailable)
    with pytest.raises(RuntimeError, match="unavailable"):
        health.plan_stop_recovery([11], max_ids=1)


def test_apply_revalidates_and_writes_only_reviewed_still_recovered_ids(monkeypatch):
    rows = [evidence(11), evidence(12)]
    reviewed = plan(monkeypatch, rows)
    rows[1]["stop_health"] = "alert"
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda requested: deepcopy(rows))
    calls = []
    monkeypatch.setattr(writer, "resolve_alert_event_ids", lambda ids, **kw: calls.append((ids, kw)) or ids)
    result = health.apply_stop_recovery(reviewed, max_ids=2, resolved_by="test:verified")

    assert result["resolved_ids"] == [11]
    assert calls[0][0] == [11]
    assert calls[0][1]["source_script"] == "stop_health"
    assert calls[0][1]["observed_before_or_at"] == rows[0]["stop_snapshot_at"]
    assert result["blocked"] == [{"alert_id": 12, "reason": "stop_still_unhealthy"}]


def test_apply_rejects_identity_change_since_review(monkeypatch):
    row = evidence()
    reviewed = plan(monkeypatch, [row])
    row["parsed_payload"]["order_id"] = row["stop_order_id"] = "replacement_order"
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda requested: [deepcopy(row)])
    result = health.apply_stop_recovery(reviewed, max_ids=1, resolved_by="test:verified")
    assert result["resolved_ids"] == []
    assert result["blocked"][0]["reason"] == "reviewed_evidence_changed"


def test_apply_reports_writer_failure_and_never_claims_resolution(monkeypatch):
    reviewed = plan(monkeypatch, [evidence()])

    def failed(*args, **kwargs):
        raise RuntimeError("DB write rejected")

    monkeypatch.setattr(writer, "resolve_alert_event_ids", failed)
    result = health.apply_stop_recovery(reviewed, max_ids=1, resolved_by="test:verified")
    assert result["ok"] is False
    assert result["resolved_ids"] == []
    assert result["error"] == "recovery_write_failed:RuntimeError"


def test_apply_refuses_candidate_id_outside_reviewed_requested_ids(monkeypatch):
    reviewed = plan(monkeypatch, [evidence(11)])
    reviewed["candidates"][0]["alert_id"] = 99
    writes = []
    monkeypatch.setattr(writer, "resolve_alert_event_ids", lambda ids, **kw: writes.append(ids) or ids)

    with pytest.raises(ValueError, match="invalid candidate IDs"):
        health.apply_stop_recovery(reviewed, max_ids=1, resolved_by="test:verified")
    assert writes == []


def test_apply_refuses_reviewed_candidates_over_apply_cap(monkeypatch):
    reviewed = plan(monkeypatch, [evidence(11), evidence(12)])
    writes = []
    monkeypatch.setattr(writer, "resolve_alert_event_ids", lambda ids, **kw: writes.append(ids) or ids)

    with pytest.raises(ValueError, match="within the cap"):
        health.apply_stop_recovery(reviewed, max_ids=1, resolved_by="test:verified")
    assert writes == []


def test_apply_refuses_regressed_observation_timestamp_with_unchanged_facts(monkeypatch):
    row = evidence()
    reviewed = plan(monkeypatch, [row])
    row["stop_snapshot_at"] -= timedelta(seconds=30)
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda ids: [deepcopy(row)])
    writes = []
    monkeypatch.setattr(writer, "resolve_alert_event_ids", lambda ids, **kw: writes.append(ids) or ids)

    result = health.apply_stop_recovery(reviewed, max_ids=1, resolved_by="test:verified")
    assert result["resolved_ids"] == []
    assert result["blocked"] == [{"alert_id": 11, "reason": "reviewed_evidence_changed"}]
    assert writes == []


def test_identity_survives_prose_and_quantity_changes_but_separates_account_and_order():
    payload = evidence()["parsed_payload"]
    key = health._stop_condition_key(payload)
    assert key == health._stop_condition_key({**payload, "qty": 150, "held_qty": 149})
    assert key != health._stop_condition_key({**payload, "account": "account_b"})
    assert key != health._stop_condition_key({**payload, "order_id": "order_2"})
    assert health._stop_condition_key({**payload, "order_id": None}) is None


@pytest.mark.parametrize(
    "scan",
    [
        {},
        {"stops": [], "generated_at": NOW.isoformat(), "summary": {"total": 0}},
        {"stops": [{}], "generated_at": NOW.isoformat(), "summary": {"total": 1}, "errors": ["scan failed"]},
        {"stops": [{}], "generated_at": NOW.isoformat(), "summary": {"total": 1}, "ok": False},
    ],
)
def test_failed_or_empty_scan_never_reads_or_resolves(scan):
    result = health._recover_current_scan(scan, NOW - timedelta(seconds=1))
    assert result["ok"] is False
    assert result["resolved_ids"] == []


def test_new_alerts_persist_stable_keys_and_dedupe_accounts_independently(monkeypatch):
    alerts = []
    for account, order in (("account_a", "order_1"), ("account_b", "order_1"), ("account_a", "order_2")):
        alerts.append(
            {
                "symbol": "XYZ",
                "account": account,
                "order_id": order,
                "flags": ["oversized"],
                "qty": 200,
                "held_qty": 100,
                "health": "alert",
                "coverage": "oversized",
                "broker": "test_broker",
                "lifecycle": "working",
                "stop_price": 10,
            }
        )
    scan = {"summary": {"total": 3, "by_health": {"alert": 3}}, "alerts": alerts}
    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", types.SimpleNamespace(scan=lambda **kw: scan))
    seen, saved, sent = set(), [], []

    def recently(symbol, key, hours=2):
        was_seen = key in seen
        seen.add(key)
        return was_seen

    monkeypatch.setattr(health, "_recently_alerted", recently)
    monkeypatch.setattr(health, "_siem", lambda *args: saved.append(args) or len(saved))
    monkeypatch.setattr(health, "_hermes_finding", lambda *args: None)
    monkeypatch.setattr(health, "_send_telegram", lambda message, **kw: sent.append(message))
    monkeypatch.setattr(health, "_pl_if_fired", lambda *args: None)
    monkeypatch.setattr(health, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(health, "_log_health_event", lambda **kw: None)

    health.run(quiet=True)
    health.run(quiet=True)
    assert len(saved) == 3 and len(sent) == 1
    assert len({args[3]["condition_key"] for args in saved}) == 3
    assert all(args[1] == "urgent" for args in saved)


def _saved_connection(monkeypatch, rows):
    queries = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql, params):
            assert sql.lstrip().startswith("SELECT")
            queries.append((sql, params))

        def fetchall(self):
            return rows

        def fetchone(self):
            return rows[0] if rows else None

    connection = types.SimpleNamespace(cursor=lambda: Cursor(), rollback=lambda: None)
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: connection)
    return queries


def test_dedupe_reader_uses_exact_key_and_excludes_resolved_history(monkeypatch):
    queries = _saved_connection(monkeypatch, [(1,)])
    payload = evidence()["parsed_payload"]
    first = health._stop_condition_key(payload)
    second = health._stop_condition_key({**payload, "account": "account_b"})

    assert health._recently_alerted("XYZ", first)
    assert health._recently_alerted("XYZ", second)
    assert queries[0][1] == ("stop_health", first, 2)
    assert queries[1][1] == ("stop_health", second, 2)
    assert "parsed_payload->>'condition_key'=%s" in queries[0][0]
    assert "<> 'resolved'" in queries[0][0]


def test_current_scan_recovers_only_matching_persisted_observation(monkeypatch):
    row = evidence()
    stop = {
        field: row["stop_" + field]
        for field in (
            "account",
            "order_id",
            "symbol",
            "status",
            "lifecycle",
            "health",
            "coverage",
            "flags",
            "qty",
            "held_qty",
        )
    }
    queries = _saved_connection(monkeypatch, [(11,)])
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda ids: [deepcopy(row)])
    calls = []
    monkeypatch.setattr(writer, "resolve_alert_event_ids", lambda ids, **kw: calls.append(ids) or ids)
    scan = {"generated_at": NOW.isoformat(), "summary": {"total": 1}, "stops": [stop]}

    result = health._recover_current_scan(scan, NOW - timedelta(minutes=2))
    assert result["ok"] is True
    assert result["resolved_ids"] == [11]
    assert calls == [[11]]
    assert "condition_key' IS NOT NULL" in queries[0][0], "legacy history requires explicit review"

    stop["held_qty"] = 90
    calls.clear()
    result = health._recover_current_scan(scan, NOW - timedelta(minutes=2))
    assert result["resolved_ids"] == [] and calls == []
    assert result["blocked"][0]["reason"] == "scan_observation_conflict"


def test_apply_refuses_changed_order_facts_even_when_newer_state_is_healthy(monkeypatch):
    row = evidence()
    reviewed = plan(monkeypatch, [row])
    row["stop_qty"] = row["stop_held_qty"] = row["position_qty"] = 50
    monkeypatch.setattr(health, "_read_stop_recovery_rows", lambda requested: [deepcopy(row)])
    result = health.apply_stop_recovery(reviewed, max_ids=1, resolved_by="test:verified")
    assert result["resolved_ids"] == []
    assert result["blocked"][0]["reason"] == "reviewed_evidence_changed"

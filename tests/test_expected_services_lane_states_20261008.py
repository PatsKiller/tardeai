"""2026-10-08: check_expected_services reported DISABLED:tradeai-due-checkpoints.timer as a P1 incident for
days although lane due-checkpoints is RETIRED in config/lane_registry.json by operator decision. A unit whose
lane is RETIRED/PAUSED is expected OFF (RETIRED_OK); a disabled unit with no row or an ACTIVE row stays a
finding. Hermetic: fixture registry + fixture unit states."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_expected_services as ces  # noqa: E402

REG = {"lanes": [
    {"lane_id": "due-checkpoints", "state": "RETIRED", "scheduler": {"kind": "systemd", "match": "tradeai-due-checkpoints.timer"}},
    {"lane_id": "paused-lane", "state": "PAUSED", "scheduler": {"kind": "systemd", "expression": "tradeai-paused.timer (weekly)"}},
    {"lane_id": "active-lane", "state": "ACTIVE", "scheduler": {"kind": "systemd", "match": "tradeai-active.timer"}},
    {"lane_id": "a-cron-lane", "state": "RETIRED", "scheduler": {"kind": "cron", "match": "scripts/x.py"}},
]}


def _row(name, status):
    return {"kind": "unit", "name": name, "status": status}


def test_lane_states_map_units_from_match_and_expression():
    m = ces.lane_states_for_units(REG)
    assert m["tradeai-due-checkpoints.timer"] == ("due-checkpoints", "RETIRED")
    assert m["tradeai-paused.timer"] == ("paused-lane", "PAUSED")
    assert m["tradeai-active.timer"] == ("active-lane", "ACTIVE")
    assert "scripts/x.py" not in m


def test_retired_or_paused_lane_makes_a_disabled_unit_expected_off():
    rows = ces.apply_lane_states(
        [_row("tradeai-due-checkpoints.timer", "DISABLED"), _row("tradeai-paused.timer", "MISSING"),
         _row("tradeai-active.timer", "DISABLED"), _row("tradeai-iris-taxonomy.timer", "DISABLED"),
         _row("tradeai-ok.timer", "OK")],
        ces.lane_states_for_units(REG))
    by = {r["name"]: r for r in rows}
    assert by["tradeai-due-checkpoints.timer"]["status"] == "RETIRED_OK"
    assert "RETIRED" in by["tradeai-due-checkpoints.timer"]["detail"]
    assert by["tradeai-paused.timer"]["status"] == "RETIRED_OK"
    assert by["tradeai-active.timer"]["status"] == "DISABLED"          # ACTIVE lane off = still a finding
    assert by["tradeai-iris-taxonomy.timer"]["status"] == "DISABLED"   # no lane row = still a finding
    assert "no lane row" in by["tradeai-iris-taxonomy.timer"]["detail"]
    assert by["tradeai-ok.timer"]["status"] == "OK" and "detail" not in by["tradeai-ok.timer"]


def test_retired_ok_is_not_counted_as_off_in_main():
    src = (ROOT / "scripts" / "check_expected_services.py").read_text()
    assert 'off = [r for r in results if r["status"] not in {"OK", "RETIRED_OK"}]' in src
    assert "apply_lane_states(results, lane_states_for_units(registry))" in src


def test_the_live_registry_retires_due_checkpoints():
    import json
    m = ces.lane_states_for_units(json.loads((ROOT / "config" / "lane_registry.json").read_text()))
    assert m.get("tradeai-due-checkpoints.timer", ("", ""))[1] == "RETIRED"
    # 2026-10-09 (PR #1597 review): iris-taxonomy now has a lane row (B1 reconciliation), but retiring it is
    # operator decision O-4, still open. The row records the disabled unit WITHOUT ruling: state ACTIVE,
    # status DISABLED_UNRULED, operator_decision_pending — so the disabled timer stays a finding, never
    # "expected off". Same for every unit the generator found disabled.
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    lane = m.get("tradeai-iris-taxonomy.timer")
    assert lane and lane[1] not in ces.OFF_BY_DECISION, lane
    rows = ces.apply_lane_states([_row("tradeai-iris-taxonomy.timer", "DISABLED")], m)
    assert rows[0]["status"] == "DISABLED", rows[0]
    unruled = [r for r in reg["lanes"] if r.get("status") == "DISABLED_UNRULED"]
    assert {r["lane_id"] for r in unruled} >= {
        "tradeai-iris-taxonomy", "db-retention-timer", "systemd-tmpfiles-clean", "tradeai-agent-runtime-atlas",
        "tradeai-agent-runtime-concierge", "tradeai-agent-runtime-hermes", "tradeai-agent-runtime-pulse"}
    for r in unruled:
        assert r["state"] not in ces.OFF_BY_DECISION and r["operator_decision_pending"] is True, r["lane_id"]
        assert (r.get("proposed_state") or {}).get("ruled", False) is False, r["lane_id"]

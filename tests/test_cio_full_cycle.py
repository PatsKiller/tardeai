"""cio_full_cycle.py — dry tests for the Phase 9 full-system integration dry-run.

Verifies the end-to-end cycle (wake → snapshot → specialists → synthesis →
capital plan → report v2 → office home → disposition) and the full evidence
spine from run-ID through to operator disposition, with store integrity.
No broker / order / provider calls.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.cio_full_cycle import run_full_cycle  # noqa: E402
from scripts.lib.cio_full_cycle import _AutoCompleteHandoffQueue  # noqa: E402

FIXED_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def _run(**overrides):
    kwargs = {"now": FIXED_NOW}
    kwargs.update(overrides)
    return run_full_cycle(**kwargs)


# ── End-to-end happy path ──────────────────────────────────────────────────────


def test_full_cycle_completes_end_to_end(tmp_path):
    res = _run(store_dir=tmp_path)
    assert res["ok"] is True
    assert res["pass1_status"] == "WAITING_FOR_SPECIALISTS"
    assert res["pass2_status"] == "COMPLETED"
    assert res["run_projection"]["status"] == "COMPLETED"

    # All three downstream compositions materialized.
    assert set(res["office_home"].keys()) >= {
        "cio_now", "capital_plan", "posture", "opportunities", "report", "evidence",
    }
    assert res["capital_plan"].get("cash_total_usd") is not None
    assert bool(res["report_v2"].get("html"))


def test_full_cycle_spine_is_fully_linked(tmp_path):
    res = _run(store_dir=tmp_path)
    spine = res["spine"]
    run = res["run_projection"]

    # wake → run
    assert run["trigger_ref"] == spine["wake_job_id"]

    # run → snapshot
    assert run["input_snapshot_id"] == spine["snapshot_id"]

    # run → specialists (no nulls, exactly 3 routed)
    assert spine["handoff_ids"] == run["specialist_requests"]
    assert len(spine["handoff_ids"]) == 3
    assert all(h for h in spine["handoff_ids"])

    # run → decision
    assert spine["decision_id"]
    assert spine["decision_position"] == "HOLD"

    # decision → action (via cio_decision_id and origin_run_id)
    action_ids = spine["action_ids"]
    assert len(action_ids) == 1
    from scripts.lib.cio_action_ledger import CIOActionLedger

    ledger = CIOActionLedger(event_store_path=tmp_path / "cio_action_ledger.jsonl")
    action = ledger.get_action(action_ids[0])
    assert action["origin_run_id"] == spine["run_id"]
    assert action["cio_decision_id"] == spine["decision_id"]

    # action → notification
    assert spine["notification_ids"]
    from scripts.lib.cio_notification_outbox import NotificationOutbox

    outbox = NotificationOutbox(event_store_path=tmp_path / "cio_notification_outbox.jsonl")
    notif = outbox.get_notification(spine["notification_ids"][0])
    assert notif["cio_action_id"] == action_ids[0]

    # action → disposition
    assert spine["disposition"]["cio_action_id"] == action_ids[0]

    # integrity passes
    assert res["integrity"]["passed"] is True
    assert res["integrity"]["passed_count"] == res["integrity"]["total_count"]


def test_full_cycle_deterministic_structure(tmp_path):
    a = _run(store_dir=tmp_path / "a")
    b = _run(store_dir=tmp_path / "b")

    # Random identities differ, but the deterministic structure is identical.
    assert a["spine"]["run_id"] != b["spine"]["run_id"]
    assert a["spine"]["decision_position"] == b["spine"]["decision_position"] == "HOLD"
    assert len(a["spine"]["action_ids"]) == len(b["spine"]["action_ids"])
    assert len(a["spine"]["notification_ids"]) == len(b["spine"]["notification_ids"])
    assert (
        a["capital_plan"]["cash_total_usd"] == b["capital_plan"]["cash_total_usd"]
    )
    assert a["office_home"]["version"] == b["office_home"]["version"]


def test_full_cycle_run_store_specialist_counter_is_clean(tmp_path):
    res = _run(store_dir=tmp_path)
    run = res["run_projection"]
    # No None entries leaked into specialist_requests from the resume transition.
    assert all(run["specialist_requests"])
    assert run["counters"]["specialist_calls"] == 3


# ── Fail-soft behavior ─────────────────────────────────────────────────────────


def test_full_cycle_empty_recommendations_falls_back_to_status(tmp_path):
    def empty_synth(run, snapshot, specialist_result, hermes_result):
        return {
            "decision_id": "d-empty",
            "final_position": "HOLD",
            "summary": "No actionable recommendations.",
            "recommendations": [],
        }

    res = _run(store_dir=tmp_path, synthesis_fn=empty_synth)
    assert res["ok"] is True
    assert res["pass2_status"] == "COMPLETED"
    # Worker writes a STATUS fallback action so the cycle still terminates.
    assert len(res["spine"]["action_ids"]) >= 1
    from scripts.lib.cio_action_ledger import CIOActionLedger

    ledger = CIOActionLedger(event_store_path=tmp_path / "cio_action_ledger.jsonl")
    status_actions = [
        a for a in ledger.list_actions() if a.get("current_status") == "OPEN"
    ]
    assert status_actions


def test_full_cycle_empty_holdings_fails_soft(tmp_path):
    res = _run(store_dir=tmp_path, holdings_doc={})
    assert res["ok"] is True
    # Capital plan degrades to a zero-cash plan, but does not raise.
    assert res["capital_plan"].get("cash_total_usd") == 0
    # Office home still has all six sections.
    assert set(res["office_home"].keys()) >= {
        "cio_now", "capital_plan", "posture", "opportunities", "report", "evidence",
    }


# ── Stand-in handoff queue ─────────────────────────────────────────────────────


def test_auto_complete_handoff_queue_returns_support_advisory():
    q = _AutoCompleteHandoffQueue()
    q.enqueue({"handoff_id": "handoff-maria-1", "to_agent": "maria"})
    projection = q.get_handoff("handoff-maria-1")
    assert projection["current_status"] == "COMPLETED"
    assert projection["specialist_advisory"]["specialist_id"] == "maria"
    assert projection["specialist_advisory"]["position"] == "SUPPORT"

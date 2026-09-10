"""Lane A — WakeRecord@v2 hermetic suite on disposable state roots.

Covers required campaign cases + four negative controls.
Never touches production DB or schedules.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_agent_wake import (  # noqa: E402
    FEATURE_FLAG,
    MemoryLoader,
    NullCommsHistory,
    WakeEngine,
    WakeRejected,
    default_decide,
    feature_enabled,
    recover_incomplete_wakes,
    run_scheduled_wake,
)
from scripts.lib.persistent_wake_interfaces import (  # noqa: E402
    mint_commitment_id,
    mint_receipt_id,
    mint_wake_id,
)
from scripts.lib.persistent_wake_schedule import (  # noqa: E402
    ScheduleContract,
    assert_schedule_states_complete,
    evaluate_health,
)
from scripts.lib.persistent_wake_store import JsonlStore  # noqa: E402

SG = "97172f54-916c-5960-aa73-f16321f1cf3e"
OTHER = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
ENV_ON = {FEATURE_FLAG: "1", "PROVENANCE_PRODUCER": "test", "TRADEAI_SOURCE_SHA": "f1c87242669b409d3a02bf28c363e032da84cb3a"}


@pytest.fixture()
def state(tmp_path: Path):
    root = tmp_path / "state"
    root.mkdir()
    return root


def _mem_file(tmp_path: Path, rows: list[dict], name: str = "mem.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _fact(fid: str, content: str, *, hours_ago: float = 1.0, subject: str = SG, relevant: bool = True):
    return {
        "fact_id": fid,
        "subject_guid": subject,
        "content": content,
        "as_of": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"),
        "relevant": relevant,
    }


def test_off_state_negative_control(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env={FEATURE_FLAG: "0", "PROVENANCE_PRODUCER": "test"},
    )
    assert r["skipped"] is True
    assert JsonlStore(state).count("wakes") == 0
    assert JsonlStore(state).count("commitments") == 0
    assert JsonlStore(state).count("receipts") == 0


def test_fresh_wake_with_relevant_memory(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha thesis")])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
    )
    assert r["ok"] and r["inserted"]
    wake = r["wake"]
    assert wake["lifecycle_state"] == "SETTLED"
    assert wake["memory_fact_ids"] == ["f1"]
    assert wake["schema_version"] == "WakeRecord@v2"
    assert len(r["commitments"]) == 1
    assert r["commitments"][0]["provenance"]["producer"] == "test"
    # Provenance shows memory influence
    assert "f1" in (r["commitments"][0]["provenance"].get("influence_source_ids") or [])
    assert any(x["effect_kind"] == "changed_commitment" for x in r["receipts"])


def test_wake_with_no_memory(state, tmp_path):
    mem = _mem_file(tmp_path, [])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
    )
    assert r["ok"]
    assert r["memory_empty"] is True
    assert r["wake"]["lifecycle_state"] == "LOADED"
    assert r["commitments"] == []
    assert "no_relevant_memory" in r["wake"]["provenance"]["policy_decisions"]


def test_stale_memory_degrades_and_does_not_refuse(state, tmp_path):
    """Superseded assertion, 2026-09-10.

    This test previously pinned `state == "STALE"` and `ok is False`. That
    behaviour had never once executed in production: `stale` is derived from
    the newest loaded fact, and every wake loaded zero facts, so `newest` was
    always None and `stale` always False. When memory became findable the
    branch fired for the first time and aborted a real wake.

    Refusing is the wrong response. Before memory was loadable these subjects
    proceeded with no facts; after, one old fact ended the decision entirely,
    so the desk did strictly less the more memory it could find. Measured then:
    65 of 71 subjects with loadable memory were past the 168h window.

    The intent is preserved — the wake never reasons from stale facts — but it
    proceeds without them instead of stopping. The literals are changed here
    because the policy is corrected, not to make a red test green.
    """
    mem = _mem_file(tmp_path, [_fact("f1", "old", hours_ago=24 * 30)])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
        # MemoryLoader default stale 168h; 30d is stale
    )
    assert r["ok"] is True
    assert r.get("state") != "STALE"
    assert r["wake"]["lifecycle_state"] != "STALE"
    assert r["wake"]["memory_fact_ids"] == [], "must not reason from stale facts"
    assert "stale_memory_degraded_to_empty" in r["wake"]["provenance"]["policy_decisions"]


def test_malformed_memory_refuses(state, tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("MALFORMED: broken store\n")
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=p, when=NOW, env=ENV_ON,
    )
    assert r["ok"] is False
    assert r["state"] == "MEMORY_MALFORMED"
    assert JsonlStore(state).count("commitments") == 0


def test_missing_fact_id_is_malformed(state, tmp_path):
    mem = _mem_file(tmp_path, [{"subject_guid": SG, "content": "x", "as_of": NOW.isoformat()}])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
    )
    assert r["state"] == "MEMORY_MALFORMED"


def test_prior_operator_reply_consumption(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    comms = NullCommsHistory(
        turns=[{"turn_id": "op-1", "subject_guid": SG, "text": "hold thesis"}],
    )
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, comms=comms, when=NOW, env=ENV_ON,
    )
    assert "op-1" in r["wake"]["prior_operator_turn_ids"]
    assert any(x["source_kind"] == "operator_turn" and x["source_id"] == "op-1" for x in r["receipts"])


def test_prior_communication_consumption(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    comms = NullCommsHistory(
        events=[{"event_id": "evt-9", "subject_guid": SG, "text": "delivered note"}],
    )
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, comms=comms, when=NOW, env=ENV_ON,
    )
    assert "evt-9" in r["wake"]["prior_comm_event_ids"]
    assert any(x["source_kind"] == "comm_event" and x["source_id"] == "evt-9" for x in r["receipts"])


def test_irrelevant_history_excluded(state, tmp_path):
    mem = _mem_file(tmp_path, [
        _fact("f1", "mine", subject=SG),
        _fact("f2", "theirs", subject=OTHER),
    ])
    comms = NullCommsHistory(
        events=[
            {"event_id": "evt-mine", "subject_guid": SG},
            {"event_id": "evt-other", "subject_guid": OTHER},
        ],
        turns=[
            {"turn_id": "op-mine", "subject_guid": SG},
            {"turn_id": "op-other", "subject_guid": OTHER},
        ],
    )
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, comms=comms, when=NOW, env=ENV_ON,
    )
    assert r["wake"]["memory_fact_ids"] == ["f1"]
    assert r["wake"]["prior_comm_event_ids"] == ["evt-mine"]
    assert r["wake"]["prior_operator_turn_ids"] == ["op-mine"]


def test_duplicate_schedule_fire_idempotent(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    a = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    b = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    assert a["inserted"] is True
    assert b.get("replay_suppressed") is True or b["inserted"] is False
    assert JsonlStore(state).count("wakes") == 1
    assert JsonlStore(state).count("commitments") == 1
    # receipts unique by receipt_id
    rids = [r["receipt_id"] for r in JsonlStore(state).iter("receipts")]
    assert len(rids) == len(set(rids))


def test_replay_negative_control_same_input_one_effect(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    for _ in range(3):
        run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    assert JsonlStore(state).count("wakes") == 1
    assert JsonlStore(state).count("commitments") == 1


def test_duplicate_equivalent_distinct_inputs_do_not_double_same_slot(state, tmp_path):
    """Two equivalent-but-distinct invocations of the SAME slot collide."""
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=mem, when=NOW, env=ENV_ON)
    # distinct wall-clock inside same slot
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=mem, when=NOW + timedelta(minutes=15), env=ENV_ON)
    assert JsonlStore(state).count("wakes") == 1


def test_crash_between_reservation_and_completion(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    with pytest.raises(RuntimeError, match="simulated_crash"):
        run_scheduled_wake(
            agent_id="cio", subject_guid=SG, state_root=state,
            memory_backend=mem, when=NOW, env=ENV_ON, crash_after="reserved",
        )
    store = JsonlStore(state)
    wake = next(store.iter("wakes"))
    assert wake["lifecycle_state"] == "CLAIMED"
    assert store.count("commitments") == 0
    # Resume same slot: non-terminal CLAIMED is continued, not duplicated.
    r2 = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON,
    )
    assert r2["ok"] is True
    assert store.count("wakes") == 1
    assert store.count("commitments") == 1
    assert store.get("wakes", "wake_id", wake["wake_id"])["lifecycle_state"] == "SETTLED"


def test_replay_after_completion(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    a = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    b = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    assert a["wake"]["wake_id"] == b["wake"]["wake_id"]
    assert b.get("replay_suppressed") is True
    assert JsonlStore(state).count("commitments") == 1


def test_restart_recovery_no_duplicate(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    # Complete once
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=mem, when=NOW, env=ENV_ON)
    store = JsonlStore(state)
    # Simulate stray CLAIMED sibling with different slot via manual insert then recover
    contract = ScheduleContract(agent_id="cio", wake_reason="scheduled_persistent_review")
    other_slot = contract.slot_for(NOW + timedelta(hours=2))
    wid = mint_wake_id("cio", "scheduled_persistent_review", other_slot, SG)
    store.append_unique("wakes", "wake_id", {
        "wake_id": wid, "lifecycle_state": "CLAIMED", "commitments_created": [],
        "idempotency_key": wid,
    })
    recover_incomplete_wakes(store)
    row = store.get("wakes", "wake_id", wid)
    assert row["lifecycle_state"] == "ABANDONED"
    # Original completed wake untouched
    assert store.count("commitments") == 1


def test_receipt_uniqueness_and_referential_integrity(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    r = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    store = JsonlStore(state)
    receipts = list(store.iter("receipts"))
    ids = [x["receipt_id"] for x in receipts]
    assert len(ids) == len(set(ids))
    for rec in receipts:
        assert rec["wake_id"] == r["wake"]["wake_id"]
        assert rec["source_id"]
        assert rec["source_kind"] in {"memory_fact", "comm_event", "operator_turn", "research_object"}
        assert rec["schema_version"] == "AgentConsumptionReceipt@v2"
        # deterministic mint
        assert rec["receipt_id"] == mint_receipt_id(
            rec["agent_id"], rec["source_kind"], rec["source_id"], rec["purpose"]
        )


def test_commitment_created_exactly_once(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    for _ in range(5):
        run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    assert JsonlStore(state).count("commitments") == 1
    c = next(JsonlStore(state).iter("commitments"))
    assert c["commitment_id"] == mint_commitment_id(
        c["wake_id"], c["subject_guid"], c["commitment_kind"], c["normalized_claim"]
    )


def test_changed_prior_memory_changes_subsequent_output(state, tmp_path):
    mem1 = _mem_file(tmp_path, [_fact("f1", "alpha")], name="m1.jsonl")
    r1 = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                            memory_backend=mem1, when=NOW, env=ENV_ON)
    fp1 = r1["wake"]["decision_summary"]["output_fingerprint"]
    c1 = r1["commitments"][0]["commitment_id"]

    # Next slot + changed memory
    mem2 = _mem_file(tmp_path, [_fact("f1", "BETA changed")], name="m2.jsonl")
    r2 = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                            memory_backend=mem2, when=NOW + timedelta(hours=1), env=ENV_ON)
    fp2 = r2["wake"]["decision_summary"]["output_fingerprint"]
    c2 = r2["commitments"][0]["commitment_id"]
    assert fp1 != fp2
    assert c1 != c2


def _crontab_snapshot() -> str:
    """The user's crontab, or "" where there is none.

    `crontab -l` exits 1 when the user has no crontab and the binary may be
    absent entirely, so check_output() raised on CI and this test failed on
    commits that passed locally. tests/test_dark_contract_guard.py records the
    same defect from the same cause: "shelling out makes the gate
    machine-dependent ... in CI, where no crontab exists."

    The assertion is unchanged and undiminished: the snapshot is taken the same
    way before and after, so "the contract did not install a cron entry" is still
    proven. On a machine with no crontab the comparison is "" == "", which is the
    correct answer there — defining a contract must not CREATE one either.
    """
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def test_production_schedule_remains_unchanged():
    """Defining the contract must not install cron/systemd."""
    before = _crontab_snapshot()
    assert_schedule_states_complete()
    contract = ScheduleContract(agent_id="cio", wake_reason="scheduled_persistent_review")
    _ = contract.slot_for(NOW)
    h = evaluate_health(contract, now=NOW, completed_slots=[], never_scheduled=True)
    assert h.state == "never_scheduled"
    after = _crontab_snapshot()
    assert before == after
    # No timer files created by this suite under /etc or user systemd
    assert not Path("/etc/systemd/system/persistent-agent-wake.timer").exists()


def test_fixture_not_organic_negative_control(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    r = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    assert r["wake"]["provenance"]["producer"] == "test"
    organic = [
        row for row in JsonlStore(state).iter("wakes")
        if row.get("provenance", {}).get("producer") not in {"test", None}
        and row.get("provenance", {}).get("trigger") == "organic_schedule"
    ]
    assert organic == []


def test_memory_must_load_before_action(state, tmp_path):
    """Ordering rail: a decide() that runs must see memory already in context."""
    seen = {}

    def decide(ctx):
        seen["facts"] = list(ctx.get("memory_facts") or [])
        return default_decide(ctx)

    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=mem, when=NOW, env=ENV_ON, decide=decide,
    )
    assert seen["facts"] and seen["facts"][0]["fact_id"] == "f1"


def test_schedule_health_states():
    c = ScheduleContract(agent_id="cio", wake_reason="r", cadence_minutes=60)
    slot = c.slot_for(NOW)
    assert evaluate_health(c, now=NOW, completed_slots=[], never_scheduled=True).state == "never_scheduled"
    assert evaluate_health(c, now=NOW, completed_slots=[], dependency_stale=True).state == "stale_dependency"
    assert evaluate_health(c, now=NOW, completed_slots=[], memory_relevant=False).state == "no_relevant_memory"
    assert evaluate_health(c, now=NOW, completed_slots=[], running_slots=[slot]).state == "running"
    assert evaluate_health(c, now=NOW, completed_slots=[], failed_slots=[slot]).state == "failed"
    assert evaluate_health(c, now=NOW, completed_slots=[slot]).state == "completed"
    assert evaluate_health(c, now=NOW, completed_slots=[], replay_suppressed_slots=[slot]).state == "replay_suppressed"
    assert evaluate_health(c, now=NOW, completed_slots=[]).state == "due"


def test_negative_control_removing_memory_loading_breaks_ordering(tmp_path, state):
    """If memory loading were skipped, decide would see empty facts despite store having data.

    This documents the failure mode the ordering test guards against.
    """
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    # Bypass loader by handing decide a forged empty context path via custom engine step
    engine = WakeEngine(
        store=JsonlStore(state),
        memory_loader=MemoryLoader(lambda _sg: []),  # broken: ignores real memory file
        comms=NullCommsHistory(),
        source_sha=ENV_ON["TRADEAI_SOURCE_SHA"],
    )
    # Real file has data, but broken loader returns empty => no commitment
    assert list(MemoryLoader(mem).load(SG, now=NOW).facts)
    r = engine.run(
        agent_id="cio", subject_guid=SG, wake_reason="scheduled_persistent_review",
        schedule_slot_utc=ScheduleContract("cio", "scheduled_persistent_review").slot_for(NOW),
        now=NOW, env=ENV_ON,
    )
    assert r["memory_empty"] is True
    assert r["commitments"] == []


def test_negative_control_removing_receipt_creation_is_detectable(state, tmp_path):
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    r = run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=mem, when=NOW, env=ENV_ON)
    assert r["receipts"], "suite expects receipts; absence would fail this control"


def test_negative_control_removing_idempotency_would_duplicate(state, tmp_path):
    """Prove collision depends on deterministic wake_id — different slot => new rows."""
    mem = _mem_file(tmp_path, [_fact("f1", "alpha")])
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=mem, when=NOW, env=ENV_ON)
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=mem, when=NOW + timedelta(hours=1), env=ENV_ON)
    assert JsonlStore(state).count("wakes") == 2
    # Same slot still 2 (not 3)
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=mem, when=NOW, env=ENV_ON)
    assert JsonlStore(state).count("wakes") == 2


def test_feature_flag_default_off():
    assert feature_enabled({}) is False
    assert feature_enabled({FEATURE_FLAG: "1"}) is True

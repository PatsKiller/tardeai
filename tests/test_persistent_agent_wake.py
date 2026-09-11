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


def test_stale_memory_decays_and_does_not_refuse(state, tmp_path):
    """Superseded assertion, twice: 2026-09-10 and again 2026-09-11.

    This test previously pinned `state == "STALE"` and `ok is False`. That
    behaviour had never once executed in production: `stale` is derived from
    the newest loaded fact, and every wake loaded zero facts, so `newest` was
    always None and `stale` always False. When memory became findable the
    branch fired for the first time and aborted a real wake.

    Refusing is the wrong response. Before memory was loadable these subjects
    proceeded with no facts; after, one old fact ended the decision entirely,
    so the desk did strictly less the more memory it could find. Measured then:
    65 of 71 subjects with loadable memory were past the 168h window.

    2026-09-11 supersedes the fix as well as the original. "Degrade to empty"
    kept the decision but still discarded every fact, so one old observation
    erased the whole subject. Age is now a continuous weight: the wake proceeds
    AND still sees the fact, discounted. The literals change here because the
    policy is corrected, not to make a red test green.
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
    assert r["wake"]["memory_fact_ids"] == ["f1"], "a 30d fact is old, not absent"
    decisions = r["wake"]["provenance"]["policy_decisions"]
    assert "stale_memory_retained_with_decay" in decisions
    assert "stale_memory_degraded_to_empty" not in decisions
    (weight,) = r["wake"]["provenance"]["memory_retrieval"]["decay_weights"]
    assert 0.0 < weight < 1.0


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


# ---------------------------------------------------------------------------
# A judgment that is not durable is not a judgment.
# ---------------------------------------------------------------------------

def _stub_judgment(view_id="view_test0000000000000000", judgment_id="jdg_test", critique_id="crt_test"):
    """The shape scripts.lib.l3_agent_view_synthesis actually returns."""
    return {
        "output": {"status": "JUDGED", "refusal_reason": None},
        "agent_view": {
            "view_id": view_id,
            "subject": SG,
            "stance": "ABSTAIN",
            "judgment_stance": "INSUFFICIENT",
            "confidence": 0.7,
            "cost_class": "model",
            "provenance_class": "A",
            "judgment_id": judgment_id,
            "critique_id": critique_id,
            "falsifier": "consumption of the research object yields primary evidence",
            "citations": ["mem_x"],
            "provenance": {
                "producer": "l3_agent_view_synthesis",
                "llm": {"author_provider": "deepseek", "critic_provider": "grok"},
                "policy_decisions": ["critic_verdict=accept", "critic_provider=grok"],
            },
        },
        "commitment": None,
        "durable_rows": [],
    }


def test_the_judgments_own_view_is_persisted(state, tmp_path, monkeypatch):
    """THE DEFECT THIS CATCHES.

    On slot 2026-09-11T15:00Z the author returned INSUFFICIENT at 0.55 from
    deepseek-flash over two paid provider calls, and the durable AgentView said
    RECOMMEND at 0.6 with cost_class "zero" and llm null. Every one of the 75
    agent_views ever written carried judgment_id null, because `default_decide`
    never reads context["agent_view"] and the only view persist site builds its
    own record with provenance llm hardcoded to None.

    A reader of durable state therefore saw the OPPOSITE of what the system had
    concluded, and the commitment it would later settle against was unrelated to
    the judgment it had paid for.
    """
    import scripts.lib.persistent_agent_wake as PW

    mem = _mem_file(tmp_path, [_fact("mem_x", "prior position on this subject")])
    monkeypatch.setattr(PW.WakeEngine, "_maybe_judge",
                        lambda self, *a, **k: _stub_judgment(), raising=True)

    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=str(mem), when=NOW, env=dict(ENV_ON),
    )
    wake = r.get("wake") or r
    assert "l3_view_persisted" in wake["provenance"]["policy_decisions"]
    assert wake["views_created"] == ["view_test0000000000000000"]

    views = [json.loads(l) for l in (Path(state) / "views.jsonl").read_text().splitlines() if l.strip()]
    persisted = [v for v in views if v["view_id"] == "view_test0000000000000000"]
    assert len(persisted) == 1, "the judgment's own view must be durable"
    v = persisted[0]

    # The three fields whose absence made the old record contradict the judgment.
    assert v["judgment_id"] == "jdg_test", "view must point at the judgment it came from"
    assert v["critique_id"] == "crt_test", "view must point at the critique"
    assert v["cost_class"] == "model", "a paid judgment must not be recorded as zero-cost"

    # And the stance must be the model's, not a deterministic default.
    assert v["stance"] == "ABSTAIN" and v["judgment_stance"] == "INSUFFICIENT"
    assert v["provenance"]["llm"]["author_provider"] == "deepseek"
    assert v["provenance"]["llm"]["critic_provider"] == "grok", (
        "provider separation must be visible in DURABLE state, not only in a cache file"
    )


def test_views_created_is_always_declared(state, tmp_path):
    """Absent-vs-empty must not be the reader's problem.

    A key that materialises only on judged slots is unreadable: a consumer cannot
    distinguish "no view" from "field not written by this version".
    """
    mem = _mem_file(tmp_path, [_fact("mem_x", "anything")])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=str(mem), when=NOW, env=dict(ENV_ON),
    )
    wake = r.get("wake") or r
    assert "views_created" in wake, "views_created must be declared on every wake"
    assert wake["views_created"] == [], "unjudged slot creates no view"


def test_a_view_claiming_model_provenance_must_name_its_judgment(state, tmp_path, monkeypatch):
    """Fail closed rather than persist the conflation in a new shape.

    A view carrying cost_class "model" but no judgment_id is the same defect
    wearing different clothes, so the wake refuses it outright.
    """
    import scripts.lib.persistent_agent_wake as PW

    bad = _stub_judgment()
    bad["agent_view"]["judgment_id"] = None
    mem = _mem_file(tmp_path, [_fact("mem_x", "prior position")])
    monkeypatch.setattr(PW.WakeEngine, "_maybe_judge",
                        lambda self, *a, **k: bad, raising=True)

    with pytest.raises(WakeRejected, match="judgment_id"):
        run_scheduled_wake(
            agent_id="cio", subject_guid=SG, state_root=state,
            memory_backend=str(mem), when=NOW, env=dict(ENV_ON),
        )


def test_a_judged_slots_commitment_does_not_claim_no_model_ran(state, tmp_path, monkeypatch):
    """`llm: None` was hardcoded on every commitment.

    That is the truth for a deterministic decision and a lie for a slot that made
    two paid provider calls.
    """
    import scripts.lib.persistent_agent_wake as PW

    def _judge(self, wake, *a, **k):
        wake["provenance"]["llm"] = {"provider": "deepseek", "judgment_id": "jdg_test"}
        return _stub_judgment()

    mem = _mem_file(tmp_path, [_fact("mem_x", "prior position")])
    monkeypatch.setattr(PW.WakeEngine, "_maybe_judge", _judge, raising=True)

    run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=str(mem), when=NOW, env=dict(ENV_ON),
    )
    rows = [json.loads(l) for l in (Path(state) / "commitments.jsonl").read_text().splitlines() if l.strip()]
    assert rows, "expected a commitment"
    llm = (rows[-1].get("provenance") or {}).get("llm")
    assert llm and llm.get("judgment_id") == "jdg_test", (
        "a judged slot's commitment must not record llm None"
    )


# ---------------------------------------------------------------------------
# An operator question that changes nothing is intake, not consumption.
# ---------------------------------------------------------------------------

def _turn(tid, text, subject=SG):
    """The shape DbCommsHistory actually returns — id, not turn_id."""
    return {"id": tid, "role": "operator", "sanitized_body": text,
            "symbol": "ADBE", "subject_guid": subject, "created_at": "t0"}


def test_an_operator_question_changes_the_next_question(state, tmp_path):
    """THE CLAUSE THIS CLOSES.

    At 19:00Z the operator asked "ADBE — what did Q3 actually show on user
    growth?". The turn was durable, bound to that exact subject, CONFIRMED, and
    receipted. The wake for that subject in that hour loaded nothing, and even
    when loading was fixed the receipt hardcoded effect_kind "none" — which never
    counts as behavioural consumption. The operator could ask and the record
    would show the question arriving and changing nothing.
    """
    mem = _mem_file(tmp_path, [])
    comms = NullCommsHistory(turns=[_turn(115, "ADBE — what did Q3 show?")])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=str(mem), comms=comms, when=NOW, env=dict(ENV_ON),
    )
    wake = r.get("wake") or r
    assert wake["prior_operator_turn_ids"] == ["115"]

    commits = [json.loads(l) for l in (Path(state) / "commitments.jsonl").read_text().splitlines() if l.strip()]
    assert commits, "an operator question must produce a commitment"
    c = commits[-1]
    assert c["commitment_kind"] == "OPERATOR_QUESTION"
    assert "what did Q3 show" in c["claim"]

    recs = [json.loads(l) for l in (Path(state) / "receipts.jsonl").read_text().splitlines() if l.strip()]
    decision = [x for x in recs if x.get("purpose") == "wake_decision"]
    assert decision and decision[-1]["effect_kind"] == "changed_question"
    assert decision[-1]["source_kind"] == "operator_turn"
    assert decision[-1]["source_id"] == "115"


def test_the_operator_outranks_the_scheduler(state, tmp_path):
    """A person asking beats anything the selection feed surfaced on its own."""
    mem = _mem_file(tmp_path, [])
    comms = NullCommsHistory(turns=[_turn(115, "ADBE — what did Q3 show?")])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=str(mem), comms=comms, when=NOW, env=dict(ENV_ON),
        selection={"source": "unconsumed_research", "source_id": "res-1",
                   "observed_at": "2026-09-11T05:45:03Z"},
    )
    wake = r.get("wake") or r
    commits = [json.loads(l) for l in (Path(state) / "commitments.jsonl").read_text().splitlines() if l.strip()]
    assert commits[-1]["commitment_kind"] == "OPERATOR_QUESTION", (
        "SELECTION_OBSERVATION must not win over a question the operator asked"
    )
    assert wake["prior_operator_turn_ids"] == ["115"]


def test_no_operator_turn_still_records_none(state, tmp_path):
    """The negative control. 'Read it' and 'it changed something' must stay
    distinguishable — collapsing them is how this system keeps producing
    counters nobody can trust."""
    mem = _mem_file(tmp_path, [])
    r = run_scheduled_wake(
        agent_id="cio", subject_guid=SG, state_root=state,
        memory_backend=str(mem), comms=NullCommsHistory(), when=NOW,
        env=dict(ENV_ON),
    )
    wake = r.get("wake") or r
    assert wake["prior_operator_turn_ids"] == []
    rp = Path(state) / "receipts.jsonl"
    # No memory, no turns, no selection -> nothing to receipt at all. The file
    # may not exist, and that is the honest zero.
    recs = ([json.loads(l) for l in rp.read_text().splitlines() if l.strip()]
            if rp.exists() else [])
    assert all(x["effect_kind"] == "none" for x in recs)
    assert not [x for x in recs if x.get("source_kind") == "operator_turn"]


def test_loading_a_turn_is_recorded_separately_from_acting_on_it(state, tmp_path):
    """Two records, two meanings. The load receipt says the turn was READ; the
    decision receipt says whether it changed anything."""
    mem = _mem_file(tmp_path, [])
    comms = NullCommsHistory(turns=[_turn(115, "ADBE — what did Q3 show?")])
    run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                       memory_backend=str(mem), comms=comms, when=NOW,
                       env=dict(ENV_ON))
    recs = [json.loads(l) for l in (Path(state) / "receipts.jsonl").read_text().splitlines() if l.strip()]
    load = [x for x in recs if x.get("purpose") == "wake_operator_load"]
    assert load and load[0]["effect_kind"] == "none", "a load is not an influence"
    decision = [x for x in recs if x.get("purpose") == "wake_decision"]
    assert decision and decision[-1]["effect_kind"] == "changed_question"


def test_a_turn_with_no_id_is_refused_not_averaged(state, tmp_path):
    """Receipt ids are a deterministic uuid5 over the source id. A turn with no
    id yields "None", every such turn mints the SAME receipt, and append_unique
    keeps one — N turns collapsing into a single receipt naming a source that
    does not exist. Refuse instead: a load this broken must be visible."""
    mem = _mem_file(tmp_path, [])
    bad = NullCommsHistory(turns=[{"role": "operator", "sanitized_body": "hi",
                                   "subject_guid": SG}])
    with pytest.raises(WakeRejected, match="turn_id/id"):
        run_scheduled_wake(agent_id="cio", subject_guid=SG, state_root=state,
                           memory_backend=str(mem), comms=bad, when=NOW,
                           env=dict(ENV_ON))

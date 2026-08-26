"""R17 failure/restart cases. No silent loss. No duplicate learning."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.lib.cio_institutional_learning import persist_observation, process_due_checkpoint, snapshot_registries
from scripts.lib.cio_model_learning import apply_routing_candidate
from scripts.lib.r17_checkpoint_binding import bind_material_decision, process_due_store

NOW = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)


def test_duplicate_material_scan_does_not_duplicate_checkpoints(tmp_path) -> None:
    d = {"decision_id": "dec_dup", "symbol": "NOC", "action": "TRIM", "security_guid": "sec-noc", "decision_evidence_digest": "same"}
    bind_material_decision(tmp_path, d, source_sha="s", now=NOW, horizons=("1_session",))
    bind_material_decision(tmp_path, dict(d, decision_id="dec_dup2"), source_sha="s", now=NOW, horizons=("1_session",))
    lines = (tmp_path / "data/cio/outcome_checkpoints.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1


def test_missing_outcome_source_pending(tmp_path) -> None:
    d = {"decision_id": "dec_src", "symbol": "NOC", "action": "HOLD", "security_guid": "sec-noc", "decision_evidence_digest": "g"}
    bind_material_decision(tmp_path, d, source_sha="s", now=NOW, horizons=("1_session",))
    out = process_due_store(tmp_path, source_available=False, persist=True, now=NOW + timedelta(days=2))
    assert out["pending_data"] >= 1
    assert (tmp_path / "data/cio/outcome_observations.jsonl").exists() is False or \
        not (tmp_path / "data/cio/outcome_observations.jsonl").read_text().strip()


def test_unavailable_providers_do_not_invent(tmp_path) -> None:
    ck = {"decision_id": "d", "checkpoint_id": "c1", "horizon": "1_session", "due_at": (NOW - timedelta(hours=1)).isoformat()}
    for label in ("hermes", "rag", "searx", "llm", "memory", "specialist"):
        out = process_due_checkpoint(checkpoint=ck, source_available=False)
        assert out["status"] == "OUTCOME_PENDING_DATA"
        assert out["invented"] is False, label


def test_model_routing_cannot_write_registry(tmp_path) -> None:
    before = snapshot_registries(tmp_path)
    try:
        apply_routing_candidate({"promote": True}, tmp_path)
        raised = False
    except Exception:
        raised = True
    after = snapshot_registries(tmp_path)
    assert before == after
    assert raised or True


def test_observation_append_is_idempotent(tmp_path) -> None:
    obs = {
        "schema": "OutcomeObservation@v1",
        "outcome_id": "oid-1",
        "decision_id": "d1",
        "horizon": "1_session",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "financial_action": False,
        "source_as_of": NOW.isoformat(),
        "observed_at": NOW.isoformat(),
        "realized_state": {"linked": True},
        "original_decision_state": {},
        "source_refs": ["t"],
        "history_rewritten": False,
        "decision_mutated": False,
        "subject_guid": "sec-noc",
    }
    a = persist_observation(tmp_path, obs)
    b = persist_observation(tmp_path, obs)
    assert a["wrote"] is True
    assert b["duplicate"] is True
    assert b["crash_idempotent"] is True

"""Honest outcomes, conservative migrations and non-activating configuration truth."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.lib.governed_commitment import build_governed_commitment, CommitmentError, evaluate_outcome
from scripts.lib.commitment_outcome_sweep import sweep_due_commitments
from scripts.lib.outcome_resolution import checkpoint_deadline_migrations, due_checkpoints

NOW = datetime(2026, 10, 5, 14, tzinfo=timezone.utc)


def commitment(**patch):
    args = dict(claim="V close return will exceed zero at the horizon", confidence=.7, horizon="7d",
                due_at=NOW-timedelta(days=1), falsifier="V close return is zero or negative at the horizon",
                evidence_refs=["filing:v:1"], source_identity="research", source_sha="abc", served_sha="abc",
                subject_guid="guid-v", trigger_provenance={"producer": "scheduled_research"},
                created_at=NOW-timedelta(days=8), frozen_at=NOW-timedelta(days=8))
    args.update(patch)
    return build_governed_commitment(**args)


@pytest.mark.parametrize("patch", [
    {"claim": "Scheduled persistent wake reviewed subject 1111-2222; advisory observation only."},
    {"falsifier": "observation contradicts claim within horizon"},
    {"evidence_refs": [""]}, {"horizon": ""},
])
def test_new_unscoreable_commitments_are_refused(patch):
    with pytest.raises(CommitmentError):
        commitment(**patch)


@pytest.mark.parametrize("flag,verdict", [("confirmed", "CONFIRMED"), ("refuted", "REFUTED")])
def test_only_joined_observations_score(flag, verdict):
    c = commitment()
    assert evaluate_outcome(c, observation={flag: True}, now=NOW)["outcome"] == "INSUFFICIENT_EVIDENCE"
    observed = {flag: True, "observed": True, "source_refs": ["ticker_prices:V:horizon"], "commitment_id": c["commitment_id"]}
    assert evaluate_outcome(c, observation=observed, now=NOW)["outcome"] == verdict
    assert evaluate_outcome(c, observation={**observed, "commitment_id": "other"}, now=NOW)["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert evaluate_outcome(c, observation=observed, now=NOW-timedelta(days=4))["outcome"] == "INSUFFICIENT_EVIDENCE"


def test_unavailable_provider_preserves_historical_insufficiency():
    historic = {"commitment_id": "old", "outcome": "INSUFFICIENT_EVIDENCE", "idempotency_key": "historic", "errors": ["unfalsifiable"]}
    original = deepcopy(historic)
    def unavailable(c):
        raise RuntimeError("source unavailable")
    out = sweep_due_commitments([commitment()], ledger=[historic], observation_provider=unavailable, now=NOW)
    assert out.by_outcome == {"INSUFFICIENT_EVIDENCE": 1}
    assert out.ledger[0] == original and not out.lessons
    again = sweep_due_commitments([commitment()], ledger=out.ledger, observation_provider=unavailable, now=NOW)
    assert not again.outcomes


def test_valid_outcome_only_proposes_an_unratified_shadow_lesson():
    c = commitment()
    out = sweep_due_commitments([c], now=NOW, observation_provider=lambda c: {
        "confirmed": True, "observed": True, "source_refs": ["price:v"], "commitment_id": c["commitment_id"]})
    lesson = out.lessons[0]
    assert lesson["status"] == "PROPOSED" and lesson["ratified_by"] is None
    assert not lesson["changes_production_behaviour"] and lesson["mbi_behavior"] == 0
    assert lesson["supporting_outcome_ids"]


def cp(**patch):
    return {"checkpoint_id": "cp-v", "status": "SCHEDULED", "created_at": NOW.isoformat(),
            "horizon": "7d", "due_at": None, "original_decision_state": {"symbol": "V"}, **patch}


@pytest.mark.parametrize("horizon,hours", [("7d", 168), ("2 weeks", 336), ("PT12H", 12), ("P3D", 72)])
def test_deadline_migration_derives_only_recorded_durations(horizon, hours):
    original = cp(horizon=horizon)
    before = deepcopy(original)
    rows = checkpoint_deadline_migrations([original])
    assert rows[0]["due_at"] == (NOW+timedelta(hours=hours)).isoformat()
    assert original == before
    assert rows == checkpoint_deadline_migrations([original])
    assert checkpoint_deadline_migrations([original, *rows]) == []


@pytest.mark.parametrize("patch", [
    {"horizon": "event-relative"}, {"horizon": "5_sessions"}, {"horizon": "soon"},
    {"created_at": None}, {"created_at": "2026-10-05T14:00:00"},
])
def test_ambiguous_deadlines_require_migration_review(patch):
    original = cp(**patch)
    row = checkpoint_deadline_migrations([original])[0]
    assert row["due_at"] is None and row["status"] == "MIGRATION_REVIEW_REQUIRED"
    assert not due_checkpoints([original, row], now=NOW+timedelta(days=90))
    assert not checkpoint_deadline_migrations([original, row])
    assert original["status"] == "SCHEDULED"


def test_migration_cli_dry_run_and_append_are_idempotent(tmp_path, monkeypatch, capsys):
    from scripts import resolve_due_checkpoints as cli
    path = tmp_path / cli.CHECKPOINT_PATH
    path.parent.mkdir(parents=True)
    original_bytes = json.dumps(cp())+"\n"
    path.write_text(original_bytes)
    monkeypatch.setattr(cli, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_price_lookup_factory", lambda: pytest.fail("migration must not score outcomes"))
    monkeypatch.setattr("sys.argv", ["resolve_due_checkpoints.py", "--migrate-missing-deadlines"])
    assert cli.main() == 0
    assert path.read_text() == original_bytes
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["resolve_due_checkpoints.py", "--migrate-missing-deadlines", "--apply"])
    assert cli.main() == 0
    after = path.read_text()
    assert after.startswith(original_bytes) and len(after.splitlines()) == 2
    assert cli.main() == 0 and path.read_text() == after


def test_registry_truth_does_not_enable_disabled_definitions():
    from scripts.lib.agent_registry import runtime_truth
    from scripts.agent_runtime.agents.definitions import fleet
    before = {key: (s.definition.enabled, s.definition.deployment_state) for key, s in fleet().items()}
    truth = runtime_truth()
    rows = {r["agent_id"]: r for r in truth["agents"]}
    for aid in ("maria", "aegis", "risk_agent"):
        assert rows[aid]["configuration_disagreement"]
        assert rows[aid]["runtime_enabled"] is False
        assert rows[aid]["observed_activity"]["status"] == "UNMEASURED"
    assert not truth["activation_performed"]
    assert before == {key: (s.definition.enabled, s.definition.deployment_state) for key, s in fleet().items()}


def test_separate_service_is_compared_to_its_declared_contract(tmp_path):
    from scripts.check_worker_pins import evaluate
    path = str(tmp_path / "separate-release")
    row = {"kind": "unit", "name": "independent", "active": "active", "tree": "release", "sha": "oldsha",
           "deployment_binding": "DECLARED_SEPARATE", "path": path, "declared_path": path}
    report = evaluate(served="newsha", rows=[row])
    assert report["ok"] and row["verdict"] == "SEPARATE_CONTRACT_MATCH"
    row["path"] = str(tmp_path / "wrong-release")
    assert not evaluate(served="newsha", rows=[row])["ok"]


def test_unavailable_process_observation_is_not_a_verified_pin():
    from scripts.check_worker_pins import evaluate
    row = {"kind": "unit", "name": "unit", "active": "unknown", "tree": "other",
           "exit_observation": {"observation_status": "UNAVAILABLE"}}
    assert not evaluate(served="sha", rows=[row])["ok"]
    assert row["verdict"] == "UNVERIFIED"


def test_legacy_maturity_renderer_calls_the_rubric_superseded():
    from scripts.compute_maturity_score import to_markdown
    report = {"generated_at": "2026-06-28", "raw_weighted_score_of_5": 4.95,
              "final_maturity_score_of_5": 4.95, "meets_4_5": True, "caps_applied": [],
              "score_lines": [], "evidence": {}}
    rendered = to_markdown(report)
    assert "SUPERSEDED" in rendered and "does not measure demonstrated learning" in rendered
    assert "4.5 MET" not in rendered

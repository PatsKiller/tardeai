"""Pure cross-source acceptance with synthetic exact-head PR/claim/release facts."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/lib/work_pipeline_sources.py"
SPEC = importlib.util.spec_from_file_location("work_pipeline_sources_tested", PATH)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
NOW = datetime(2026, 11, 3, 3, tzinfo=timezone.utc)
HEAD, OTHER, SERVED = "a" * 40, "b" * 40, "c" * 40


def pr(**updates):
    return {"number": 2501, "branch": "wt/test", "head_sha": HEAD,
            "created_at": "2026-11-02T18:00:00Z", "merged_at": "2026-11-02T22:00:00Z",
            "released": {"at": "2026-11-02T23:00:00Z", "sha": OTHER, "basis": "release_pins/apply-first.json"},
            "served_contains": True, **updates}


def claim(**updates):
    return {"claim_id": "claim-one", "session": "worker", "vendor": "codex", "status": "active",
            "branch": "wt/test", "started_at": "2026-11-02T17:00:00Z",
            "heartbeat_at": "2026-11-03T01:00:00Z", "task": "Synthetic update",
            "stages": {"building": "2026-11-02T17:30:00Z"},
            "worklog": {"next_step": "Verify the served change", "blockers": 0,
                        "last_entry_at": "2026-11-03T00:00:00Z"}, **updates}


def approval(head=HEAD, **updates):
    return {"schema": "PrMergeDigestApproval@v1", "approval_id": "approval-one",
            "approved_at": "2026-11-02T21:00:00Z", "items": [{"pr": 2501, "head_sha": head}], **updates}


def event(kind="review_receipt_recorded", **updates):
    return {"kind": kind, "pr_number": 2501, "head_sha": HEAD, "verdict": "MERGE",
            "reviewer_session": "independent-worker", "evidence_class": "reported_review_not_approval",
            "ts": "2026-11-02T20:00:00Z", **updates}


def build(prs=None, claims=None, events=None, approvals=None, plans=None, **updates):
    return M.build([pr()] if prs is None else prs, [claim()] if claims is None else claims,
                   [event()] if events is None else events, [approval()] if approvals is None else approvals,
                   [] if plans is None else plans, NOW,
                   serving=updates.pop("serving", {"sha": SERVED, "since": "2026-11-03T00:00:00Z"}),
                   health=updates.pop("health", {"sha": SERVED, "ok": True, "at": "2026-11-03T00:05:00Z"}),
                   **updates)


def write_sources(tmp_path, events=None, approvals=None):
    for rel, rows in [(M.LEDGER_REL, [event()] if events is None else events),
                      (M.APPROVALS_REL, [approval()] if approvals is None else approvals)]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    (tmp_path / M.PLANS_REL).mkdir(parents=True, exist_ok=True)
    registry = tmp_path / M.REGISTRY_REL
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(registry_value()))


def registry_value(lead="test-lead", role="lead", updated_at="2026-11-03T00:30:00Z"):
    return {"lead": lead, "updated_at": updated_at,
            "coordinators": [{"id": lead, "role": role, "territories": ["ui", "release"]}]}


def test_full_timeline_uses_first_apply_and_distinct_verification_clock():
    data = build()
    row = data["by_pr"][2501]
    kinds = [entry["kind"] for entry in row["timeline"]]
    assert kinds == ["claimed", "building", "pr_open", "review_receipt_recorded", "operator_approval",
                     "merged", "released", "verified_live"]
    assert row["released"]["as_of"] == "2026-11-02T23:00:00Z"
    assert row["released"]["value"]["basis"] == "release_pins/apply-first.json"
    assert row["live"]["value"] is True
    assert row["live"]["as_of"] == "2026-11-03T00:05:00Z"
    assert row["owner"]["value"]["session"] == "worker"
    assert row["next_action"]["as_of"] == "2026-11-03T00:00:00Z"
    assert row["review"]["state"] == "MERGE"
    assert data["owner_coverage"] == {"prs_with_claim": 1, "owner_filled": 1, "pct": 100.0}
    assert row["coordinator"]["gap"] == "registry_not_supplied"
    assert row["plan_link"]["gap"] == "plan_link_not_recorded"


def test_head_changes_invalidate_approval_and_review_but_preserve_history():
    row = build(prs=[pr(head_sha=OTHER)])["by_pr"][2501]
    assert row["approval"]["value"] is False
    assert row["approval"]["as_of"] is None
    assert row["review"]["state"] == "UNKNOWN"
    assert row["review"]["gap"] == "stale_review_for_other_head"
    assert row["approvals"][0]["current_head"] is False
    assert any(e["kind"] == "operator_approval" for e in row["timeline"])


@pytest.mark.parametrize("health,prs", [
    ({"sha": OTHER, "ok": True, "at": "2026-11-03T00:05:00Z"}, [pr()]),
    ({"sha": SERVED, "ok": False, "at": "2026-11-03T00:05:00Z"}, [pr()]),
    ({"sha": SERVED, "ok": True, "at": None}, [pr()]),
    ({"sha": SERVED, "ok": True, "at": "2026-11-02T22:59:00Z"}, [pr()]),
    ({"sha": SERVED, "ok": True, "at": "2026-11-03T00:05:00Z"}, [pr(served_contains=None)]),
    ({"sha": SERVED, "ok": True, "at": "2026-11-03T00:05:00Z"}, [pr(released=None)]),
])
def test_unbound_or_unverified_release_never_becomes_live(health, prs):
    row = build(prs=prs, health=health)["by_pr"][2501]
    assert row["live"]["value"] is False
    assert row["live"]["gap"]
    assert not any(e["kind"] == "verified_live" for e in row["timeline"])


def test_stale_claim_history_preserved_but_active_count_excludes_it():
    old = claim(heartbeat_at="2026-11-01T01:00:00Z")
    result = build(claims=[old])
    assert result["active_claim_ids"] == []
    assert result["by_pr"][2501]["owner"]["value"]["session"] == "worker"
    assert len(result["claims"]) == 1
    assert build(claims=[old], stale_claim_hours=100)["active_claim_ids"] == ["claim-one"]


def test_future_heartbeat_and_ended_claim_are_not_in_flight():
    assert not build(claims=[claim(heartbeat_at="2026-11-04T01:00:00Z")])["active_claim_ids"]
    assert not build(claims=[claim(status="done")])["active_claim_ids"]


@pytest.mark.parametrize("effective", [{"_state": "done"}, {"state": "done"}, {"stage": "released"},
                                       {"stage": "merged"}, {"ended_at": "2026-11-03T01:00:00Z"}])
def test_effective_terminal_state_overrides_raw_active_status(effective):
    result = build(claims=[claim(status="active", **effective)])
    assert result["active_claim_ids"] == []
    assert result["by_pr"][2501]["active_claim_ids"] == []
    assert result["by_pr"][2501]["owner"]["value"]["session"] == "worker"
    assert len(result["claims"]) == 1


def test_nested_claim_metadata_is_allowlisted_and_clock_normalized():
    original = claim(worklog={"exists": True, "next_step": "Verify served output",
                              "last_entry_at": "2026-11-02T19:00:00-05:00",
                              "plan_done": 1, "plan_total": 2, "blockers": 0,
                              "path": "PRIVATE-PATH", "extra": {"secret": "PRIVATE-WORKLOG"}},
                     stages={"building": "2026-11-02T12:30:00-05:00",
                             "released": "2026-11-02T23:00:00",
                             "extra": "PRIVATE-STAGE", "claimed": {"secret": "PRIVATE-NESTED"}},
                     extra="PRIVATE-TOP")
    result = build(claims=[original])
    assert "PRIVATE" not in json.dumps(result)
    public = result["claims"][0]
    assert public["worklog"] == {"exists": True, "next_step": "Verify served output",
                                 "last_entry_at": "2026-11-03T00:00:00Z",
                                 "plan_done": 1, "plan_total": 2, "blockers": 0}
    assert public["stages"] == {"building": "2026-11-02T17:30:00Z"}
    assert original["worklog"]["extra"]["secret"] == "PRIVATE-WORKLOG"  # no mutation


@pytest.mark.parametrize("release_at,verified_at", [
    ("2026-11-02T23:00:00Z", "2026-11-04T00:00:00Z"),
    ("2026-11-04T00:00:00Z", "2026-11-04T01:00:00Z"),
])
def test_future_release_or_health_never_proves_live(release_at, verified_at):
    release = {"at": release_at, "sha": OTHER, "basis": "release_pins/synthetic.json"}
    result = build(prs=[pr(released=release)], health={"sha": SERVED, "ok": True, "at": verified_at})
    row = result["by_pr"][2501]
    assert row["live"]["value"] is False
    assert row["live"]["gap"]
    assert not any(e["kind"] == "verified_live" for e in row["timeline"])


@pytest.mark.parametrize("release_at,verified_at,expected", [
    ("2026-11-03T00:00:00.900Z", "2026-11-03T00:00:00.100Z", False),
    ("2026-11-03T00:00:00Z", "2026-11-03T00:00:00.100Z", True),
    ("2026-11-03T00:00:00.100Z", "2026-11-03T00:00:00.900Z", True),
])
def test_subsecond_release_verification_order_is_preserved(release_at, verified_at, expected):
    release = {"at": release_at, "sha": OTHER, "basis": "release_pins/subsecond.json"}
    result = build(prs=[pr(released=release)], health={"sha": SERVED, "ok": True, "at": verified_at})
    row = result["by_pr"][2501]
    assert row["live"]["value"] is expected
    assert M._parse(row["released"]["as_of"]) == M._parse(release_at)
    if expected:
        assert M._parse(row["live"]["as_of"]) == M._parse(verified_at)


def test_subseconds_sort_latest_owner_and_timeline_by_instant():
    newer = claim(session="newer", heartbeat_at="2026-11-03T01:00:00.100Z")
    older = claim(session="older", heartbeat_at="2026-11-03T01:00:00Z")
    data = build(claims=[newer, older], events=[
        event("check_request", ts="2026-11-03T00:00:00.100Z"),
        event("check_request", ts="2026-11-03T00:00:00Z"),
    ])
    row = data["by_pr"][2501]
    assert row["owner"]["value"]["session"] == "newer"
    assert data["sources"]["claims"]["as_of"] == "2026-11-03T01:00:00.100000Z"
    times = [e["as_of"] for e in row["timeline"] if e["kind"] == "check_request"]
    assert times == ["2026-11-03T00:00:00Z", "2026-11-03T00:00:00.100000Z"]


@pytest.mark.parametrize("kind,field", [("review_receipt_recorded", "review"), ("ci_observation", "ci")])
def test_invalid_current_head_record_never_lends_green_from_older_valid(kind, field):
    result = build(events=[event(kind, state="GREEN"), event(kind, ts="invalid", state="RED", verdict="BLOCK")])
    evidence = result["by_pr"][2501][field]
    assert evidence["state"] == "UNKNOWN"
    assert evidence["gap"] == f"invalid_{field}_timestamp"
    assert result["sources"]["coordinator_ledger"]["gap"] == "typed_evidence_timestamp_invalid"


def test_invalid_old_head_record_does_not_poison_current_head_review():
    result = build(events=[event(), event(head_sha=OTHER, ts="invalid", verdict="BLOCK")])
    assert result["by_pr"][2501]["review"]["state"] == "MERGE"


def test_registered_lead_default_routing_keeps_its_own_provenance_and_changes():
    registry = registry_value()
    registry["operator_quote"] = "PRIVATE-QUOTE"
    registry["note"] = "PRIVATE-NOTE"
    registry["coordinators"][0]["where"] = "PRIVATE-LOCATION"
    result = M.build([pr()], [claim()], [], [], [], NOW, coordination_registry=registry)
    row = result["by_pr"][2501]
    assert row["coordinator"] == {"value": "test-lead", "source": "coordinator_registry",
                                  "as_of": "2026-11-03T00:30:00Z", "gap": None,
                                  "source_ref": M.REGISTRY_REL, "routing_basis": "default_lead"}
    assert row["owner"]["value"]["coordinator"] is None  # no forged claim metadata
    assert "PRIVATE" not in json.dumps(result)
    changed = M.build([pr()], [claim()], [], [], [], NOW,
                      coordination_registry=registry_value("other-lead", updated_at="2026-11-03T01:00:00Z"))
    assert changed["by_pr"][2501]["coordinator"]["value"] == "other-lead"
    assert changed["by_pr"][2501]["coordinator"]["as_of"] == "2026-11-03T01:00:00Z"


def test_explicit_claim_coordinator_wins_without_forging_registry_source():
    result = M.build([pr()], [claim(coordinator="assigned-coordinator")], [], [], [], NOW,
                     coordination_registry=registry_value())
    routed = result["by_pr"][2501]["coordinator"]
    assert routed["value"] == "assigned-coordinator"
    assert routed["source"] == "claim_board"
    assert routed["as_of"] == "2026-11-03T01:00:00Z"
    assert routed["routing_basis"] == "explicit_claim"


@pytest.mark.parametrize("registry", [registry_value(role="observer"), registry_value(updated_at=None),
                                      registry_value(updated_at="2026-11-03T00:00:00"),
                                      {"lead": "not-registered", "updated_at": "2026-11-03T00:00:00Z",
                                       "coordinators": []}])
def test_observer_unregistered_or_undated_lead_is_not_guessed(registry):
    result = M.build([pr()], [claim()], [], [], [], NOW, coordination_registry=registry)
    assert result["by_pr"][2501]["coordinator"]["value"] is None
    assert result["by_pr"][2501]["coordinator"]["gap"]
    assert result["sources"]["coordination_registry"]["gap"]


def test_registry_load_missing_corrupt_and_budget_gaps_are_named(tmp_path, monkeypatch):
    write_sources(tmp_path)
    assert M.load(tmp_path, [pr()], [claim()], NOW)["by_pr"][2501]["coordinator"]["value"] == "test-lead"
    path = tmp_path / M.REGISTRY_REL
    path.write_text("{broken")
    assert M.load(tmp_path, [pr()], [claim()], NOW)["sources"]["coordination_registry"]["gap"] == "registry_corrupt"
    path.write_text(json.dumps(registry_value()))
    monkeypatch.setattr(M, "MAX_REGISTRY_BYTES", 1)
    assert M.load(tmp_path, [pr()], [claim()], NOW)["sources"]["coordination_registry"]["gap"] == "registry_byte_budget_exceeded"


def test_caller_source_gaps_survive_successful_local_load(tmp_path):
    write_sources(tmp_path)
    result = M.load(tmp_path, [pr()], [claim()], NOW, serving={"sha": SERVED},
                    source_gaps={"claims": "caller_claims_corrupt", "coordinator_ledger": "caller_ledger_gap"})
    assert result["sources"]["claims"]["gap"] == "caller_claims_corrupt"
    assert result["sources"]["coordinator_ledger"]["gap"] == "caller_ledger_gap"


def test_ci_gate_declares_its_acceptance_anchor():
    path = PATH.parents[2] / "config/ci_gates/work_pipeline_sources_20261103.json"
    assert json.loads(path.read_text())["anchor"] == "WORK_PIPELINE_SOURCES_20261103"


def test_latest_claim_owner_and_explicit_pr_conflict_are_respected():
    claims = [claim(session="older", heartbeat_at="2026-11-02T23:00:00Z"), claim(session="current")]
    assert build(claims=claims)["by_pr"][2501]["owner"]["value"]["session"] == "current"
    assert build(claims=[claim(pr=123)])["by_pr"][2501]["owner"]["value"] is None
    assert build(claims=[claim(pr=2501, branch="wt/renamed")])["by_pr"][2501]["owner"]["value"]["session"] == "worker"


def test_typed_public_history_and_approval_never_expose_raw_payloads():
    data = build(events=[event(detail="PRIVATE-EVENT", operator_quote="PRIVATE-QUOTE"),
                         event("freeform_status", detail="PRIVATE-FREEFORM")],
                 approvals=[approval(operator_chat_id="PRIVATE-ID", operator_words="PRIVATE-WORDS")])
    assert "PRIVATE" not in json.dumps(data)
    assert all(e["kind"] != "freeform_status" for e in data["by_pr"][2501]["timeline"])
    ci = build(events=[event("ci_observation", state="GREEN",
                             workflows=[{"name": "ci", "status": "completed", "conclusion": "success",
                                         "raw": "PRIVATE-RAW"}])])
    assert "PRIVATE" not in json.dumps(ci)
    assert ci["by_pr"][2501]["ci"]["state"] == "GREEN"


def test_plan_frontmatter_links_by_claim_and_does_not_expose_body(tmp_path):
    write_sources(tmp_path)
    front = {"id": "plan-one", "title": "Synthetic plan", "claim": "claim-one", "author_session": "worker",
             "approved_at": "2026-11-02T16:00:00Z", "updated_at": "2026-11-03T00:10:00Z",
             "operator_quote": "PRIVATE-QUOTE"}
    path = tmp_path / M.PLANS_REL / "plan-one.md"
    path.write_text("---\n" + "".join(f"{k}: {json.dumps(v)}\n" for k, v in front.items()) + "---\nPRIVATE-BODY")
    data = M.load(tmp_path, [pr()], [claim()], NOW, serving={"sha": SERVED})
    plan = data["by_pr"][2501]["plans"][0]
    assert plan["id"] == "plan-one"
    assert plan["as_of"] == "2026-11-03T00:10:00Z"
    assert "PRIVATE" not in json.dumps(data)
    assert data["plans"][0]["id"] == "plan-one"


def test_unlinked_plan_remains_in_inventory_without_inferred_same_author():
    data = build(plans=[{"id": "unlinked", "title": "Another task", "author_session": "worker",
                         "approved_at": "2026-11-02T16:00:00Z"}], claims=[claim(coordinator="lead")])
    row = data["by_pr"][2501]
    assert data["plans"][0]["id"] == "unlinked"
    assert row["plans"] == []
    assert row["plan_link"]["gap"] == "plan_link_not_recorded"
    assert row["coordinator"]["value"] == "lead"
    assert row["coordinator"]["gap"] is None


def test_naive_typed_evidence_is_a_gap_and_never_a_fresh_review():
    result = build(events=[event(ts="2026-11-03T01:00:00")])
    assert result["sources"]["coordinator_ledger"]["gap"] == "typed_evidence_timestamp_invalid"
    assert result["by_pr"][2501]["review"]["state"] == "UNKNOWN"


def test_missing_and_corrupt_sources_are_named_gaps(tmp_path):
    missing = M.load(tmp_path, [pr()], [], NOW)
    assert {row["source"] for row in missing["gaps"]} == {"coordinator_ledger", "digest_approvals", "plans", "releases", "coordination_registry"}
    write_sources(tmp_path)
    (tmp_path / M.LEDGER_REL).write_text("{broken")
    data = M.load(tmp_path, [pr()], [], NOW, serving={"sha": SERVED})
    assert {tuple(g.values()) for g in data["gaps"]} == {("coordinator_ledger", "corrupt")}


@pytest.mark.parametrize("items", [3, {}, "not-a-list", [None] * 501])
def test_semantically_invalid_digest_items_is_a_named_source_gap(tmp_path, items):
    write_sources(tmp_path, approvals=[approval(items=items)])
    result = M.load(tmp_path, [pr()], [], NOW, serving={"sha": SERVED})
    assert result["sources"]["digest_approvals"]["gap"] == "invalid_approval_items"
    assert result["by_pr"][2501]["approval"]["value"] is None
    assert result["by_pr"][2501]["approvals"] == []


def test_byte_and_event_bounds_are_reported_without_tail_inference(tmp_path, monkeypatch):
    write_sources(tmp_path)
    monkeypatch.setattr(M, "MAX_BYTES", 5)
    assert M.load(tmp_path, [], [], NOW)["sources"]["coordinator_ledger"]["gap"] == "byte_budget_exceeded"
    monkeypatch.setattr(M, "MAX_BYTES", 10000)
    monkeypatch.setattr(M, "MAX_EVENTS", 1)
    write_sources(tmp_path, events=[event(), event()])
    assert M.load(tmp_path, [], [], NOW)["sources"]["coordinator_ledger"]["gap"] == "event_budget_exceeded"


def test_plan_limits_corruption_and_symlink_are_named(tmp_path, monkeypatch):
    write_sources(tmp_path)
    plan = tmp_path / M.PLANS_REL / "plan.md"
    plan.write_text("---\nid: \"wrong\"\n---\n")
    assert M.load(tmp_path, [], [], NOW)["sources"]["plans"]["gap"] == "plan_id_mismatch"
    plan.write_text("---\nid: \"plan\"\n")
    assert M.load(tmp_path, [], [], NOW)["sources"]["plans"]["gap"] == "corrupt_frontmatter"
    monkeypatch.setattr(M, "MAX_PLAN_BYTES", 1)
    assert M.load(tmp_path, [], [], NOW)["sources"]["plans"]["gap"] == "byte_budget_exceeded"


def test_request_path_never_invokes_membership_or_network(tmp_path):
    write_sources(tmp_path)

    class Reader:
        calls = 0

        def serving(self):
            self.calls += 1
            return {"sha": SERVED}

        def released(self, *_args):
            raise AssertionError("membership belongs in background census")

        def ancestor(self, *_args):
            raise AssertionError("git/GitHub forbidden in request adapter")

    reader = Reader()
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    data = M.load(tmp_path, [pr()], [claim()], NOW, release_reader=reader,
                  health={"sha": SERVED, "ok": True, "at": "2026-11-03T00:05:00Z"})
    assert data["by_pr"][2501]["live"]["value"] is True
    assert reader.calls == 1
    assert {p: p.read_bytes() for p in before} == before

"""Ratification is authority only from a trusted same-main policy/manifest pair.

Synthetic policy/claims only. Pure helper tests never contact GitHub, install a
hook, send a message or push a branch; consumer tests stub trusted reads.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".cursor/hooks"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HOOKS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


auth = load("standing_policy_test", "guard_standing_policy.py")
MAIN = "a" * 40
REVIEWED = "b" * 40
TOKEN = f"APPROVE_AGENTS_POLICY_30_0_0 10001 {REVIEWED}"


def policy(binding="Standing-Authority: AgentStandingAuthority@v1"):
    return ("# AGENTS\n\n```\nPolicy-Version: 30.0.0\nStatus: ACTIVE\nEffective-Date: 2026-11-02\n```\n"
            "# 0 · If you read nothing else\n" + binding + "\nApproved work and all authority rails remain binding.\n"
            "# Version history\n| Version | Date | State | Approval |\n"
            f"| 30.0.0 | 2026-11-02 | ACTIVE | `{TOKEN}` (operator ratification) |\n")


def manifest():
    return {"schema": "AgentStandingAuthority@v1", "minimum_policy": "30.0.0", "status": "ACTIVE",
            "ratification": {"approval_token": TOKEN, "pr": 10001, "reviewed_head": REVIEWED},
            "capabilities": {"feature_push": {"branch_prefixes": ["wt/"], "approved_scope_required": True},
                             "delegated_upload": {"coordinator_handoff_required": True},
                             "coordinator_merge": {"ordinary_reviews": 1, "held_reviews": 2}},
            "reserved_paths": ["AGENTS.md", ".cursor/hooks/**"]}


def call(text=None, doc=None, **kw):
    return auth.authorize(policy() if text is None else text, manifest() if doc is None else doc,
                          capability=kw.pop("capability", "feature_push"), policy_sha=kw.pop("policy_sha", MAIN),
                          branch=kw.pop("branch", "wt/synthetic-feature"), **kw)


@pytest.mark.parametrize("capability", ["feature_push", "delegated_upload", "coordinator_merge"])
def test_real_ratification_grants_only_requested_capability_without_expiry_or_issue(capability):
    doc = manifest()
    before = deepcopy(doc)
    out = call(doc=doc, capability=capability)
    assert out["ok"] is True
    assert out["authority"]["policy_sha"] == MAIN
    assert out["authority"]["ratification"] == {"approval_token": TOKEN, "pr": 10001, "reviewed_head": REVIEWED}
    assert out["authority"]["capability"] == capability
    assert doc == before
    out["authority"]["requirements"].clear()
    assert doc == before


@pytest.mark.parametrize("value", [None, [], {}, "", 1])
def test_absent_or_malformed_manifest_fails_closed(value):
    out = auth.authorize(policy(), value, capability="feature_push", policy_sha=MAIN, branch="wt/synthetic-feature")
    assert out["ok"] is False and out["authority"] is None


@pytest.mark.parametrize("value", [None, [], {}, "feature", 1])
def test_malformed_capability_never_throws(value):
    assert call(capability=value)["ok"] is False


@pytest.mark.parametrize("value", [None, [], {}, "a" * 7, "a" * 41, "A" * 40, "main"])
def test_policy_commit_is_always_full_exact_sha(value):
    assert call(policy_sha=value)["ok"] is False


@pytest.mark.parametrize("status", ["PROPOSED", "SUPERSEDED", "ACTIVE-ish", "", None, []])
def test_manifest_must_be_exactly_active(status):
    doc = manifest()
    doc["status"] = status
    assert call(doc=doc)["ok"] is False


@pytest.mark.parametrize("replace", [
    ("Status: ACTIVE", "Status: PROPOSED"),
    ("Status: ACTIVE", "Status: ACTIVE-ish"),
    ("Policy-Version: 30.0.0", "Policy-Version: 29.9.9"),
    ("| ACTIVE |", "| PROPOSED |"),
    ("| ACTIVE |", "| ACTIVE-ish |"),
    (f"`{TOKEN}`", f"PENDING `{TOKEN}`"),
    (f"`{TOKEN}`", f"`{TOKEN}c`"),
    (f"`{TOKEN}`", f"`NOT_{TOKEN}`"),
    (f"`{TOKEN}`", f"`{TOKEN.replace(REVIEWED, 'c' * 40)}`"),
])
def test_policy_and_history_must_match_ratification(replace):
    assert call(text=policy().replace(*replace))["ok"] is False


@pytest.mark.parametrize("binding", ["", "> Standing-Authority: AgentStandingAuthority@v1",
    "```\nStanding-Authority: AgentStandingAuthority@v1\n```",
    "~~~\nStanding-Authority: AgentStandingAuthority@v1\n~~~",
    "<!-- Standing-Authority: AgentStandingAuthority@v1 -->",
    "    Standing-Authority: AgentStandingAuthority@v1",
    "\tStanding-Authority: AgentStandingAuthority@v1",
    "Standing-Authority: AgentStandingAuthority@v1 EXAMPLE"])
def test_examples_hidden_or_quoted_markers_cannot_grant(binding):
    assert call(text=policy(binding))["ok"] is False


def test_banner_and_history_mentions_do_not_grant_capability():
    text = "Standing-Authority: AgentStandingAuthority@v1\n" + policy("")
    text += "History example: Standing-Authority: AgentStandingAuthority@v1\n"
    assert call(text=text)["ok"] is False


@pytest.mark.parametrize("field,value", [("approval_token", None), ("pr", True), ("pr", "10001"),
    ("pr", 10002), ("reviewed_head", "c" * 40), ("reviewed_head", REVIEWED[:7]),
    ("approval_token", TOKEN.lower()), ("approval_token", TOKEN + " trailing")])
def test_ratification_tuple_requires_real_matching_fields(field, value):
    doc = manifest()
    doc["ratification"][field] = value
    assert call(doc=doc)["ok"] is False


@pytest.mark.parametrize("branch", [None, [], {}, "main", "master", "release/synthetic", "train/synthetic",
    "feat/synthetic", "wt/a..b", "wt/synthetic.lock", "wt/synthetic.", "wt/-bad", "wt/ab"])
def test_no_protected_or_ambiguous_branch_reach(branch):
    assert call(branch=branch)["ok"] is False


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(minimum_policy="29.9.9"),
    lambda d: d["capabilities"]["feature_push"].update(branch_prefixes=["wt/", "release/"]),
    lambda d: d["capabilities"]["feature_push"].update(approved_scope_required=False),
    lambda d: d["capabilities"]["delegated_upload"].update(coordinator_handoff_required=False),
    lambda d: d["capabilities"]["coordinator_merge"].update(ordinary_reviews=0),
    lambda d: d["capabilities"]["coordinator_merge"].update(held_reviews=1),
    lambda d: d["capabilities"]["coordinator_merge"].update(held_reviews=True),
    lambda d: d.update(reserved_paths=[]),
    lambda d: d.update(reserved_paths=["../outside"]),
])
def test_consistency_and_safety_floors_cannot_be_relaxed_by_manifest(mutate):
    doc = manifest()
    mutate(doc)
    assert call(doc=doc)["ok"] is False


def test_revocation_is_not_a_feature_or_environment_switch(tmp_path, monkeypatch):
    p = tmp_path / "coordinator" / "STANDING_AUTHORITY_REVOKED.json"
    monkeypatch.setattr(auth, "REVOCATION_PATH", p)
    monkeypatch.setenv("HOME", str(tmp_path / "attacker"))
    monkeypatch.setenv("STANDING_AUTHORITY_REVOKED", "false")
    assert auth.revoked_marker() is False
    p.parent.mkdir()
    p.symlink_to(tmp_path / "absent-target")
    assert auth.revoked_marker() is True
    assert call(revoked=auth.revoked_marker())["ok"] is False


@pytest.mark.parametrize("value", [True, None, [], {}, "false", 0])
def test_revoked_or_unknown_revocation_always_refuses(value):
    assert call(revoked=value)["ok"] is False


def test_pure_authorize_cannot_reach_files_or_spawn(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("pure validator reached I/O")
    monkeypatch.setattr(Path, "open", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    assert call()["ok"] is True


@pytest.fixture
def consumer(tmp_path, monkeypatch):
    g = load("standing_guard_consumer_test", "guard_push_free.py")
    monkeypatch.setattr(g, "standing_policy_module", lambda: auth)
    monkeypatch.setattr(auth, "revoked_marker", lambda: False)
    monkeypatch.setattr(g, "coordinator_lead", lambda cfg: "codex")
    def no_network(*a, **kw):
        raise AssertionError("ratification path requested a GitHub approval")
    monkeypatch.setattr(g, "_gh_api", no_network)
    monkeypatch.setattr(g, "_gh_api_list", no_network)
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir()
    cfg = {"_main_policy": {"_text": policy(), "_manifest": manifest(), "_sha": MAIN},
           "handoffs_dir": handoffs}
    return g, cfg


def claim(tmp_path, cid="owner", session="owner-session", branch="wt/synthetic-feature", **extra):
    return {"claim_id": cid, "session": session, "branch": branch, "_state": "live",
            "task": "Implement the operator-requested synthetic task", "_path": str(tmp_path / (cid + ".json")),
            "note": "Approved-scope: ROOT-TASK-001\nAssigned-by: codex", **extra}


def test_ratified_own_claim_needs_no_issue_or_named_comment(consumer, tmp_path):
    g, cfg = consumer
    row = claim(tmp_path)
    out = g.claim_approval(row["branch"], row["session"], cfg, [row])
    assert out["source"] == "claim+ratified-policy"
    assert out["approval_ref"] == "policy:" + MAIN
    assert out["claim_id"] == "owner" and out["session"] == "owner-session"
    assert out["scope"]["assigned_by"] == "codex"


def test_self_written_goal_alone_never_establishes_approved_scope(consumer, tmp_path):
    g, cfg = consumer
    row = claim(tmp_path, note="I decided this is approved")
    with pytest.raises(g.Refused, match="lacks recorded"):
        g.scope_provenance(row, cfg)


def test_other_session_cannot_use_own_claim_route(consumer, tmp_path):
    g, cfg = consumer
    with pytest.raises(g.Refused, match="no live claim"):
        g.claim_approval("wt/synthetic-feature", "recipient-session", cfg, [claim(tmp_path)])


def write_handoff(cfg, text):
    path = cfg["handoffs_dir"] / "task.md"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def handoff_text(**changes):
    fields = {"Assigned-branch": "wt/synthetic-feature", "Assigned-by": "codex",
              "Assigned-to": "recipient-session", "Owner-claim": "owner", "Owner-session": "owner-session",
              "Approved-scope": "ROOT-TASK-001"}
    fields.update(changes)
    return "\n".join(f"{key}: {value}" for key, value in fields.items()) + "\n"


def delegated_claims(tmp_path):
    return [claim(tmp_path), claim(tmp_path, cid="recipient", session="recipient-session", branch="wt/cleanup-scope")]


def test_ratified_delegation_attributes_actual_owner_and_recipient(consumer, tmp_path):
    g, cfg = consumer
    write_handoff(cfg, handoff_text())
    out = g.ratified_handoff("wt/synthetic-feature", "recipient-session", cfg, delegated_claims(tmp_path))
    assert out["source"] == "handoff+ratified-policy"
    assert out["owner_claim"] == "owner" and out["owner_session"] == "owner-session"
    assert out["recipient_claim"] == "recipient" and out["recipient_session"] == "recipient-session"
    assert out["budget_branch"] == "wt/synthetic-feature"


@pytest.mark.parametrize("field,value", [("Assigned-by", "observer"), ("Assigned-to", "another-session"),
    ("Assigned-branch", "wt/other-branch"), ("Owner-claim", "nonexistent"),
    ("Owner-session", "recipient-session"), ("Approved-scope", "different-task")])
def test_delegation_refuses_inconsistent_or_unassigned_handoffs(consumer, tmp_path, field, value):
    g, cfg = consumer
    write_handoff(cfg, handoff_text(**{field: value}))
    with pytest.raises(g.Refused, match="no consistent"):
        g.ratified_handoff("wt/synthetic-feature", "recipient-session", cfg, delegated_claims(tmp_path))


def test_delegation_requires_recipient_scope_even_with_real_owner(consumer, tmp_path):
    g, cfg = consumer
    write_handoff(cfg, handoff_text())
    rows = delegated_claims(tmp_path)
    rows[1]["note"] = "self-assigned work"
    with pytest.raises(g.Refused, match="no consistent"):
        g.ratified_handoff("wt/synthetic-feature", "recipient-session", cfg, rows)


def test_same_main_snapshot_supplies_policy_and_manifest(tmp_path, monkeypatch):
    import json
    g = load("standing_guard_main_read_test", "guard_push_free.py")
    monkeypatch.setattr(g, "_has", lambda *a: True)
    calls = []
    def read(repo, *args):
        calls.append(args)
        return policy() if args == ("show", MAIN + ":AGENTS.md") else json.dumps(manifest())
    monkeypatch.setattr(g, "_out", read)
    out = g.check_policy(tmp_path, MAIN)
    assert calls == [("show", MAIN + ":AGENTS.md"), ("show", MAIN + ":config/agent_standing_authority.json")]
    assert out["_sha"] == MAIN and out["_manifest"] == manifest()


def test_installer_copies_the_same_trusted_pure_module():
    source = (ROOT / "install-guardrails.sh").read_text(encoding="utf-8")
    assert ".cursor/hooks/guard_standing_policy.py" in source


def test_revocation_arriving_after_preflight_blocks_actual_push(consumer, monkeypatch):
    g, cfg = consumer
    plan = {"source": "claim+ratified-policy", "approval_ref": "policy:" + MAIN}
    ev = {"cfg": cfg, "repo": str(ROOT), "plan": plan, "approval_ref": plan["approval_ref"],
          "branch": "wt/synthetic-feature", "head": MAIN,
          "remote_head": "", "ff": "new", "refspec": MAIN + ":refs/heads/wt/synthetic-feature",
          "canonical": "https://example.test/synthetic/repo", "budget": {"count": 0, "budget": 2},
          "policy": {"main": MAIN, "version": "30.0.0"}, "dry_run": "synthetic", "pins": ()}
    def intent(*a, **kw):
        monkeypatch.setattr(auth, "revoked_marker", lambda: True)
        return {"chain_hash": "synthetic-intent"}
    def never_push(*a, **kw):
        raise AssertionError("revoked capability reached actual git push")
    monkeypatch.setattr(g, "audit", intent)
    monkeypatch.setattr(g, "_git", never_push)
    with pytest.raises(g.Refused, match="revoked before push"):
        g.do_push(ev, "owner-session", str(ROOT))


@pytest.mark.parametrize("change", [
    lambda d: d["coordinators"][0].update(role="observer"),
    lambda d: d["coordinators"][0].update(territories="agents"),
    lambda d: d["coordinators"].append({"id": "codex", "role": "observer", "territories": []}),
    lambda d: d.update(lead="absent"),
])
def test_real_registry_reader_refuses_role_and_identity_inconsistency(tmp_path, monkeypatch, change):
    import json
    g = load("standing_guard_registry_test", "guard_push_free.py")
    monkeypatch.setattr(g, "standing_policy_module", lambda: auth)
    monkeypatch.setattr(auth, "COORDINATION_ROOT", tmp_path)
    doc = {"schema": "CoordinatorRegistry@v1", "lead": "codex",
           "coordinators": [{"id": "codex", "role": "lead", "territories": ["agents"]}]}
    path = tmp_path / "coordinators.json"
    path.write_text(json.dumps(doc))
    assert g.coordinator_lead({}) == "codex"
    change(doc)
    path.write_text(json.dumps(doc))
    with pytest.raises(g.Refused, match="unavailable or inconsistent"):
        g.coordinator_lead({})

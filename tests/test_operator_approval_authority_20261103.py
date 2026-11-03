"""Synthetic snapshots only: approval scope cannot reach any mutation entrypoint."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/lib/operator_approval_authority.py"
SPEC = importlib.util.spec_from_file_location("operator_approval_authority_tested", PATH)
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
NOW = datetime(2032, 4, 12, 14, tzinfo=timezone.utc)
MAIN, HEAD, REVIEWED = "a" * 40, "b" * 40, "c" * 40


class FakeGuard:
    SCHEMA = "AgentStandingAuthority@v1"

    @staticmethod
    def revoked_marker():
        return False

    @staticmethod
    def authorize(policy, manifest, **kwargs):
        if manifest.get("status") != "ACTIVE" or kwargs.get("revoked"):
            return {"ok": False}
        return {
            "ok": True,
            "authority": {
                "manifest_schema": FakeGuard.SCHEMA,
                "repository": M.REPOSITORY,
                "policy_sha": kwargs["policy_sha"],
                "capability": "coordinator_merge",
                "reserved_paths": ["protected/policy"],
                "requirements": {"excluded_globs": ["protected/credential"]},
                "ratification": {
                    "pr": 42,
                    "reviewed_head": REVIEWED,
                    "approval_token": f"APPROVE_AGENTS_POLICY_30_0_0 42 {REVIEWED}",
                },
            },
        }

    @staticmethod
    def verify_ratification_evidence(authority, comments, expected_operator):
        token = authority["ratification"]["approval_token"]
        if comments != [{"verified_fixture_token": token}]:
            return {"ok": False}
        return {
            "ok": True,
            "authority": {
                **authority,
                "ratification_evidence": {
                    "comment_id": 7,
                    "url": "https://github.com/example/synthetic/issues/42#issuecomment-7",
                    "created_at": "2032-04-12T13:00:00Z",
                },
            },
        }


class FakeMerge:
    RESERVED = ("protected/policy",)
    OPERATOR_ONLY = ("protected/credential",)
    DECISION_PATHS = ("protected/runtime",)

    @staticmethod
    def hits(path, patterns):
        return path in patterns

    @staticmethod
    def collect_held_classes(paths, config, helper):
        if config.get("schema") != "MergeHoldPaths@v1" or "unknown/class" in paths:
            raise ValueError("unclassified")
        return ["engineering"], {}

    @staticmethod
    def run(*args, **kwargs):
        raise AssertionError("execution must never be reached")


class Gh:
    def __init__(self):
        self.calls = []
        self.comment = {"verified_fixture_token": f"APPROVE_AGENTS_POLICY_30_0_0 42 {REVIEWED}"}

    def get(self, path):
        self.calls.append(path)
        if path.endswith("commits/main"):
            return {"sha": MAIN}, None
        if "/comments?" in path:
            return [self.comment], None
        raise AssertionError("unexpected read path")


@pytest.fixture
def setup(monkeypatch):
    docs = {
        "AGENTS.md": "Policy-Version: 30.0.0\nStatus: ACTIVE\n",
        "config/agent_standing_authority.json": json.dumps({"status": "ACTIVE"}),
        "config/merge_hold_paths.json": json.dumps({"schema": "MergeHoldPaths@v1"}),
        ".cursor/hooks/guard_standing_policy.py": "guard",
        "scripts/lib/pr_merge_delegation.py": "merge",
        "scripts/lib/merge_hold_paths.py": "hold",
    }

    def git(*args):
        if args == ("rev-parse", "refs/remotes/origin/main"):
            return MAIN
        assert args[0] == "show" and args[1].startswith(MAIN + ":")
        return docs[args[1].split(":", 1)[1]]

    def module(path, expected):
        if path.name == "guard_standing_policy.py":
            return FakeGuard
        if path.name == "pr_merge_delegation.py":
            return FakeMerge
        return SimpleNamespace()

    monkeypatch.setattr(M, "_module", module)
    monkeypatch.setattr(M, "_installed_hooks", lambda: Path("/synthetic/installed/hooks"))
    return docs, git, Gh()


def context(setup):
    _, git, gh = setup
    return M.load_context(git=git, gh=gh, now=NOW)


def test_ratified_engineering_routes_to_coordinator_without_execution(setup):
    c = context(setup)
    result = c.classify(["engineering/source"], head_sha=HEAD)
    assert c.mode == "delegated" and result["complete"] and result["gap"] is None
    assert result["operator_required"] is False and result["next_actor"] == "coordinator"
    assert result["head_sha"] == HEAD and result["policy_sha"] == MAIN
    assert result["ratification"]["reviewed_head"] == REVIEWED
    calls = len(setup[2].calls)
    c.classify(["engineering/peer"], head_sha=HEAD)
    assert len(setup[2].calls) == calls  # classification performs no GitHub work


@pytest.mark.parametrize("version", ["28.0.0", "29.3.0"])
def test_healthy_legacy_policy_needs_no_helper_and_has_no_source_gap(setup, monkeypatch, version):
    docs, _, gh = setup
    docs["AGENTS.md"] = f"Policy-Version: {version}\nStatus: ACTIVE\n"
    monkeypatch.setattr(M, "_module", lambda *a: pytest.fail("legacy must not load 30 helper"))
    c = context(setup)
    result = c.classify(["engineering/source"], head_sha=HEAD)
    assert c.mode == "legacy" and result["complete"] and result["gap"] is None
    assert result["operator_required"] and result["next_actor"] == "operator"
    assert len(gh.calls) == 1


@pytest.mark.parametrize("path", ["protected/policy", "protected/credential", "protected/runtime"])
def test_mixed_and_previous_protected_paths_stay_operator_owned(setup, path):
    c = context(setup)
    for files, previous in [(["engineering/source", path], []), (["engineering/renamed"], [path])]:
        result = c.classify(files, previous_paths=previous, head_sha=HEAD)
        assert result["operator_required"] and result["complete"]
        assert result["reason"] == "operator_reserved_or_live_decision"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"files": []},
        {"files": ["../escape"]},
        {"files": ["engineering/source"], "previous_paths": None},
        {"files": ["engineering/source"], "paths_complete": False},
        {"files": ["engineering/source"], "head_sha": "branch-name"},
        {"files": ["unknown/class"]},
    ],
)
def test_incomplete_paths_heads_or_classification_refuse_delegation(setup, kwargs):
    result = context(setup).classify(**{"head_sha": HEAD, **kwargs})
    assert result["operator_required"] and not result["complete"]
    assert result["gap"] == "APPROVAL_AUTHORITY_SCOPE_UNPROVEN"


@pytest.mark.parametrize("failure", ["inactive", "unratified", "helper_missing", "main_moved", "invalid_policy"])
def test_missing_active_or_genuine_authority_cannot_delegate(setup, monkeypatch, failure):
    docs, git, gh = setup
    if failure == "inactive":
        docs["config/agent_standing_authority.json"] = json.dumps({"status": "PROPOSED"})
    elif failure == "unratified":
        gh.comment = {"verified_fixture_token": "wrong-head"}
    elif failure == "helper_missing":
        monkeypatch.setattr(M, "_module", lambda *a: (_ for _ in ()).throw(FileNotFoundError()))
    elif failure == "main_moved":
        original = gh.get
        gh.get = lambda p: ({"sha": HEAD}, None) if p.endswith("commits/main") else original(p)
    else:
        docs["AGENTS.md"] = "Policy-Version: 30.0.0\nStatus: PROPOSED\n"
    c = context(setup)
    result = c.classify(["engineering/source"], head_sha=HEAD)
    assert c.mode == "unavailable" and result["operator_required"]
    assert result["gap"] == "APPROVAL_AUTHORITY_SOURCE_UNAVAILABLE"


def test_real_helper_loader_requires_exact_main_bytes_and_writes_no_cache(tmp_path):
    source = tmp_path / "fixture.py"
    source.write_text("MARKER = 7\n")
    source.chmod(0o600)
    real_loader = M.__dict__["_module"]
    assert real_loader(source, "MARKER = 7\n").MARKER == 7
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fixture.py"]
    with pytest.raises(ValueError, match="not_current_main"):
        real_loader(source, "MARKER = 8\n")
    source.chmod(0o666)
    with pytest.raises(ValueError, match="unsafe"):
        real_loader(source, "MARKER = 7\n")


def test_exact_policy_comment_and_unverified_continuation(setup):
    c = context(setup)
    token = f"APPROVE_AGENTS_POLICY_30_0_0 42 {HEAD}"
    result = c.policy_approval(pr=42, head_sha=HEAD, version="30.0.0", comments=[public_comment(token)])
    assert result["state"] == "approved" and result["proof"]["comment_id"] == 7
    assert c.policy_approval(pr=42, head_sha=HEAD, version="30.0.0", comments=[])["state"] == "pending"
    changed = c.policy_approval(
        pr=42, head_sha=HEAD, version="30.0.0", reviewed_head_sha=REVIEWED, comments=[{"verified_fixture_token": token}]
    )
    assert changed["state"] == "unknown" and changed["gap"] == "POLICY_RATIFICATION_CONTINUATION_UNVERIFIED"
    assert c.policy_approval(pr=42, head_sha=HEAD, version="29.0.0", comments=[])["state"] == "pending"


def test_comment_pagination_truncation_is_a_gap(setup, monkeypatch):
    docs, git, gh = setup
    gh.get = lambda p: ({"sha": MAIN}, None) if p.endswith("commits/main") else ([{}] * 100, None)
    c = context(setup)
    assert c.gap == "APPROVAL_AUTHORITY_SOURCE_UNAVAILABLE"


def test_clock_requires_timezone(setup):
    with pytest.raises(ValueError, match="aware_clock"):
        M.load_context(git=setup[1], gh=setup[2], now=NOW.replace(tzinfo=None))


def public_comment(token, **updates):
    return {
        "id": 7,
        "user": {"login": M.REPOSITORY.split("/")[0], "type": "User"},
        "body": token,
        "html_url": f"https://github.com/{M.REPOSITORY}/issues/42#issuecomment-7",
        "created_at": "2032-04-12T13:00:00Z",
        "updated_at": "2032-04-12T13:00:00Z",
        **updates,
    }


def test_legacy_policy_bootstrap_exact_public_comment_and_no_authority_change(setup):
    docs, _, gh = setup
    docs["AGENTS.md"] = "Policy-Version: 29.3.0\nStatus: ACTIVE\n"
    c = context(setup)
    assert c.mode == "legacy" and c.guard is None
    token = f"APPROVE_AGENTS_POLICY_30_0_0 42 {HEAD}"
    gh.comment = public_comment(token)
    assert c.policy_approval(pr=42, head_sha=HEAD, version="30.0.0")["state"] == "approved"
    count = len(gh.calls)
    assert c.policy_approval(pr=42, head_sha=HEAD, version="30.0.0")["state"] == "approved"
    assert len(gh.calls) == count  # one policy comments read in this snapshot
    assert c.classify(["engineering/source"], head_sha=HEAD)["operator_required"] is True
    # A new head cannot borrow that exact-head comment.
    assert c.policy_approval(pr=42, head_sha=MAIN, version="30.0.0")["state"] == "pending"


@pytest.mark.parametrize(
    "body",
    [
        "```\n{token}\n```",
        "Example: {token}",
        "<!-- {token} -->",
        "Approved earlier: {token}",
        "{token} and then merge",
    ],
)
def test_fences_examples_or_extra_words_are_not_policy_ratification(setup, body):
    token = f"APPROVE_AGENTS_POLICY_30_0_0 42 {HEAD}"
    row = public_comment(body.format(token=token))
    assert context(setup).policy_approval(pr=42, head_sha=HEAD, version="30.0.0", comments=[row])["state"] == "pending"


@pytest.mark.parametrize(
    "updates",
    [
        {"updated_at": "2032-04-12T13:01:00Z"},
        {"created_at": "2032-04-12T13:00:00", "updated_at": "2032-04-12T13:00:00"},
        {"html_url": "https://github.com/other/repo/issues/42#issuecomment-7"},
        {"user": {"login": M.REPOSITORY.split("/")[0], "type": "Bot"}},
        {"id": True},
    ],
)
def test_ambiguous_matching_comment_is_unknown_not_approved(setup, updates):
    token = f"APPROVE_AGENTS_POLICY_30_0_0 42 {HEAD}"
    row = public_comment(token, **updates)
    result = context(setup).policy_approval(pr=42, head_sha=HEAD, version="30.0.0", comments=[row])
    assert result["state"] == "unknown" and result["gap"] == "POLICY_RATIFICATION_EVIDENCE_INVALID"


def test_foreign_author_and_malformed_comment_source_cannot_approve(setup):
    token = f"APPROVE_AGENTS_POLICY_30_0_0 42 {HEAD}"
    c = context(setup)
    foreign = public_comment(token, user={"login": "fixture-worker", "type": "User"})
    assert c.policy_approval(pr=42, head_sha=HEAD, version="30.0.0", comments=[foreign])["state"] == "pending"
    assert c.policy_approval(pr=42, head_sha=HEAD, version="30.0.0", comments=[None])["state"] == "unknown"


def test_malformed_positive_verifier_proof_does_not_delegate(setup, monkeypatch):
    monkeypatch.setattr(FakeGuard, "verify_ratification_evidence", lambda *a: {"ok": True, "authority": {}})
    c = context(setup)
    assert c.mode == "unavailable" and c.gap == "APPROVAL_AUTHORITY_SOURCE_UNAVAILABLE"
    assert c.classify(["engineering/source"], head_sha=HEAD)["operator_required"]

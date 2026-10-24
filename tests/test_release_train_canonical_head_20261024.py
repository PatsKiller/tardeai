"""Canonical verifier alignment: fake Git/issuer boundaries and owned temporary Git only.

No live train, source checkout, provider, credentials or real capability is accessed or issued.
"""
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import release_window as rw
from scripts.lib import release_train_controller as t

TARGET = "a" * 40
OLD = "b" * 40
NOW = 1792843200.0


class ReachedPrepare(Exception):
    pass


class FakeHost:
    def __init__(self, root):
        self.canonical = root / "canonical-fixture"
        self.checkout = root / "release-fixture"
        self.deploy = root / "not-executed.sh"
        self.head = OLD
        self.calls = []
        self.status = []
        self.checkout_rc = 0
        self.checkout_changes_head = True

    def _run(self, args):
        assert args[:3] == ["git", "-C", str(self.canonical)]
        cmd = args[3:]
        self.calls.append(cmd)
        if cmd == ["status", "--porcelain", "--untracked-files=all"]:
            return self.status.pop(0) if self.status else (0, "")
        assert cmd == ["checkout", "--detach", TARGET]
        if not self.checkout_rc and self.checkout_changes_head:
            self.head = TARGET
        return self.checkout_rc, "fixture credential should-never-leak"

    def canonical_head(self):
        return self.head

    def checkout_clean(self):
        return True

    def current_release(self):
        return self.checkout.parent / "previous"

    def build_sha(self, _):
        return "f" * 40


def controller(tmp_path, host=None):
    """Exercise real controller preflight only; stop at the fake prepare-issuance boundary."""
    c = object.__new__(t.TrainController)
    c.host = host or FakeHost(tmp_path)
    c.live = True
    c.train_id = "rt-20261024-1800-fixture"
    c.tstate, c.event_errors, c.steps = {}, [], []
    c.events = t.MemoryEventSink()
    c.epoch_at_claim = 0
    c.env = {}
    c.cfg = SimpleNamespace(main_ci_timeout_s=1)
    c._ts = lambda: NOW
    c._save_state = lambda **kw: c.tstate.update(kw)
    c._phase = lambda *_: None
    c._boundary = lambda *_: None
    c.host_units = lambda: ()
    c.github = SimpleNamespace(main_head=lambda: TARGET)
    c.quarantined = lambda: []
    c.order = []

    def wait_checks(sha, names, timeout, outcome, label):
        assert sha == TARGET and label == "main" and outcome == t.MERGED_NOT_LIVE
        assert names == tuple(n for n in t.REQUIRED_CHECKS if n != t.BATCH_QUALIFIER)
        c.order.append("exact_main_ci")
        return {"sha": TARGET, "checks": []}

    def issue(*args, **kw):
        c.order.append("prepare_issuance_boundary")
        assert c.host.canonical_head() == TARGET
        assert kw["candidate_sha"] == TARGET and kw["actions"] == ["prepare_release"]
        raise ReachedPrepare

    c._wait_checks = wait_checks
    c.authority = SimpleNamespace(issue_promote=issue)
    c._cap_effect = lambda issue, *args, **kw: issue()
    return c


def promote(c):
    c._promote({"base_sha": OLD, "manifest_digest": "sha256:" + "c" * 64},
               {"members": [], "sha": "d" * 40}, {"pr": 1, "evidence": {"sha": "d" * 40}}, TARGET, {})


def test_clean_stale_verifier_aligns_after_exact_main_ci_before_issuance(tmp_path):
    c = controller(tmp_path)
    original_run = c.host._run

    def ordered_git(args):
        assert c.order == ["exact_main_ci"]
        return original_run(args)

    c.host._run = ordered_git
    with pytest.raises(ReachedPrepare):
        promote(c)
    assert c.order == ["exact_main_ci", "prepare_issuance_boundary"]
    assert c.host.calls.count(["checkout", "--detach", TARGET]) == 1
    assert c.tstate["canonical_source_alignment"]["action"] == "ALIGNED"
    assert [e["payload"]["action"] for e in c.events.rows] == ["CHECKOUT_STARTED", "ALIGNED"]
    assert c.event_errors == []


def test_already_aligned_clean_verifier_is_noop(tmp_path):
    c = controller(tmp_path)
    c.host.head = TARGET
    with pytest.raises(ReachedPrepare):
        promote(c)
    assert c.host.calls == [["status", "--porcelain", "--untracked-files=all"]]
    assert c.tstate["canonical_source_alignment"]["action"] == "NO_OP"


@pytest.mark.parametrize("head", [OLD, TARGET])
def test_dirty_canonical_refuses_even_at_target_without_prepare_or_checkout(tmp_path, head):
    c = controller(tmp_path)
    c.host.head, c.host.status = head, [(0, "?? private-fixture.txt")]
    with pytest.raises(t.Halt) as error:
        promote(c)
    assert error.value.outcome == t.MERGED_NOT_LIVE and error.value.reason == "CANONICAL_SOURCE_DIRTY"
    assert c.order == ["exact_main_ci"]
    assert not any(x[0] == "checkout" for x in c.host.calls)
    assert "private-fixture" not in json.dumps(c.events.rows)


@pytest.mark.parametrize("failure,reason", [
    ("status", "CANONICAL_SOURCE_STATUS_FAILED"),
    ("checkout", "CANONICAL_SOURCE_CHECKOUT_FAILED"),
    ("no_head", "CANONICAL_SOURCE_HEAD_MISMATCH"),
    ("unchanged_head", "CANONICAL_SOURCE_HEAD_MISMATCH"),
    ("dirty_after", "CANONICAL_SOURCE_DIRTY"),
    ("runner_exception", "CANONICAL_SOURCE_GIT_FAILED"),
])
def test_alignment_failure_is_sanitized_and_precedes_capability(tmp_path, failure, reason):
    c = controller(tmp_path)
    if failure == "status":
        c.host.status = [(1, "credential should-never-leak")]
    elif failure == "checkout":
        c.host.checkout_rc = 1
    elif failure == "no_head":
        c.host.head = ""
    elif failure == "unchanged_head":
        c.host.checkout_changes_head = False
    elif failure == "dirty_after":
        c.host.status = [(0, ""), (0, ""), (0, " M fixture.txt")]
    elif failure == "runner_exception":
        def broken(_):
            raise OSError("credential should-never-leak")
        c.host._run = broken
    with pytest.raises(t.Halt) as error:
        promote(c)
    assert error.value.reason == reason and error.value.outcome == t.MERGED_NOT_LIVE
    assert c.order == ["exact_main_ci"]
    assert "should-never-leak" not in error.value.detail + json.dumps(c.events.rows) + json.dumps(c.tstate)
    assert c.tstate["canonical_source_alignment"]["action"] == "REFUSED"


def test_main_ci_failure_never_reads_or_moves_canonical(tmp_path):
    c = controller(tmp_path)

    def failed(*_):
        raise t.Halt(t.MERGED_NOT_LIVE, "MAIN_CI_FAILED", "fixture CI refusal")

    c._wait_checks = failed
    with pytest.raises(t.Halt) as error:
        promote(c)
    assert error.value.reason == "MAIN_CI_FAILED" and error.value.detail == "fixture CI refusal"
    assert c.host.calls == [] and c.order == []


def test_stop_at_new_mutation_boundary_prevents_checkout_and_capability(tmp_path):
    c = controller(tmp_path)

    def stopped(label):
        if label == "canonical_source_alignment":
            raise t.Halt(t.MERGED_NOT_LIVE, "STOP_REQUESTED", "fixture STOP")

    c._boundary = stopped
    with pytest.raises(t.Halt) as error:
        promote(c)
    assert error.value.reason == "STOP_REQUESTED"
    assert c.order == ["exact_main_ci"] and not any(x[0] == "checkout" for x in c.host.calls)


def test_current_movement_prevents_canonical_alignment(tmp_path):
    c = controller(tmp_path)
    previous = c.host.current_release()
    reads = iter([previous, previous.parent / "different", previous.parent / "different"])
    c.host.current_release = lambda: next(reads)
    with pytest.raises(t.Halt) as error:
        promote(c)
    assert error.value.reason == "CURRENT_MOVED" and c.host.calls == []


def local_git(root, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                           "-C", str(root), *args], env=env, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def canonical(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "canonical-only-fixture"
    repo.mkdir()
    local_git(repo, "init", "-q", "-b", "main")
    (repo / "app.txt").write_text("old\n")
    local_git(repo, "add", "app.txt")
    local_git(repo, "commit", "-q", "-m", "old")
    old = local_git(repo, "rev-parse", "HEAD")
    (repo / "app.txt").write_text("new\n")
    local_git(repo, "commit", "-q", "-am", "new")
    target = local_git(repo, "rev-parse", "HEAD")
    local_git(repo, "checkout", "--detach", old)
    return repo, old, target


def test_real_temporary_git_detaches_exact_commit_without_changing_branch(canonical, tmp_path):
    repo, old, target = canonical
    c = controller(tmp_path, rw.Host(checkout=tmp_path / "unused", canonical=repo, releases=tmp_path / "unused-rel"))
    c._align_canonical_at(target)
    assert local_git(repo, "rev-parse", "HEAD") == target
    assert local_git(repo, "rev-parse", "refs/heads/main") == target
    assert local_git(repo, "status", "--porcelain") == ""
    with pytest.raises(subprocess.CalledProcessError):
        local_git(repo, "symbolic-ref", "-q", "HEAD")
    assert c.tstate["canonical_source_alignment"]["head_before"] == old
    assert (repo / "app.txt").read_text() == "new\n"


@pytest.mark.parametrize("tracked", [True, False])
def test_real_temporary_dirty_tree_is_preserved(canonical, tmp_path, tracked):
    repo, old, target = canonical
    path = repo / ("app.txt" if tracked else "untracked.txt")
    path.write_text("operator fixture work\n")
    c = controller(tmp_path, rw.Host(checkout=tmp_path / "unused", canonical=repo, releases=tmp_path / "unused-rel"))
    with pytest.raises(t.Halt) as error:
        c._align_canonical_at(target)
    assert error.value.reason == "CANONICAL_SOURCE_DIRTY"
    assert local_git(repo, "rev-parse", "HEAD") == old
    assert path.read_text() == "operator fixture work\n"

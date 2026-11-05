"""CHECK is read-only metadata evidence; only the actual push runs verified hooks.

All process, transport, authority and audit boundaries are injected. These tests
never call Git, GitHub, the installed guard, a real journal or a push endpoint.
They replace the former dry-transport premise with explicit preview evidence.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

BRANCH = "wt/synthetic-preview"
SESSION = "synthetic-session"
HEAD = "a" * 40
MAIN = "b" * 40
REMOTE = "c" * 40
CANONICAL = "https://example.invalid/synthetic/repository"


@pytest.fixture
def preview(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / ".cursor/hooks/guard_push_free.py"
    name = "guard_push_preview_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    g = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, g)
    spec.loader.exec_module(g)
    calls = []
    state = {"head": HEAD, "remote": None, "count": 0, "budget": 2, "dirty": "", "policy": "30.0.0"}
    cfg = {"canonical_url": CANONICAL, "credential_helper": "synthetic-unused",
           "ls_remote_timeout": 10, "push_timeout": 30}
    monkeypatch.setattr(g, "load_config", lambda: dict(cfg))

    def never_process(*args, **kwargs):
        raise AssertionError("synthetic check reached a real process")

    monkeypatch.setattr(g.subprocess, "run", never_process)

    def read(repo, *args, **kwargs):
        calls.append(("read", args))
        if args == ("rev-parse", "--show-toplevel"):
            return str(tmp_path)
        if args == ("rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}^{{commit}}"):
            return state["head"]
        if args == ("symbolic-ref", "--quiet", "HEAD"):
            return f"refs/heads/{BRANCH}"
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return state["dirty"]
        if args == ("diff", "--name-only", "HEAD"):
            return "synthetic.py"
        raise AssertionError(("unexpected metadata command", args))

    monkeypatch.setattr(g, "_out", read)
    monkeypatch.setattr(g, "_has", lambda *args: True)

    def git(repo, *args, **kwargs):
        calls.append(("git", args))
        if args[0] == "push":
            raise AssertionError("CHECK/evaluate reached Git push")
        assert args == ("merge-base", "--is-ancestor", state["remote"], state["head"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(g, "_git", git)

    def remote(repo, canonical, branch, timeout, pins):
        calls.append(("remote", canonical, branch))
        return {"refs/heads/main": MAIN, **({f"refs/heads/{BRANCH}": state["remote"]} if state["remote"] else {})}

    def policy(repo, main):
        calls.append(("policy", main))
        return {"version": state["policy"]}

    def gate(name):
        def check(*args, **kwargs):
            calls.append((name, args))
        return check

    def budget(repo, branch, cfg):
        calls.append(("budget", branch))
        if state["count"] >= state["budget"]:
            raise g.Refused("synthetic budget exhausted")
        return {"count": state["count"], "budget": state["budget"]}

    def plan(branch, session, cfg, *, bind_session):
        calls.append(("plan", branch, session, bind_session))
        if bind_session and session != SESSION:
            raise g.Refused("synthetic session refused")
        return {"source": "claim+ratified-policy", "approval_ref": "policy:" + MAIN,
                "scope": {"paths": ["synthetic.py"]}, "session": session}

    monkeypatch.setattr(g, "check_remote_config", gate("remote-config"))
    monkeypatch.setattr(g, "ls_remote", remote)
    monkeypatch.setattr(g, "check_policy", policy)
    monkeypatch.setattr(g, "check_prepush", gate("prepush-closure"))
    monkeypatch.setattr(g, "check_broker_paths", gate("scope"))
    monkeypatch.setattr(g, "check_budget", budget)
    monkeypatch.setattr(g, "find_plan", plan)
    monkeypatch.setattr(g, "audit", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("CHECK reached journal")))
    monkeypatch.setattr(g, "refuse_dirty_env", lambda: None)
    return g, tmp_path, state, calls


def evaluate(preview, *, bind_session=False):
    g, repo, _, _ = preview
    return g.evaluate(str(repo), BRANCH, SESSION, bind_session=bind_session)


def test_preview_never_reaches_push_or_journal_and_keeps_real_evidence(preview):
    g, repo, state, calls = preview
    before = sorted((str(p.relative_to(repo)), p.read_bytes()) for p in repo.rglob("*") if p.is_file())
    out = evaluate(preview)
    after = sorted((str(p.relative_to(repo)), p.read_bytes()) for p in repo.rglob("*") if p.is_file())
    assert before == after
    assert out["schema"] == "GuardGrantFreePush@v2" and out["allow"] is True
    assert out["preview"] == {"schema": "GuardPushPreview@v1", "kind": "metadata-preflight",
                              "transport_checked": False, "pre_push_executed": False,
                              "remote_write_attempted": False}
    assert "metadata-only" in out["dry_run"] and "no Git push" in out["dry_run"]
    assert "\t" not in out["dry_run"] and "outcome" not in out and "result" not in out
    assert out["head"] == HEAD and out["remote_head"] == "" and out["ff"] == "new-branch"
    assert out["refspec"] == HEAD + ":refs/heads/" + BRANCH
    assert out["canonical"] == CANONICAL and out["policy"] == {"version": "30.0.0", "main": MAIN}
    assert out["budget"] == {"count": 0, "budget": 2} and out["plan"]["scope"]["paths"] == ["synthetic.py"]
    assert {c[0] for c in calls} >= {"remote-config", "remote", "policy", "prepush-closure", "scope", "budget", "plan"}


def test_preview_changes_with_underlying_head_remote_policy_and_budget(preview):
    _, _, state, _ = preview
    first = evaluate(preview)
    state.update(head="d" * 40, remote=REMOTE, count=1, policy="30.1.0")
    second = evaluate(preview)
    assert second["head"] != first["head"] and second["refspec"] != first["refspec"]
    assert second["remote_head"] == REMOTE and second["ff"] == "fast-forward"
    assert second["budget"] == {"count": 1, "budget": 2} and second["policy"]["version"] == "30.1.0"
    state["remote"] = state["head"]
    assert evaluate(preview)["ff"] == "up-to-date"
    state["count"] = 2
    with pytest.raises(preview[0].Refused, match="budget exhausted"):
        evaluate(preview)


@pytest.mark.parametrize("name", ["check_remote_config", "ls_remote", "check_policy", "check_prepush",
                                   "check_fast_forward", "check_broker_paths", "check_budget", "find_plan"])
def test_preview_refuses_when_each_existing_evidence_gate_refuses(preview, monkeypatch, name):
    g = preview[0]
    def refuse(*args, **kwargs):
        raise g.Refused("synthetic refusal from " + name)
    monkeypatch.setattr(g, name, refuse)
    with pytest.raises(g.Refused, match=name):
        evaluate(preview)


def test_preview_cli_reports_metadata_without_calling_do_push(preview, monkeypatch, capsys):
    g, repo, _, _ = preview
    monkeypatch.setattr(g, "do_push", lambda *a: (_ for _ in ()).throw(AssertionError("CHECK entered do_push")))
    assert g.main(["check", "--repo", str(repo), "--branch", BRANCH, "--session", SESSION]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["preview"]["transport_checked"] is False and "cfg" not in out and "pins" not in out


def pushing(preview, monkeypatch, *, rc=0, stdout=None, intent_error=False, revoked=False):
    g, repo, _, calls = preview
    ev = evaluate(preview, bind_session=True)
    events = []
    def audit(row, cfg):
        events.append(("audit", dict(row)))
        if row["event"] == "grant-free-push-intent" and intent_error:
            raise g.Refused("synthetic intent failure")
        return {"chain_hash": "synthetic-" + str(len(events))}
    def transport(path, *args, **kwargs):
        events.append(("push", args, kwargs))
        return subprocess.CompletedProcess(args, rc, stdout if stdout is not None else
                                           "*\t" + ev["refspec"] + "\t[new branch]\n", "synthetic transport failure" if rc else "")
    monkeypatch.setattr(g, "audit", audit)
    monkeypatch.setattr(g, "_git", transport)
    monkeypatch.setattr(g, "standing_policy_module", lambda: types.SimpleNamespace(revoked_marker=lambda: revoked))
    return g, repo, ev, events


def test_actual_push_retains_verified_hook_pin_and_intent_before_one_transport(preview, monkeypatch):
    g, repo, ev, events = pushing(preview, monkeypatch)
    result = g.do_push(ev, SESSION, str(repo))
    assert result["allow"] is True and result["outcome"] == "pushed"
    assert [e[0] for e in events] == ["audit", "push", "audit"]
    args, kwargs = events[1][1:]
    assert args == ("push", "--porcelain", "--no-follow-tags", "--no-signed", "--recurse-submodules=no", CANONICAL, ev["refspec"])
    assert "--no-verify" not in args and "--dry-run" not in args
    hooks = [p for p in kwargs["pins"] if p.lower().startswith("core.hookspath=")]
    assert hooks == [f"core.hooksPath={repo / '.githooks'}"]
    assert kwargs["pins"] == ev["pins"]
    assert kwargs["env_extra"] == {"TRADEAI_REMOTE_PUSH_AUTHORIZED": "1", "TRADEAI_GRANT_FREE": "1", "TRADEAI_GUARD_CONSUME": "0"}
    assert events[0][1]["event"] == "grant-free-push-intent" and events[0][1]["preview"] == ev["preview"]
    assert events[2][1]["outcome"] == "pushed" and events[2][1]["intent_hash"] == "synthetic-1"


@pytest.mark.parametrize("rc,stdout,outcome", [(1, "", "failed"), (0, "!\twrong:refs/heads/other\trefused\n", "unexpected-result")])
def test_actual_push_failure_is_never_reported_as_transport_success(preview, monkeypatch, rc, stdout, outcome):
    g, repo, ev, events = pushing(preview, monkeypatch, rc=rc, stdout=stdout)
    out = g.do_push(ev, SESSION, str(repo))
    assert out["allow"] is False and out["outcome"] == outcome and out["rc"] == rc
    assert events[-1][1]["outcome"] == outcome


@pytest.mark.parametrize("cause", ["intent", "revocation"])
def test_actual_push_cannot_mutate_after_failed_intent_or_revocation(preview, monkeypatch, cause):
    g, repo, ev, events = pushing(preview, monkeypatch, intent_error=cause == "intent", revoked=cause == "revocation")
    with pytest.raises(g.Refused, match="intent failure|revoked before push"):
        g.do_push(ev, SESSION, str(repo))
    assert len(events) == 1 and events[0][1]["event"] == "grant-free-push-intent"


@pytest.mark.parametrize("rc", [0, 1])
def test_actual_push_outcome_reports_result_without_preflight_nonexecution_claims(preview, monkeypatch, rc):
    g, repo, ev, events = pushing(preview, monkeypatch, rc=rc)
    out = g.do_push(ev, SESSION, str(repo))
    intent, outcome = events[0][1], events[-1][1]
    assert intent["preview"] == ev["preview"] and intent["dry_run"] == ev["dry_run"]
    assert intent["preview"]["remote_write_attempted"] is False
    assert outcome["event"] == "grant-free-push" and outcome["rc"] == rc
    assert outcome["result"] == out["result"]
    assert outcome["outcome"] == ("pushed" if rc == 0 else "failed")
    assert bool(outcome["result"]) is (rc == 0)
    for key in ("preview", "dry_run", "transport_checked", "pre_push_executed", "remote_write_attempted"):
        assert key not in outcome

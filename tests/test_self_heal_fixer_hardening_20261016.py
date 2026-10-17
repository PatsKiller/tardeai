"""Architect review of the self-heal Claude fixer (#1830, main 26fd0518), 2026-10-16: negative tests per finding.

1. Patch/commit mismatch: acceptance is bound to ONE immutable candidate commit (sha + tree); every harness test run
   happens in a fresh checkout of it whose files and .git are digested before and after; the diff guard is re-run on
   the commit's tree right before the branch update / push; the PR head must equal the evaluated commit.
2. Agent isolation: the Claude Code process itself runs in an allowlist bwrap sandbox (rw only on its worktree, a
   throwaway HOME and scratch state; one scoped auth bind; network only through an allowlist CONNECT proxy).
3. Durable claims: one flock per cycle, one sqlite claim per defect signature, the whole budget reserved before the
   backend starts, heartbeat leases, and restart reconciliation to ``fix_interrupted`` (never a blind restart).
4. Output recovered = the output contract on a live receipt (one swappable hook), never an mtime / JSON timestamp.

Hermetic: tmp git repos, stub CLIs (never a real model), tmp state roots, loopback-only sockets. The bwrap tests run
where bubblewrap works (the host) and skip on a runner without it.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_egress as EG  # noqa: E402
from lib import self_heal_fix_evaluator as E  # noqa: E402
from lib import self_heal_fixer as F  # noqa: E402
from lib import self_heal_fixer_claims as C  # noqa: E402
import self_heal_fixer as S  # noqa: E402
from tests import test_self_heal_fixer_20261016 as B  # noqa: E402

sandbox = B.sandbox  # the tmp origin/repo/stub-CLI fixture of the base suite
CFG, NOW = B.CFG, B.NOW


@pytest.fixture(autouse=True)
def _ci(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")


def _cfg_of(sb) -> dict:
    return json.loads(sb["cfg"].read_text())


def _write_cfg(sb, cfg: dict) -> None:
    sb["cfg"].write_text(json.dumps(cfg))


def _state(sb) -> dict:
    return json.loads((sb["state"] / CFG["state"]["state_rel"]).read_text())


def _calls(sb) -> list[dict]:
    p = sb["bin"] / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


#: A stub CLI driven by an actions file: ``actions.py`` in its own dir is exec'd with ``cwd`` = the worktree.
ACTION_CLAUDE = r'''#!{py}
import json, os, pathlib, sys
prompt = sys.stdin.read()
here = pathlib.Path(__file__).resolve().parent
calls = here / "calls.jsonl"
with calls.open("a") as fh:
    fh.write(json.dumps({{"cwd": os.getcwd(), "pid": os.getpid(), "ppid": os.getppid()}}) + "\n")
n = sum(1 for _ in calls.open())
cwd = pathlib.Path.cwd()
exec((here / "actions.py").read_text())
print(json.dumps({{"type": "result", "is_error": False, "total_cost_usd": 0.5, "num_turns": 1, "result": "ok"}}))
'''

REG = '    # self-heal regression for buggy\n    ("self_heal_buggy", ["tests/test_self_heal_buggy.py"]),\n'
FIX = 'def ratio(a, b):\n    return a / b if b else 0.0\n'


def _actions(sb, body: str) -> None:
    B._exe(sb["bin"] / "claude", ACTION_CLAUDE.format(py=sys.executable))
    (sb["bin"] / "actions.py").write_text(body)


def _fix_with_test(test_body: str) -> str:
    """actions.py source: write ``test_body`` as the regression test, fix buggy.py, register the test."""
    return (f"(cwd / 'tests' / 'test_self_heal_buggy.py').write_text({test_body!r})\n"
            f"(cwd / 'scripts' / 'buggy.py').write_text({FIX!r})\n"
            "p = cwd / 'scripts' / 'run_cio_hardening_ci.py'\n"
            f"p.write_text(p.read_text().replace('\\n]\\n', '\\n' + {REG!r} + ']\\n', 1))\n")


GOOD_TEST = "def test_ratio_handles_zero():\n    from scripts.buggy import ratio\n    assert ratio(1, 0) == 0.0\n"


def _cycle(sb, *, env=None, grant="self-heal-fixer test", gh=None):
    return S.main(["--cycle", "--apply", "--config", str(sb["cfg"]), "--incident", str(sb["incident"])],
                  now=lambda: NOW, environ=env or sb["env"],
                  grant_reader=lambda tier: {"reason": grant, "grant_id": "a" * 32} if grant else None,
                  gh=gh or (lambda cmd: {"rc": 1, "out": "", "err": "", "seconds": 0}))


def _bwrap_works() -> bool:
    return B._bwrap_works()


# ================================================================ finding 1: bind acceptance to an immutable commit


def test_acceptance_is_bound_to_one_immutable_candidate_commit(sandbox):
    _actions(sandbox, _fix_with_test(GOOD_TEST))
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_READY_LOCAL, job.get("reason")
    it = job["iterations"][0]
    acc = it["acceptance"]
    commit, tree = acc["commit_sha"], acc["tree_sha"]
    assert len(commit) == 40 and len(tree) == 40 and acc["checks"]["runs_bound_to_candidate"]
    # the branch points at EXACTLY the evaluated commit, whose tree is the evaluated tree
    repo = str(sandbox["repo"])
    assert B._sh("git", "-C", repo, "rev-parse", job["branch"]).strip() == commit == job["head_sha"]
    assert B._sh("git", "-C", repo, "rev-parse", f"{job['branch']}^{{tree}}").strip() == tree
    # every harness run is recorded with its own id, in a checkout of the candidate (red-first: of the base, with
    # the test overlaid from the commit object), and nothing in that checkout changed during the run
    runs = {r["kind"]: r for r in it["test_runs"]}
    assert set(runs) == {"red_first", "targeted", "ci"}
    assert runs["targeted"]["checkout_sha"] == runs["ci"]["checkout_sha"] == commit
    assert runs["red_first"]["checkout_sha"] == job["iterations"][0]["candidate"]["base_sha"]
    assert runs["red_first"]["overlay_from"] == commit
    assert all(r["integrity_ok"] and r["run_id"].startswith(r["kind"]) for r in runs.values())
    assert acc["test_run_ids"] == {k: r["run_id"] for k, r in runs.items()}
    assert acc["guard_verdict"] == {"tree_sha": tree, "clean": True, "codes": []}
    assert job["ship_check"]["accepted"] and job["ship_check"]["commit_sha"] == commit
    assert job["evaluated"]["commit_sha"] == commit and job["evaluated"]["tree_sha"] == tree


MUTATE_WORKTREE = (
    "def test_ratio_handles_zero():\n"
    "    import pathlib\n"
    "    root = pathlib.Path(__file__).resolve().parents[1]\n"
    "    try:\n"
    "        (root / 'scripts' / 'planted.py').write_text('x = 1\\n')\n"
    "    except OSError:\n"
    "        pass\n"
    "    from scripts.buggy import ratio\n"
    "    assert ratio(1, 0) == 0.0\n")

MUTATE_GIT = (
    "def test_ratio_handles_zero():\n"
    "    import pathlib\n"
    "    root = pathlib.Path(__file__).resolve().parents[1]\n"
    "    try:\n"
    "        with (root / '.git' / 'config').open('a') as fh:\n"
    "            fh.write('[core]\\n\\thooksPath = /tmp/planted-hooks\\n')\n"
    "    except OSError:\n"
    "        pass\n"
    "    from scripts.buggy import ratio\n"
    "    assert ratio(1, 0) == 0.0\n")


@pytest.mark.parametrize("test_body", [MUTATE_WORKTREE, MUTATE_GIT], ids=["worktree", "git_admin"])
def test_a_test_that_mutates_its_checkout_or_git_is_refused(sandbox, test_body):
    """bwrap off (the CI runner): the write lands, and the before/after digest refuses the job."""
    _actions(sandbox, _fix_with_test(test_body))
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_REFUSED and job["reason"] == "guard_refused"
    it = job["iterations"][0]
    assert "guard:integrity:checkout_or_git_mutated" in it["failing"]
    assert not it["acceptance"]["accepted"] and not it["acceptance"]["checks"]["runs_bound_to_candidate"]
    assert any(r["integrity_ok"] is False for r in it["test_runs"])
    assert job["branch"] not in B._sh("git", "-C", str(sandbox["repo"]), "branch", "--list")
    assert not (sandbox["bin"] / "gh_calls.txt").exists()


@pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap unavailable on this runner (host-only proof)")
def test_sandboxed_harness_runs_cannot_write_the_checkout_or_git(sandbox):
    """bwrap on: the evaluation checkout and its .git are read-only to the tests (the write itself fails)."""
    cfg = _cfg_of(sandbox)
    cfg["sandbox"]["enabled"] = True
    _write_cfg(sandbox, cfg)
    must_fail = ("def test_ratio_handles_zero():\n"
                 "    import pathlib, pytest\n"
                 "    root = pathlib.Path(__file__).resolve().parents[1]\n"
                 "    with pytest.raises(OSError):\n"
                 "        (root / 'scripts' / 'planted.py').write_text('x')\n"
                 "    with pytest.raises(OSError):\n"
                 "        (root / '.git' / 'config').open('a').write('x')\n"
                 "    from scripts.buggy import ratio\n"
                 "    assert ratio(1, 0) == 0.0\n")
    _actions(sandbox, _fix_with_test(must_fail))
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_READY_LOCAL, job["iterations"][-1].get("failing")
    assert all(r["integrity_ok"] for r in job["iterations"][0]["test_runs"])


def test_pr_head_not_the_evaluated_commit_is_refused(sandbox):
    _actions(sandbox, _fix_with_test(GOOD_TEST))
    (sandbox["bin"] / "gh_head_override").write_text("f" * 40)  # the PR head moved after the push
    marker = CFG["policy_gate"]["amendment_heading_marker"]
    p = sandbox["repo"] / "AGENTS.md"
    p.write_text(p.read_text() + f"\n{marker} (13.0.0, ACTIVE)\n")
    B._sh("git", "-C", str(sandbox["repo"]), "commit", "-qam", "amend")
    B._sh("git", "-C", str(sandbox["repo"]), "push", "-q", "origin", "main")
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_REFUSED and job["reason"].startswith("pr_head_mismatch:ffffffffffff!=")
    assert job["pr_number"] == 4242 and job["pr_head"] == "f" * 40
    assert not F.is_healed(job)
    # what WAS pushed is the evaluated commit itself (pushed by sha, not by branch name)
    pushed = B._sh("git", "-C", str(sandbox["origin"]), "rev-parse", job["branch"]).strip()
    assert pushed == job["evaluated"]["commit_sha"]


def test_prepush_guard_rerun_on_the_commit_tree_refuses(sandbox, monkeypatch):
    """The diff guard is re-run on the commit's tree immediately before the branch update / push: if it refuses
    then (here: the guard changed its mind), nothing ships."""
    _actions(sandbox, _fix_with_test(GOOD_TEST))
    real = S.Attempt.guard
    calls = {"n": 0}

    def guard(self, d):
        calls["n"] += 1
        out = real(self, d)
        return out if calls["n"] == 1 else out + [{"hard": True, "code": "protected_path", "path": "x"}]

    monkeypatch.setattr(S.Attempt, "guard", guard)
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert calls["n"] == 2  # once on the candidate, once right before shipping
    assert job["state"] == F.FIX_REFUSED and job["reason"] == "ship_check_failed:prepush_guard_clean"
    assert "head_sha" not in job
    assert job["branch"] not in B._sh("git", "-C", str(sandbox["repo"]), "branch", "--list")


def test_ship_verdict_refuses_any_mismatch():
    local = E.local_verdict({"tests_run": ["tests/t.py"], "red_first": True, "targeted_rc": 0, "ci_rc": 0,
                             "refusals": [], **B.bound_facts(commit="c" * 40, tree="d" * 40)})
    assert local["accepted"]
    ok = E.ship_verdict(local, commit_sha="c" * 40, tree_sha="d" * 40, prepush_refusals=[])
    assert ok["accepted"]
    assert E.ship_verdict(local, commit_sha="e" * 40, tree_sha="d" * 40, prepush_refusals=[])["failed"] == \
        ["commit_is_evaluated"]
    assert E.ship_verdict(local, commit_sha="c" * 40, tree_sha="0" * 40, prepush_refusals=[])["failed"] == \
        ["tree_is_evaluated"]
    assert not E.ship_verdict(local, commit_sha="c" * 40, tree_sha="d" * 40,
                              prepush_refusals=[{"code": "protected_path"}])["accepted"]
    assert not E.ship_verdict(dict(local, accepted=False), commit_sha="c" * 40, tree_sha="d" * 40,
                              prepush_refusals=[])["accepted"]


@pytest.mark.parametrize("mutate,why", [
    (lambda f: f["test_runs"][1].update(checkout_sha="9" * 40), "targeted:not_bound_to_candidate"),
    (lambda f: f["test_runs"][1].update(head_after="9" * 40), "targeted:not_bound_to_candidate"),
    (lambda f: f["test_runs"][2].update(integrity_ok=False), "ci:checkout_or_git_mutated"),
    (lambda f: f["test_runs"].pop(), "ci:missing"),
    (lambda f: f["test_runs"][0].update(overlay_from="9" * 40), "red_first:overlay_not_from_candidate"),
    (lambda f: f["guard"].update(tree_sha="9" * 40), None),
])
def test_local_verdict_refuses_runs_not_bound_to_the_candidate(mutate, why):
    facts = B.bound_facts()
    mutate(facts)
    v = E.local_verdict({"tests_run": ["tests/t.py"], "red_first": True, "targeted_rc": 0, "ci_rc": 0,
                         "refusals": [], **facts})
    assert not v["accepted"]
    if why:
        assert why in v["unbound"]
    else:
        assert v["failed"] == ["guard_judged_candidate_tree"]


def test_checkout_digest_sees_worktree_and_git_writes(tmp_path):
    B._sh("git", "init", "-q", str(tmp_path / "r"))
    r = tmp_path / "r"
    (r / "a.py").write_text("x = 1\n")
    d0 = S.checkout_digest(r)
    (r / ".git" / "index").write_bytes(b"stat cache only")  # excluded: a stat-cache refresh is not a mutation
    assert S.checkout_digest(r) == d0
    (r / ".git" / "config").write_text((r / ".git" / "config").read_text() + "[core]\n\thooksPath = /x\n")
    d1 = S.checkout_digest(r)
    assert d1 != d0
    (r / "b.py").write_text("")
    assert S.checkout_digest(r) != d1


# ================================================================ finding 2: the agent's own boundary


def _fake_probe(kinds: dict):
    return lambda p: kinds.get(p)


def test_agent_sandbox_is_an_allowlist_rw_only_on_its_worktree():
    cfg = json.loads(json.dumps(CFG))
    kinds = {"/usr": "dir", "/bin": "link:usr/bin", "/etc": "dir", "/lib": "link:usr/lib", "/r/.git": "dir",
             "/r/.venv": "dir", "/opt/claude": "file", "/w/bin": "dir", "/w/eg": "dir",
             "/h/.claude/.credentials.json": "file"}
    probe = _fake_probe(kinds)
    binds, why = F.agent_auth_binds(cfg, home="/h", agent_home="/w/home", probe=probe)
    assert why == "auth:credentials_file"
    assert binds == [("/h/.claude/.credentials.json", "/w/home/.claude/.credentials.json", True)]
    env = F.agent_env({"HOME": "/h", "PATH": "/x", "USER": "u", "DB_PASSWORD": "p"}, cfg, scratch_state="/w/st",
                      agent_home="/w/home", proxy_port=18977)
    argv = F.agent_sandbox_prefix(cfg, home="/h", repo_root="/r", python_root="/r/.venv",
                                  extra_ro=["/opt/claude", "/w/bin", "/w/eg"], fix_wt="/w/wt", agent_home="/w/home",
                                  scratch="/w/st", auth_binds=binds, env=env, probe=probe)
    joined = " ".join(argv)
    assert argv[0] == cfg["agent_sandbox"]["bwrap"]
    for flag in ("--unshare-net", "--unshare-pid", "--new-session", "--clearenv", "--die-with-parent"):
        assert flag in argv
    assert "--ro-bind / /" not in joined  # NOT the host view: an empty root
    pairs = [(argv[i], argv[i + 1], argv[i + 2]) for i in range(len(argv) - 2) if argv[i] in ("--bind", "--ro-bind")]
    rw = [(s, d) for f, s, d in pairs if f == "--bind"]
    assert rw == [("/w/wt", "/w/wt"), ("/w/home", "/w/home"), ("/w/st", "/w/st"),
                  ("/h/.claude/.credentials.json", "/w/home/.claude/.credentials.json")]
    ro = {s for f, s, d in pairs if f == "--ro-bind"}
    assert {"/usr", "/etc", "/r/.git", "/r/.venv", "/opt/claude", "/w/bin", "/w/eg"} <= ro
    assert "/r" not in ro and "/h" not in ro and not any(s.startswith("/h/") for s in ro)  # no repo tree, no $HOME
    assert ["--symlink", "usr/bin", "/bin"] == argv[argv.index("/bin") - 2:argv.index("/bin") + 1]
    assert argv[-2:] == ["--chdir", "/w/wt"]
    # the env inside: throwaway HOME, the scoped config dir, the bridge proxy; nothing credential-shaped
    setenv = {argv[i + 1]: argv[i + 2] for i in range(len(argv) - 2) if argv[i] == "--setenv"}
    assert setenv["HOME"] == "/w/home" and setenv["CLAUDE_CONFIG_DIR"] == "/w/home/.claude"
    assert setenv["HTTPS_PROXY"] == "http://127.0.0.1:18977" and setenv["TRADE_AI_CI"] == "1"
    assert "DB_PASSWORD" not in setenv and "USER" not in setenv
    assert F.agent_sandbox_prefix(B._cfg(agent_sandbox={"enabled": False}), home="/h", repo_root="/r",
                                  python_root="/v", extra_ro=[], fix_wt="/w", agent_home="/a", scratch="/s",
                                  auth_binds=[], env={}, probe=probe) == []


def test_auth_bind_is_scoped_or_refused():
    probe = _fake_probe({})
    assert F.agent_auth_binds(CFG, home="/h", agent_home="/a", probe=probe) == ([], "auth_credentials_file_missing")
    assert F.agent_auth_binds(B._cfg(claude={"auth": {"mode": "none"}}), home="/h", agent_home="/a",
                              probe=probe) == ([], "auth:none")
    assert F.agent_auth_binds(B._cfg(claude={"auth": {"mode": "whole_dir"}}), home="/h", agent_home="/a",
                              probe=probe)[1] == "auth_mode_unknown:whole_dir"


def test_model_pytest_wrapper_clears_the_agent_env():
    w = F.model_pytest_wrapper(python="/v/bin/python", env={"HOME": "/s", "TRADE_AI_CI": "1"}, sandbox=[])
    assert w.startswith("#!/bin/sh\nexec /usr/bin/env -i HOME=/s TRADE_AI_CI=1 /v/bin/python -m pytest")
    assert "HTTPS_PROXY" not in w and "CLAUDE_CONFIG_DIR" not in w


def test_eval_sandbox_binds_the_checkout_read_only():
    kinds = {"/usr": "dir", "/r/.git": "dir", "/v": "dir", "/w/eval/c": "dir"}
    argv = F.eval_sandbox_prefix(B._cfg(sandbox={"enabled": True}), repo_root="/r", python_root="/v",
                                 checkout="/w/eval/c", scratch="/w/st", env={"HOME": "/w/st"},
                                 probe=_fake_probe(kinds))
    pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1) if argv[i] in ("--bind", "--ro-bind")]
    assert ("--ro-bind", "/w/eval/c") in pairs and ("--ro-bind", "/r/.git") in pairs
    assert [s for f, s in pairs if f == "--bind"] == ["/w/st"] and "--unshare-net" in argv


def test_agent_never_runs_unsandboxed_outside_hermetic_tests(sandbox):
    """agent_sandbox.enabled false is honoured only with TRADE_AI_CI=1; otherwise the job fails before any model."""
    _actions(sandbox, _fix_with_test(GOOD_TEST))
    env = {k: v for k, v in sandbox["env"].items() if k != "TRADE_AI_CI"}
    assert _cycle(sandbox, env=env) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_FAILED and job["reason"] == "agent_sandbox_disabled"
    assert _calls(sandbox) == []


def test_secret_shaped_literals_in_a_diff_are_hard_refusals():
    cfg = CFG
    added = "+TOKEN = 'sk-ant-oat01-abcdefghijklmnop'\n"
    u0 = f"diff --git a/scripts/x.py b/scripts/x.py\n--- a/scripts/x.py\n+++ b/scripts/x.py\n@@ -1,0 +1,1 @@\n{added}"
    r = F.guard_diff(name_status="M\tscripts/x.py\nA\ttests/test_x.py\n", numstat="1\t0\tscripts/x.py\n",
                     unified=u0, base_ci_text="", cfg=cfg)
    assert {"hard": True, "code": "secret_in_diff", "path": "scripts/x.py", "prefix": "sk-a..."} in r
    assert F.secret_like("x = 'Zm9vYmFyQmF6UXV4MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3BxcnN0'") is not None
    assert F.secret_like('"accessToken": "x"') is not None
    # not secrets: sha256 hex, long snake_case identifiers, ordinary code
    assert F.secret_like("h = '" + "ab12" * 16 + "'") is None
    assert F.secret_like("def test_n8n_self_heal_tranche_defects_are_all_fixed_20261016():") is None
    assert F.secret_like("assert ratio(1, 0) == 0.0") is None


# ---- the egress proxy + bridge (no bwrap needed)


def _echo_server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            data = c.recv(1024)
            c.sendall(b"echo:" + data)
            c.close()

    threading.Thread(target=loop, daemon=True).start()
    return srv, srv.getsockname()[1]


def _connect_via(sock_path: str, target: str) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(sock_path)
    s.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    head = s.recv(1024)
    if b" 200 " in head:
        s.sendall(b"ping")
        head += b"|" + s.recv(1024)
    s.close()
    return head


def test_egress_proxy_allows_only_listed_connect_targets(tmp_path):
    srv, port = _echo_server()
    sock = str(tmp_path / "s")
    with EG.EgressProxy(sock, [f"127.0.0.1:{port}"]) as px:
        assert _connect_via(sock, f"127.0.0.1:{port}").endswith(b"|echo:ping")
        assert b" 403 " in _connect_via(sock, "evil.example:443")
        assert b" 403 " in _connect_via(sock, f"127.0.0.1:{port + 1}")  # same host, other port
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock)
        s.sendall(b"GET http://127.0.0.1/ HTTP/1.1\r\n\r\n")  # plain HTTP is never proxied
        assert b" 403 " in s.recv(1024)
        s.close()
        summ = px.summary()
    srv.close()
    assert summ["allowed"] == {f"127.0.0.1:{port}": 1} and "evil.example:443" in summ["denied"]
    assert EG.parse_connect(b"CONNECT api.anthropic.com:443 HTTP/1.1\r\n\r\n") == ("api.anthropic.com", 443)
    assert EG.parse_connect(b"CONNECT api.anthropic.com HTTP/1.1\r\n\r\n") is None


def test_bridge_forwards_tcp_to_the_proxy_socket_and_returns_the_child_rc(tmp_path):
    srv, port = _echo_server()
    sock = str(tmp_path / "s")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        bport = probe.getsockname()[1]
    child = ("import socket,sys\n"
             f"s=socket.create_connection(('127.0.0.1',{bport}),timeout=5)\n"
             f"s.sendall(b'CONNECT 127.0.0.1:{port} HTTP/1.1\\r\\n\\r\\n')\n"
             "h=s.recv(1024)\n"
             "s.sendall(b'hi'); d=s.recv(1024)\n"
             "sys.exit(0 if b' 200 ' in h and d==b'echo:hi' else 3)\n")
    with EG.EgressProxy(sock, [f"127.0.0.1:{port}"]):
        p = subprocess.run([sys.executable, "-I", EG.__file__, "bridge", "--unix", sock, "--port", str(bport), "--",
                            sys.executable, "-c", f"import time; time.sleep(0.3)\n{child}"], timeout=30)
    srv.close()
    assert p.returncode == 0


# ---- the boundary itself, with a stub CLI inside bwrap

PROBE_CLAUDE = r'''#!{py}
import json, os, pathlib, socket, subprocess, sys
sys.stdin.read()
P = json.loads({paths!r})
out = {{}}
def can_read(p):
    try:
        pathlib.Path(p).read_bytes(); return True
    except OSError:
        return False
def can_write(p):
    try:
        pathlib.Path(p).write_text("planted"); return True
    except OSError:
        return False
out["read_repo_env"] = can_read(P["repo_env"])
out["read_home_env"] = can_read(P["home_env"])
out["read_ssh"] = can_read(P["ssh"])
out["read_claude_history"] = can_read(P["claude_history"])
out["read_releases"] = can_read(P["releases"])
out["home_listing"] = os.path.isdir(P["home"])
out["auth_visible"] = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"], ".credentials.json").read_text() == "FAKE-CRED"
out["write_repo_tree"] = can_write(P["repo_plant"])
out["write_repo_git"] = can_write(P["git_plant"])
out["write_home"] = can_write(P["home_plant"])
out["write_outside"] = can_write(P["outside_plant"])
out["write_worktree"] = can_write(os.path.join(os.getcwd(), "agent_note.txt"))
try:
    socket.create_connection(("127.0.0.1", P["host_port"]), timeout=2).close(); out["direct_host_port"] = True
except OSError:
    out["direct_host_port"] = False
def via_proxy(target):
    try:
        s = socket.create_connection(("127.0.0.1", int(os.environ["HTTPS_PROXY"].rsplit(":", 1)[1])), timeout=5)
        s.sendall(("CONNECT %s HTTP/1.1\r\n\r\n" % target).encode()); h = s.recv(1024)
        if b" 200 " in h:
            s.sendall(b"x"); h += s.recv(1024)
        s.close(); return h.decode("latin-1")
    except OSError as exc:
        return "error:" + type(exc).__name__
out["proxy_allowed"] = via_proxy("127.0.0.1:%d" % P["host_port"])
out["proxy_denied"] = via_proxy("api.evil.example:443")
pyt = next(a for a in sys.argv if "/pytest:" in a).split("Bash(", 1)[1].split(":", 1)[0]
t = pathlib.Path(os.getcwd(), "tests", "test_probe_env.py")
t.write_text("import os\ndef test_env():\n    assert 'HTTPS_PROXY' not in os.environ and 'CLAUDE_CONFIG_DIR' not in os.environ\n")
r = subprocess.run([pyt, "-q", str(t)], capture_output=True, text=True, timeout=120)
out["model_pytest_rc"] = r.returncode
t.unlink()
os.unlink(os.path.join(os.getcwd(), "agent_note.txt"))
print(json.dumps({{"type": "result", "is_error": False, "total_cost_usd": 0.0, "result": json.dumps(out)}}))
'''


@pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap unavailable on this runner (host-only proof)")
def test_agent_in_its_sandbox_cannot_read_env_or_write_outside_its_worktree(sandbox):
    tmp = sandbox["tmp"]
    home = tmp / "home"
    for d in (home / ".ssh", home / ".claude", home / "trade-ai-releases", tmp / "outside"):
        d.mkdir(parents=True)
    (home / ".env").write_text("DB_PASSWORD=hunter2\n")
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE\n")
    (home / ".claude" / "history.jsonl").write_text("{}\n")
    (home / ".claude" / ".credentials.json").write_text("FAKE-CRED")
    (home / "trade-ai-releases" / "GIT_SHA").write_text("x\n")
    (sandbox["repo"] / ".env").write_text("SCHWAB_SECRET=x\n")  # untracked, in the operator's working tree
    srv, port = _echo_server()
    paths = {"repo_env": str(sandbox["repo"] / ".env"), "home_env": str(home / ".env"),
             "ssh": str(home / ".ssh" / "id_ed25519"), "claude_history": str(home / ".claude" / "history.jsonl"),
             "releases": str(home / "trade-ai-releases" / "GIT_SHA"), "home": str(home),
             "repo_plant": str(sandbox["repo"] / "scripts" / "planted.py"),
             "git_plant": str(sandbox["repo"] / ".git" / "planted"), "home_plant": str(home / "planted"),
             "outside_plant": str(tmp / "outside" / "planted"), "host_port": port}
    B._exe(sandbox["bin"] / "claude", PROBE_CLAUDE.format(py=sys.executable, paths=json.dumps(paths)))
    cfg = _cfg_of(sandbox)
    cfg["agent_sandbox"].update(enabled=True, egress_allow=[f"127.0.0.1:{port}"], proxy_port=18977)
    cfg["claude"]["auth"] = {"mode": "credentials_file", "credentials_file": "{home}/.claude/.credentials.json",
                             "rw": False}
    cfg["iteration"]["max_iterations"] = 1
    _write_cfg(sandbox, cfg)
    env = dict(sandbox["env"], HOME=str(home))
    assert _cycle(sandbox, env=env) == 0
    srv.close()
    (job,) = _state(sandbox)["jobs"].values()
    assert job["boundary"]["agent_sandbox"] is True and job["boundary"]["auth"] == "auth:credentials_file"
    ev = sandbox["state"] / CFG["state"]["evidence_rel"] / job["job_id"]
    res = json.loads((ev / "backend_iter1.json").read_text())
    probes = json.loads(res["result"])
    assert probes == {
        "read_repo_env": False, "read_home_env": False, "read_ssh": False, "read_claude_history": False,
        "read_releases": False, "home_listing": False, "auth_visible": True,
        "write_repo_tree": False, "write_repo_git": False, "write_home": False, "write_outside": False,
        "write_worktree": True, "direct_host_port": False,
        "proxy_allowed": probes["proxy_allowed"], "proxy_denied": probes["proxy_denied"], "model_pytest_rc": 0,
    }, probes
    assert " 200 " in probes["proxy_allowed"] and probes["proxy_allowed"].endswith("echo:x")
    assert " 403 " in probes["proxy_denied"]
    assert res["egress"]["denied"] == {"api.evil.example:443": 1}
    for p in ("repo_plant", "git_plant", "home_plant", "outside_plant"):
        assert not Path(paths[p]).exists(), p
    assert (home / ".claude" / ".credentials.json").read_text() == "FAKE-CRED"  # untouched, never copied


# ================================================================ finding 3: durable claims, leases, budget


def _claim(db, key="lane|sig", job="j1", **kw):
    args = dict(dedupe_key=key, job_id=job, day="2026-10-16", reserve_iterations=4, reserve_usd=12.0,
                reserve_seconds=5400, lease_ttl_s=300, daily_job_cap=3, daily_usd_cap=24.0)
    args.update(kw)
    return C.claim(db, **args)


def test_one_active_claim_per_signature(tmp_path):
    db = tmp_path / "c.sqlite"
    cid, why = _claim(db)
    assert cid and why == "claimed"
    assert _claim(db, job="j2") == (None, "claimed_elsewhere:j1")
    assert C.settle(db, cid, outcome="fix_failed", spent_usd=1.5, iterations_done=2)
    assert _claim(db, job="j3")[0]  # released: the next attempt may claim
    assert not C.settle(db, cid, outcome="x", spent_usd=0, iterations_done=0)  # settle is once


def test_concurrent_claims_on_one_signature_exactly_one_wins(tmp_path):
    db = tmp_path / "c.sqlite"
    C.rows(db)  # schema
    with C.connect(db):
        pass
    results, barrier = [], threading.Barrier(8)

    def go(i):
        barrier.wait()
        results.append(_claim(db, job=f"j{i}", daily_job_cap=99, daily_usd_cap=999))

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(1 for cid, _ in results if cid) == 1
    assert len([r for r in C.rows(db) if r["state"] == C.ACTIVE]) == 1


def test_budget_is_reserved_before_launch_and_caps_bind_on_reservations(tmp_path):
    db = tmp_path / "c.sqlite"
    a, _ = _claim(db, key="a")
    b, _ = _claim(db, key="b")
    # 12 + 12 reserved = the 24 cap: a third job is refused BEFORE anything runs, though nothing was spent yet
    assert _claim(db, key="c") == (None, "daily_usd_cap:24.00+12.00>24.00")
    C.settle(db, a, outcome="fix_ready_local", spent_usd=2.0, iterations_done=1)
    assert C.day_usage(db, "2026-10-16")["usd"] == 14.0  # settled counts actual spend, active counts reservation
    assert _claim(db, key="c", reserve_usd=12.0) == (None, "daily_usd_cap:14.00+12.00>24.00")
    assert _claim(db, key="c", reserve_usd=10.0)[0]
    assert _claim(db, key="d", reserve_usd=0.0) == (None, "daily_job_cap:3/3")


def test_reconcile_marks_expired_or_dead_owners_interrupted_once(tmp_path):
    db = tmp_path / "c.sqlite"
    t0 = 1_000_000.0
    live, _ = _claim(db, key="live", now_ts=t0, pid=os.getpid())
    stale, _ = _claim(db, key="stale", now_ts=t0, pid=os.getpid())
    C.record_progress(db, stale, iterations_done=1, spent_usd=0.5, partial={"iteration": 1, "patch": "/e/p"})
    C.heartbeat(db, live, lease_ttl_s=300, now_ts=t0 + 290)
    got = C.reconcile(db, now_ts=t0 + 301, alive=lambda pid: True)
    assert [g["claim_id"] for g in got] == [stale] and got[0]["why"] == "lease_expired"
    assert got[0]["partial"] == {"iteration": 1, "patch": "/e/p"} and got[0]["iterations_done"] == 1
    assert C.reconcile(db, now_ts=t0 + 302, alive=lambda pid: True) == []  # idempotent
    # an owner pid that is gone on this host is dead even before its lease expires
    dead, _ = _claim(db, key="dead", now_ts=t0 + 302, pid=999_999_999, daily_usd_cap=999)
    got = C.reconcile(db, now_ts=t0 + 303, alive=lambda pid: pid != 999_999_999)
    assert [g["claim_id"] for g in got] == [dead] and got[0]["why"] == "owner_pid_dead"
    u = C.day_usage(db, "2026-10-16")
    assert u["interrupted"] == 2 and u["usd"] == 36.0  # each reservation counted exactly once


def test_cycle_lock_lets_exactly_one_cycle_run(tmp_path):
    a, b = C.CycleLock(tmp_path / "l"), C.CycleLock(tmp_path / "l")
    assert a.acquire() and not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


DRIVER = r'''
import json, sys
from datetime import datetime, timezone
sys.path.insert(0, {scripts!r})
import self_heal_fixer as S
env = json.loads(sys.argv[1])
rc = S.main(["--cycle", "--apply", "--config", sys.argv[2], "--incident", sys.argv[3]],
            now=lambda: datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc), environ=env,
            grant_reader=lambda tier: {{"reason": "self-heal-fixer test", "grant_id": "a" * 32}},
            gh=lambda cmd: {{"rc": 1, "out": "", "err": "", "seconds": 0}})
sys.exit(rc)
'''


def _driver(sb) -> list[str]:
    path = sb["tmp"] / "driver.py"
    path.write_text(DRIVER.format(scripts=str(ROOT / "scripts")))
    return [sys.executable, str(path), json.dumps(sb["env"]), str(sb["cfg"]), str(sb["incident"])]


def test_concurrent_invocations_exactly_one_runs(sandbox):
    """A live cycle holds the lock while its backend runs; a second invocation exits busy and runs nothing."""
    gate = sandbox["bin"] / "release"
    _actions(sandbox, f"import time, pathlib\n(here / 'started').touch()\n"
                      f"t = time.time()\nwhile not pathlib.Path({str(gate)!r}).exists() and time.time() - t < 60:\n"
                      f"    time.sleep(0.05)\n" + _fix_with_test(GOOD_TEST))
    a = subprocess.Popen(_driver(sandbox), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        t = time.time()
        while not (sandbox["bin"] / "started").exists() and time.time() - t < 60:
            time.sleep(0.05)
        assert (sandbox["bin"] / "started").exists(), a.stderr.read() if a.poll() is not None else "no start"
        out_b = subprocess.run(_driver(sandbox), capture_output=True, text=True, timeout=120)
        assert out_b.returncode == 0 and json.loads(out_b.stdout)["busy"] is True
    finally:
        gate.touch()
        a.wait(timeout=180)
    assert a.returncode == 0, a.stderr.read()
    assert len(_calls(sandbox)) == 1
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_READY_LOCAL
    rows = C.rows(sandbox["state"] / CFG["state"]["claims_rel"])
    assert [(r["job_id"], r["state"]) for r in rows] == [(job["job_id"], C.SETTLED)]


def test_crash_mid_attempt_is_reconciled_once_and_not_restarted(sandbox):
    """Iteration 1 completes (partial evidence recorded durably), then the fixer process is SIGKILLed during
    iteration 2. The next start marks the attempt fix_interrupted with that evidence; no backend call; the budget
    reservation is counted exactly once, however many times the fixer restarts."""
    noprogress = ("(cwd / 'tests' / 'test_self_heal_buggy.py').write_text(" + repr(GOOD_TEST) + ")\n"
                  "p = cwd / 'scripts' / 'run_cio_hardening_ci.py'\n"
                  f"p.write_text(p.read_text().replace('\\n]\\n', '\\n' + {REG!r} + ']\\n', 1))\n")
    _actions(sandbox, "import os, signal\nif n >= 2:\n    os.kill(os.getppid(), signal.SIGKILL)\n"
                      "    raise SystemExit(0)\n" + noprogress)
    p = subprocess.run(_driver(sandbox), capture_output=True, text=True, timeout=300)
    assert p.returncode == -signal.SIGKILL
    db = sandbox["state"] / CFG["state"]["claims_rel"]
    (row,) = C.rows(db)
    assert row["state"] == C.ACTIVE and row["iterations_done"] == 1  # durable before the crash
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_ATTEMPTING and len(job["iterations"]) == 1  # persisted after iteration 1
    assert len(_calls(sandbox)) == 2
    # restart: reconciled, not restarted
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_INTERRUPTED and job["reason"] == "interrupted:owner_pid_dead"
    intr = job["interrupted"]
    assert intr["iterations_done"] == 1 and intr["partial"]["iteration"] == 1
    assert intr["partial"]["candidate"]["commit_sha"] == job["iterations"][0]["candidate"]["commit_sha"]
    assert Path(intr["evidence_dir"], "prompt_iter1.md").exists()
    assert len(_calls(sandbox)) == 2  # no backend call on restart
    esc = [json.loads(x) for x in (sandbox["state"] / CFG["state"]["escalations_rel"]).read_text().splitlines()]
    assert [e["state"] for e in esc] == [F.FIX_INTERRUPTED]
    u1 = C.day_usage(db, F.et_day(NOW))
    assert u1 == {"day": F.et_day(NOW), "jobs": 1, "usd": CFG["iteration"]["max_cost_usd"], "active": 0,
                  "interrupted": 1}
    # and again: idempotent, nothing double-counted, still no restart; cooldown keeps the signature parked
    assert _cycle(sandbox) == 0
    assert C.day_usage(db, F.et_day(NOW)) == u1 and len(_calls(sandbox)) == 2
    rcpt = json.loads((sandbox["state"] / CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["reconciled"] == [] and rcpt["budget_today"] == u1


def test_claim_refusal_runs_no_backend(sandbox):
    """A live claim on the signature (another host's owner, lease fresh) blocks the attempt before the backend."""
    _actions(sandbox, _fix_with_test(GOOD_TEST))
    db = sandbox["state"] / CFG["state"]["claims_rel"]
    defect = json.loads(sandbox["incident"].read_text())["code_defect"]
    inc = F.defect_to_incident(defect)
    key = F.dedupe_key(inc["lane"], inc["signature"])
    with C.connect(db):
        pass
    cid, _ = _claim(db, key=key, job="elsewhere", day=F.et_day(NOW))
    with C.connect(db) as con:  # owned by another host: only its lease can expire it
        con.execute("UPDATE claims SET owner_host='other-host', lease_expires_at=? WHERE claim_id=?",
                    (time.time() + 600, cid))
    assert _cycle(sandbox) == 0
    (job,) = _state(sandbox)["jobs"].values()
    assert job["state"] == F.FIX_REQUESTED and _calls(sandbox) == []
    rcpt = json.loads((sandbox["state"] / CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["attempted"][0]["outcome"] == "not_claimed:claimed_elsewhere:elsewhere"


# ================================================================ finding 4: output recovered = the output contract


SINCE = NOW


@pytest.mark.parametrize("over,why", [
    ({}, None),
    ({"verdict": "empty_allowed"}, None),
    ({"finished": SINCE - timedelta(minutes=1)}, "not_after_since"),
    ({"state": "RUN_FAILED"}, "not_run_done"),
    ({"exit_code": 1}, "nonzero_or_unknown_exit"),
    ({"mode": "dry_run"}, "effective_mode_not_live"),
    ({"clamp": "dry_run"}, "effective_mode_not_live"),
    ({"verdict": "empty_violation"}, "output_verdict:empty_violation"),
    ({"verdict": "declared_not_enforced"}, "output_verdict:declared_not_enforced"),
    ({"verdict": None}, "output_verdict:absent"),
])
def test_receipt_meets_output_contract(over, why):
    a = dict(finished=SINCE + timedelta(hours=1), state="RUN_DONE", mode="live", exit_code=0, verdict="produced",
             clamp="live")
    a.update(over)
    rec = {"mode": a["mode"], "state": a["state"], "exit_code": a["exit_code"],
           "finished_at": a["finished"].isoformat(), "stage_clamp": {"effective_mode": a["clamp"]}}
    if a["verdict"]:
        rec["output_verdict"] = {"verdict": a["verdict"]}
    row = {"mode": a["mode"], "state": a["state"], "exit_code": a["exit_code"], "finished_at": rec["finished_at"],
           "receipt": rec}
    assert F.receipt_meets_output_contract(row, SINCE) == why


def test_output_recovered_reads_only_live_contract_receipts(tmp_path):
    cfg = CFG
    root = tmp_path
    contract = S.recovery_contract(cfg, root)
    assert S.output_recovered("lane-x", SINCE, contract)["why"] == "ledger_missing"
    B.ledger_row(root, cfg, "old", lane="lane-x", finished=SINCE - timedelta(hours=1))
    B.ledger_row(root, cfg, "dry", lane="lane-x", finished=SINCE + timedelta(hours=1), mode="dry_run", clamp=None)
    B.ledger_row(root, cfg, "clamped", lane="lane-x", finished=SINCE + timedelta(hours=1), clamp="dry_run")
    B.ledger_row(root, cfg, "empty", lane="lane-x", finished=SINCE + timedelta(hours=1), verdict="empty_violation")
    B.ledger_row(root, cfg, "other", lane="lane-y", finished=SINCE + timedelta(hours=1))
    no = S.output_recovered("lane-x", SINCE, contract)
    assert no["recovered"] is False and no["checked"] == 4
    assert no["reasons"] == {"not_after_since": 1, "effective_mode_not_live": 2, "output_verdict:empty_violation": 1}
    B.ledger_row(root, cfg, "good", lane="lane-x", finished=SINCE + timedelta(hours=2), verdict="empty_allowed")
    yes = S.output_recovered("lane-x", SINCE, contract)
    assert yes["recovered"] and yes["run_id"] == "good" and yes["output_verdict"] == "empty_allowed"
    assert yes["validator"].startswith("self_heal_fixer.output_recovered@")
    assert S.output_recovered("lane-x", None, contract)["why"] == "no_deployed_at"


def test_advance_goes_through_the_single_output_recovered_hook(monkeypatch, tmp_path):
    """The swap point for the shared recovery validator: advance() asks output_recovered(lane, since, contract) and
    nothing else."""
    seen = []

    def hook(lane, since, contract):
        seen.append((lane, since, contract["kind"]))
        return {"recovered": True, "basis": "stub", "run_id": "r9", "finished_at": "2026-10-16T19:00:00+00:00"}

    monkeypatch.setattr(S, "output_recovered", hook)
    job = {"job_id": "j", "lane": "lane-x", "state": F.FIX_DEPLOYED, "deployed_at": NOW.isoformat(), "history": []}
    assert S.advance(job, cfg=CFG, now=NOW, diag_state=None, root=tmp_path, gh=lambda c: {}, repo=tmp_path) == \
        F.OUTPUT_RECOVERED
    assert seen == [("lane-x", NOW, "live_receipt_output_verdict@v1")] and job["output_run"] == "r9"


# ================================================================ config rails


def test_config_arms_the_boundaries_and_protects_the_new_modules():
    assert CFG["agent_sandbox"]["enabled"] is True and CFG["sandbox"]["enabled"] is True
    assert CFG["claude"]["auth"]["mode"] == "credentials_file"
    assert all(a.endswith(":443") for a in CFG["agent_sandbox"]["egress_allow"])
    assert CFG["arming"]["daily_cost_cap_usd"] >= CFG["iteration"]["max_cost_usd"]
    for p in ("scripts/lib/self_heal_fixer_claims.py", "scripts/lib/self_heal_egress.py",
              "scripts/lib/self_heal_fix_evaluator.py", "tests/test_self_heal_fixer_hardening_20261016.py"):
        assert F.lane_refusal("x", p, CFG) or F._match_any(p, CFG["diff_guard"]["refuse_paths"]), p
    assert F.FIX_INTERRUPTED in F.TERMINAL and F.FIX_INTERRUPTED not in F.HEALED

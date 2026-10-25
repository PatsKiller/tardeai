"""AGENTS.md 21.0.0 §28.15 item 8: grant-free pushes ONLY via ``bin/agent-push <branch>``; toolchains are not deps.

Hermetic. Each test builds a temp guard tree (copies of .cursor/hooks, bin/agent-push, the train policy and the push
budget module, plus a ``guard_push_free.config.json`` pointing every path into the temp dir and ``gh`` at a fake), a
temp bare canonical remote and a clone whose main carries AGENTS.md, a tracked ``.githooks/pre-push`` and
``bin/agent-push``. Nothing reads or writes the real ledger, guard log, claim board, handoffs or budget.

Reviewer exploits from PR #2148 reviews 1 (X1-X11, deps) and 2 (H1-H3, M1-M3, L1-L2) are regression tests here:
every one must be refused.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".cursor" / "hooks"
BRANCH = "feat/item8-demo-20261025"
SESSION = "s-demo-20261025"
CLAIM_ID = "20261025T120000Z-claude-0a1b2c3d"
COORD_ID = "20261025T110000Z-claude-0c0c0c0c"
GH = "https://github.com/PatsKiller/tardeai"
OK_COMMENT = f"{GH}/pull/2148#issuecomment-111"          # operator, on the PR whose head is BRANCH
OTHER_COMMENT = f"{GH}/pull/2148#issuecomment-222"       # not the operator
RATIFY_COMMENT = f"{GH}/pull/2128#issuecomment-444"      # operator's APPROVE_AGENTS_POLICY_ ratification
NAMES_COMMENT = f"{GH}/pull/7#issuecomment-555"          # operator, other PR, body names BRANCH
UNBOUND_COMMENT = f"{GH}/pull/7#issuecomment-666"        # operator, other PR, does not name BRANCH

CLOSURE_STUBS = ("scripts/check_no_secrets.py", "scripts/lib/tradeai_push_budget.py", "scripts/lib/guard_push_auth.py",
                 "scripts/lib/__init__.py", ".cursor/hooks/guard_ledger.py")

pytestmark = pytest.mark.skipif(shutil.which("jq") is None or not Path("/usr/bin/git").exists(),
                                reason="needs jq + /usr/bin/git")

PREPUSH = """#!/bin/sh
# test pre-push: refuses unless authorized, records what it saw
d="$(git rev-parse --git-common-dir)"
echo "auth=${TRADEAI_REMOTE_PUSH_AUTHORIZED:-} grantfree=${TRADEAI_GRANT_FREE:-} consume=${TRADEAI_GUARD_CONSUME:-} \
skip=${TRADEAI_SKIP_SECRETS_SCAN:-}" >> "$d/prepush-ran"
cat >> "$d/prepush-ran"
[ "${TRADEAI_REMOTE_PUSH_AUTHORIZED:-}" = "1" ] || exit 1
"""

FAKE_GH = """#!/bin/sh
U=https://github.com/PatsKiller/tardeai
case "$2" in
  */comments/111) echo "{\\"user\\":{\\"login\\":\\"PatsKiller\\"},\\"html_url\\":\\"$U/pull/2148#issuecomment-111\\",\\"body\\":\\"go ahead\\"}" ;;
  */comments/222) echo "{\\"user\\":{\\"login\\":\\"someone-else\\"},\\"html_url\\":\\"$U/pull/2148#issuecomment-222\\",\\"body\\":\\"ok\\"}" ;;
  */comments/333) echo "{\\"user\\":{\\"login\\":\\"PatsKiller\\"},\\"html_url\\":\\"$U/pull/9#issuecomment-333\\",\\"body\\":\\"ok\\"}" ;;
  */comments/444) echo "{\\"user\\":{\\"login\\":\\"PatsKiller\\"},\\"html_url\\":\\"$U/pull/2128#issuecomment-444\\",\\"body\\":\\"APPROVE_AGENTS_POLICY_21_0_0 2128 f8a89dc6b\\"}" ;;
  */comments/555) echo "{\\"user\\":{\\"login\\":\\"PatsKiller\\"},\\"html_url\\":\\"$U/pull/7#issuecomment-555\\",\\"body\\":\\"approve feat/item8-demo-20261025 too\\"}" ;;
  */comments/666) echo "{\\"user\\":{\\"login\\":\\"PatsKiller\\"},\\"html_url\\":\\"$U/pull/7#issuecomment-666\\",\\"body\\":\\"approved\\"}" ;;
  */pulls/2148) echo '{"head":{"ref":"feat/item8-demo-20261025"}}' ;;
  */pulls/2128) echo '{"head":{"ref":"docs/agents-20-4-0-hands-off-20261025"}}' ;;
  */pulls/7) echo '{"head":{"ref":"feat/other-20261025"}}' ;;
  *) exit 1 ;;
esac
"""


def agents_md(version: str = "21.0.0", header: str = "ACTIVE", row: str = "ACTIVE") -> str:
    return (
        "# AGENTS.md\n\n```\n"
        f"Policy-Version:      {version}\n"
        f"Status:              {header}\n"
        "```\n\nbody\n\n# Version history\n\n"
        "| Version | Date | Status | Class | Summary | Ratification |\n|---|---|---|---|---|---|\n"
        f"| {version} | 2026-10-25 | {row} | MAJOR | item 8 | ratified |\n"
    )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.adir = tmp / "approvals"
        self.adir.mkdir(mode=0o700)
        self.audit = tmp / "audit.jsonl"
        self.claims = tmp / "coordination" / "claims"
        self.claims.mkdir(parents=True)
        self.handoffs = tmp / "coordination" / "handoffs"
        self.handoffs.mkdir()
        self.decisions = tmp / "operator_decisions.jsonl"
        self.budget = tmp / "budget" / "tradeai-push-budget.v2.json"
        self.budget.parent.mkdir()
        self.origin = tmp / "origin.git"
        self.repo = tmp / "work"
        # trusted guard tree copy
        self.tree = tmp / "guardtree"
        shutil.copytree(HOOKS, self.tree / ".cursor" / "hooks", ignore=shutil.ignore_patterns("__pycache__"))
        (self.tree / "bin").mkdir()
        shutil.copy2(ROOT / "bin" / "agent-push", self.tree / "bin" / "agent-push")
        (self.tree / "config").mkdir()
        shutil.copy2(ROOT / "config" / "release_train_policy.json", self.tree / "config" / "release_train_policy.json")
        (self.tree / "scripts" / "lib").mkdir(parents=True)
        for f in ("__init__.py", "tradeai_push_budget.py"):
            shutil.copy2(ROOT / "scripts" / "lib" / f, self.tree / "scripts" / "lib" / f)
        self.gh = tmp / "fake-gh"
        self.gh.write_text(FAKE_GH)
        self.gh.chmod(0o755)
        self.cfg = {
            "canonical_url": str(self.origin), "comment_repo": "PatsKiller/tardeai", "gh": str(self.gh),
            "claims_dir": str(self.claims), "handoffs_dir": str(self.handoffs),
            "approvals_dir": str(self.adir), "audit_log": str(self.audit), "budget_path": str(self.budget),
        }
        self.write_cfg()
        self.env = {
            "PATH": "/usr/bin:/bin", "HOME": str(self.home), "TMPDIR": str(tmp),
            "GUARD_APPROVALS_DIR": str(self.adir), "GUARD_AUDIT_LOG": str(self.audit), "CURSOR_PROJECT_DIR": str(tmp),
            "GUARD_PUSH_FREE_TEST_CONFIG": str(self.cfg_path),  # the hook's own (Cursor's) environment
        }
        subprocess.run([sys.executable, str(HOOKS / "guard_ledger.py"), "init"], env=self.env, check=True,
                       capture_output=True)

    def write_cfg(self) -> None:
        self.cfg_path = self.tmp / "guard_push_free.test-config.json"
        self.cfg_path.write_text(json.dumps(self.cfg))

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        cp = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                             "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                            cwd=str(cwd or self.repo), env=self.env, capture_output=True, text=True)
        if check and cp.returncode != 0:
            raise AssertionError(f"git {args}: {cp.stderr}")
        return cp.stdout.strip()

    def build(self, agents: str | None = agents_md()) -> None:
        self.git("init", "--bare", "-q", str(self.origin), cwd=self.tmp)
        self.git("init", "-q", str(self.repo), cwd=self.tmp)
        if agents is not None:
            (self.repo / "AGENTS.md").write_text(agents)
        (self.repo / ".githooks").mkdir()
        (self.repo / ".githooks" / "pre-push").write_text(PREPUSH)
        (self.repo / ".githooks" / "pre-push").chmod(0o755)
        (self.repo / "bin").mkdir()
        shutil.copy2(ROOT / "bin" / "agent-push", self.repo / "bin" / "agent-push")
        (self.repo / "README").write_text("x\n")
        for rel in CLOSURE_STUBS:  # what the tracked pre-push executes; identical on main and the branch
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(f"# stub {rel}\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "seed")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-qb", BRANCH)
        self.commit("work 1")

    def commit(self, msg: str, path: str = "f.txt") -> str:
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(msg + "\n")
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def claim(self, *, note: str = f"Operator-approval: {OK_COMMENT}", branch: str = BRANCH, session: str = SESSION,
              heartbeat: str | None = None, worklog: str | None = None, claim_id: str = CLAIM_ID,
              paths: list | None = None) -> None:
        doc = {"schema": "AgentClaim@v1", "claim_id": claim_id, "agent": "claude-code", "vendor": "claude",
               "session": session, "branch": branch, "paths": paths or ["scripts/x.py"], "status": "active",
               "task": "demo", "note": note, "started_at": heartbeat or _now(), "heartbeat_at": heartbeat or _now()}
        (self.claims / f"{claim_id}.json").write_text(json.dumps(doc))
        if worklog is not None:
            (self.claims / f"{claim_id}.worklog.md").write_text(worklog)

    def coordinator(self, session: str = "coord-20261025") -> None:
        self.claim(note="coordinator", branch="main", session=session, claim_id=COORD_ID,
                   paths=["coordination/COORDINATOR"])

    def set_budget_count(self, n: int, branch: str = BRANCH) -> None:
        key = f"{self.budget.resolve().parent}#{branch}"
        self.budget.write_text(json.dumps({"schema": "TradeAIPushBudget@v2",
                                           "counters": {key: {"branch": branch, "authorized_push_count": n}}}))

    def checker(self, mode: str = "push", branch: str = BRANCH, session: str | None = SESSION,
                extra_env: dict | None = None, test_config: bool = True) -> dict:
        args = [str(self.tree / ".cursor" / "hooks" / "guard_push_free.py"), mode, "--repo", str(self.repo),
                f"--branch={branch}", "--cwd", str(self.repo)]
        if test_config:
            args += ["--test-config", str(self.cfg_path)]
        if session:
            args += ["--session", session]
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), **(extra_env or {})}
        p = subprocess.run(["/usr/bin/python3", "-I", *args], env=env, capture_output=True, text=True)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        assert (p.returncode == 0) == bool(out.get("allow")), out
        return out

    def checker_raw(self, args: list) -> dict:
        p = subprocess.run(["/usr/bin/python3", "-I", str(self.tree / ".cursor" / "hooks" / "guard_push_free.py"), *args],
                           env={"PATH": "/usr/bin:/bin", "HOME": str(self.home)}, capture_output=True, text=True)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def hook(self, cmd: str, cwd: Path | None = None) -> dict:
        payload = {"command": cmd, "cwd": str(cwd or self.repo), "hook_event_name": "beforeShellExecution"}
        p = subprocess.run(["bash", str(self.tree / ".cursor" / "hooks" / "guard-shell.sh")],
                           input=json.dumps(payload), env=self.env, capture_output=True, text=True, cwd=str(self.tmp))
        return json.loads(p.stdout.strip().splitlines()[-1])

    def events(self, prefix: str = "grant-free") -> list[dict]:
        if not self.audit.exists():
            return []
        rows = [json.loads(x) for x in self.audit.read_text().splitlines() if x.strip()]
        return [r for r in rows if str(r.get("event") or "").startswith(prefix)]

    def remote_sha(self, ref: str) -> str:
        out = self.git("ls-remote", str(self.origin), ref, cwd=self.tmp)
        return out.split("\t")[0] if out else ""

    def main_sha(self) -> str:
        return self.git("rev-parse", "main", cwd=self.origin)

    def prepush_log(self) -> str:
        p = self.repo / ".git" / "prepush-ran"
        return p.read_text() if p.exists() else ""

    def grant(self, uses: int = 3, reason: str = f"push {BRANCH}") -> None:
        subprocess.run([sys.executable, str(HOOKS / "guard_ledger.py"), "grant", "--tier", "git-push",
                        "--expires", str(int(datetime.now(timezone.utc).timestamp()) + 1800),
                        "--uses", str(uses), "--reason", reason], env=self.env, check=True, capture_output=True)


@pytest.fixture
def E(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    e.build()
    return e


def _allowed(v: dict) -> bool:
    return v.get("permission") == "allow"


def _refused(E: Env, out: dict, needle: str = "") -> None:
    assert not out["allow"], out
    if needle:
        assert needle in out["reason"], out["reason"]
    assert [e for e in E.events() if e.get("event") == "grant-free-push"] == []


# =========================================================================== allow


def test_claim_path_pushes_runs_prepush_and_chains_audit(E):
    E.claim()
    before_main = E.main_sha()
    out = E.checker()
    assert out["allow"] and out["outcome"] == "pushed", out
    head = E.git("rev-parse", "HEAD")
    assert E.remote_sha(f"refs/heads/{BRANCH}") == head and E.main_sha() == before_main
    log = E.prepush_log()
    assert "auth=1 grantfree=1 consume=0 skip=" in log and f"refs/heads/{BRANCH}" in log  # L1, pre-push ran
    intent, done = E.events()
    assert intent["event"] == "grant-free-push-intent" and done["event"] == "grant-free-push"
    assert done["outcome"] == "pushed" and done["head"] == head and done["pusher_session"] == SESSION
    assert done["approval_ref"] == OK_COMMENT and done["plan"]["approval_author"] == "PatsKiller"
    assert done["refspec"] == f"{head}:refs/heads/{BRANCH}" and done["cwd"] == str(E.repo)
    assert intent["chain_prev"] == "genesis" and done["chain_prev"] == intent["chain_hash"]  # M3 hash chain
    assert (E.adir / "grant_free_chain.head").read_text().strip() == done["chain_hash"]


def test_fast_forward_second_push_and_worklog_plan(E):
    E.claim(note="working", worklog=f"## Goal\n\nx\n\n## Plan\n\n- Operator-approval: {OK_COMMENT}\n")
    assert E.checker()["allow"]
    E.commit("work 2")
    out = E.checker()
    assert out["allow"], out
    assert E.events()[-1]["ff"] == "fast-forward"


def test_unresolvable_note_falls_back_to_resolvable_plan_line(E):
    E.claim(note="Operator-approval: prose only", worklog=f"## Plan\n\n- [ ] Operator-approval: {OK_COMMENT}  _(added 2026-10-25T21:36:18Z)_\n")
    assert E.checker()["allow"]


def test_coordinator_handoff_path(E):
    E.coordinator()
    (E.handoffs / "batch-1").mkdir()
    (E.handoffs / "batch-1" / "TASK.md").write_text(
        f"Do the page.\nAssigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: {OK_COMMENT}\n")
    out = E.checker(session=None)
    assert out["allow"], out
    assert E.events()[-1]["plan"]["source"] == "handoff"


def test_hook_admits_strict_agent_push_form(E):
    E.claim()
    v = E.hook(f"bin/agent-push {BRANCH}")
    assert _allowed(v) and "GRANT-FREE PUSH admitted" in v["user_message"], v
    assert E.remote_sha(f"refs/heads/{BRANCH}") == ""  # admission only; the wrapper pushes


# =========================================================================== raw shell pushes keep the grant path


@pytest.mark.parametrize("cmd", [
    f"git push origin {BRANCH} ; echo a#b ; git push -f origin HEAD:main",                       # X1
    "git push", "git push origin", f"git push origin {BRANCH}",                                  # X2
    "git config remote.origin.push +HEAD:refs/heads/main && git push origin",                    # X2b
    "true || cd /tmp/decoy && git push origin HEAD",                                             # X4
    "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.push GIT_CONFIG_VALUE_0=+HEAD:refs/heads/main"
    " && git push origin",                                                                       # X5
    f"/tmp/evil/git push origin {BRANCH}",                                                       # X6
    f"TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin {BRANCH}",
    f"git -C /x push origin {BRANCH}",
    f"true || cd /x && bin/agent-push {BRANCH}",                                                 # X4 via wrapper
    f"bin/agent-push {BRANCH} && git push -f origin main",
    f"bin/agent-push -u origin {BRANCH}",
    f"PATH=/evil:$PATH bin/agent-push {BRANCH}",
    f"x;evil/bin/agent-push {BRANCH}",
])
def test_raw_and_compound_pushes_need_a_grant(E, cmd):
    E.claim()
    v = E.hook(cmd)
    assert v["permission"] == "deny", (cmd, v)


@pytest.mark.parametrize("cmd", [
    "export GIT_DIR=/x/.git", "export TRADEAI_SKIP_SECRETS_SCAN=1", "unset TRADEAI_PUSH_BUDGET_PATH",
    "declare -x GIT_CONFIG_COUNT=1", "env GIT_CONFIG_COUNT=1 bash", "set -a; export TRADEAI_REMOTE_PUSH_OVERRIDE=1",
])
def test_h2_env_manipulation_is_push_scope(E, cmd):
    assert E.hook(cmd)["permission"] == "deny"


def test_h1_modified_worktree_wrapper_not_admitted(E):
    E.claim()
    w = E.repo / "bin" / "agent-push"
    w.write_text(w.read_text() + "\n# tampered\n")
    v = E.hook(f"bin/agent-push {BRANCH}")
    assert v["permission"] == "deny" and "byte-identical" in v["agent_message"]


def test_x6_wrapper_elsewhere_not_identical(E, tmp_path):
    E.claim()
    evil = tmp_path / "evil" / "bin"
    evil.mkdir(parents=True)
    (evil / "agent-push").write_text("#!/bin/sh\ngit push -f origin HEAD:main\n")
    assert E.hook(f"{evil}/agent-push {BRANCH}")["permission"] == "deny"


def test_grant_path_unchanged_for_raw_push(E):
    E.grant(uses=2, reason="override force main")
    v = E.hook("git push --force origin main")
    assert _allowed(v) and "AUTO-ACCEPTED" in v["user_message"]
    assert E.events() == []


# =========================================================================== checker refusals


@pytest.mark.parametrize("var,val", [
    ("GIT_CONFIG_COUNT", "1"), ("GIT_DIR", "/x"), ("TRADEAI_AGENT_CLAIMS_DIR", "/x"),
    ("TRADEAI_SKIP_SECRETS_SCAN", "1"), ("TRADEAI_REMOTE_PUSH_OVERRIDE", "1"), ("GUARD_AUDIT_LOG", "/x"),
    ("PYTHONPATH", "/x"), ("LD_PRELOAD", "/x"), ("BASH_ENV", "/x"),
])
def test_x7_h2_env_overrides_refused_by_checker(E, var, val):
    E.claim()
    _refused(E, E.checker(extra_env={var: val}), "environment overrides")


@pytest.mark.parametrize("var", ["GIT_CONFIG_COUNT", "TRADEAI_AGENT_CLAIMS_DIR", "TRADEAI_SKIP_SECRETS_SCAN"])
def test_x7_wrapper_refuses_env_before_anything(E, var):
    E.claim()
    env = dict(E.env, **{var: "1"})
    p = subprocess.run(["bash", str(E.repo / "bin" / "agent-push"), BRANCH], cwd=str(E.repo), env=env,
                       capture_output=True, text=True)
    assert p.returncode == 1 and "environment overrides" in p.stderr
    assert E.remote_sha(f"refs/heads/{BRANCH}") == ""


def test_wrapper_other_args_take_the_grant_path(E):
    p = subprocess.run(["bash", str(E.tree / "bin" / "agent-push"), "-u", "origin", BRANCH], cwd=str(E.repo),
                       env=E.env, capture_output=True, text=True)
    assert p.returncode == 1 and "No active git-push grant" in p.stderr


@pytest.mark.parametrize("key,val", [
    ("remote.origin.push", "+HEAD:refs/heads/main"),                          # X2
    ("remote.origin.mirror", "true"),                                         # X3
    ("remote.origin.receivepack", "git-receive-pack --evil"),                 # X10
    ("push.followTags", "true"),                                              # X10
    ("push.recurseSubmodules", "on-demand"), ("push.pushOption", "x"),        # X10
    ("core.hooksPath", "/dev/null"),                                          # X9
    ("url./tmp/fake.git.insteadOf", "{origin}"),                              # M1
    ("url./tmp/fake.git.pushInsteadOf", "{origin}"),                          # M1
    ("core.sshCommand", "evil"), ("credential.helper", "!evil"), ("http.proxy", "http://evil"),
    ("include.path", "/tmp/evil.cfg"),
])
def test_hijacking_repo_config_refused(E, key, val):
    E.claim()
    E.git("config", key, val.replace("{origin}", str(E.origin)))
    _refused(E, E.checker())
    assert E.remote_sha(f"refs/heads/{BRANCH}") == ""


def test_x8_url_pushurl_split_refused(tmp_path):
    e = Env(tmp_path)
    e.build(agents=agents_md("20.3.0"))
    e.claim()
    fake = tmp_path / "fake.git"
    e.git("init", "--bare", "-q", str(fake), cwd=tmp_path)
    e.git("config", "remote.origin.pushurl", str(e.origin))
    e.git("config", "remote.origin.url", str(fake))
    _refused(e, e.checker(), "canonical")


def test_origin_pointing_elsewhere_refused(E, tmp_path):
    E.claim()
    fake = tmp_path / "fake.git"
    E.git("init", "--bare", "-q", str(fake), cwd=tmp_path)
    E.git("remote", "set-url", "origin", str(fake))
    _refused(E, E.checker(), "canonical")


@pytest.mark.parametrize("agents", [agents_md("20.3.0"), agents_md(header="PROPOSED"), agents_md(row="PROPOSED"),
                                    None, "no control block"])
def test_policy_not_active_refused(tmp_path, agents):
    e = Env(tmp_path)
    e.build(agents=agents)
    e.claim()
    _refused(e, e.checker(), "AGENTS.md")


def test_local_origin_main_cannot_fake_ratification(tmp_path):
    e = Env(tmp_path)
    e.build(agents=agents_md("20.3.0"))
    e.claim()
    e.git("checkout", "-qb", "fake", "main")
    (e.repo / "AGENTS.md").write_text(agents_md())
    e.git("commit", "-qam", "fake ratification")
    e.git("update-ref", "refs/remotes/origin/main", "HEAD")
    e.git("checkout", "-q", BRANCH)
    _refused(e, e.checker())


def test_remote_main_not_fetched_refused(E):
    E.claim()
    other = E.tmp / "other"
    E.git("clone", "-q", str(E.origin), str(other), cwd=E.tmp)
    (other / "AGENTS.md").write_text(agents_md("21.0.1"))
    E.git("commit", "-qam", "bump", cwd=other)
    E.git("push", "-q", "--no-verify", "origin", "main", cwd=other)
    _refused(E, E.checker(), "git fetch origin main")


def test_x9_modified_prepush_refused(E):
    E.claim()
    (E.repo / ".githooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    E.git("commit", "-qam", "neuter pre-push")
    _refused(E, E.checker(), "pre-push")


@pytest.mark.parametrize("branch", ["main", "master", "release/x-2026", "train/w1-abc", "Main", "feat/a..b",
                                    "feat/x.lock", "feat", "refs/heads/feat/x", "feat/x:main", "-f", "feat/$(id)",
                                    "feat/x y", "a/b/c-d"])
def test_branch_name_refused(E, branch):
    E.claim(branch=branch)
    _refused(E, E.checker(branch=branch))


def test_non_fast_forward_refused(E):
    E.claim()
    assert E.checker()["allow"]
    E.git("reset", "-q", "--hard", "HEAD~1")
    E.commit("divergent")
    assert not E.checker()["allow"]
    assert len([e for e in E.events() if e.get("event") == "grant-free-push"]) == 1


def test_h3iii_broker_paths_refused(E):
    E.claim()
    E.commit("broker", path="scripts/brokers/x.py")
    _refused(E, E.checker(), "broker")


def test_budget_exhausted_refused(E):
    E.claim()
    E.set_budget_count(50)
    _refused(E, E.checker(), "push budget")


def test_m2_audit_failure_refuses_before_push(E):
    E.claim()
    E.audit.mkdir()  # the log path is a directory: the intent line cannot be written
    out = E.checker()
    assert not out["allow"] and "guard log write failed" in out["reason"]
    assert E.remote_sha(f"refs/heads/{BRANCH}") == ""


# --------------------------------------------------------------------------- approval evidence


@pytest.mark.parametrize("note", [
    "Operator-approval: yes", "Operator-approval: <ref>", "Operator-approval: tracker item 12 (operator said so)",
    f"Operator-approval: {OTHER_COMMENT}",                                    # comment not by the operator
    "Operator-approval: https://github.com/PatsKiller/tardeai/pull/2148#issuecomment-333",  # wrong PR number
    "Operator-approval: https://github.com/evil/tardeai/pull/1#issuecomment-111",            # other repo
    "Operator-approval: https://github.com/PatsKiller/tardeai/pull/2128#issuecomment-999",   # gh fails
    "Operator-approval: operator-decision:req-missing-1", "working on it", f"Operator-approval: {RATIFY_COMMENT}",
    f"Operator-approval: {UNBOUND_COMMENT}",
])
def test_x11b_claim_approval_must_resolve(E, note):
    E.claim(note=note)
    _refused(E, E.checker())


def test_f2_operator_decision_ledger_not_accepted(E):
    E.decisions.write_text(json.dumps({"event": "DECIDED", "decision": "APPROVE", "request_id": "req-0001-demo",
                                       "actor": "PatsKiller", "item_id": BRANCH}) + "\n")
    E.claim(note="Operator-approval: operator-decision:req-0001-demo")
    _refused(E, E.checker(), "does not resolve")


@pytest.mark.parametrize("ref,ok", [(NAMES_COMMENT, True), (UNBOUND_COMMENT, False), (RATIFY_COMMENT, False)])
def test_f1_claim_comment_must_bind_to_branch(E, ref, ok):
    E.claim(note=f"Operator-approval: {ref}")
    out = E.checker()
    assert out["allow"] is ok, out
    if ok:
        assert E.events()[-1]["plan"]["approval_bound"] == "comment-names-branch"
    else:
        assert ("not bound" in out["reason"]) or ("ratifies a policy" in out["reason"]), out


@pytest.mark.parametrize("ref,ok", [(UNBOUND_COMMENT, True), (RATIFY_COMMENT, False), (OTHER_COMMENT, False)])
def test_f1_handoff_binds_by_assignment_but_never_a_ratification(E, ref, ok):
    E.coordinator()
    (E.handoffs / "T.md").write_text(
        f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: {ref}\n")
    out = E.checker(session=None)
    assert out["allow"] is ok, out
    if ref == RATIFY_COMMENT:
        assert "ratifies a policy" in out["reason"]


def test_f1_done_coordinator_claim_does_not_assign(E):
    E.coordinator()
    doc = json.loads((E.claims / f"{COORD_ID}.json").read_text())
    doc["status"] = "done"
    (E.claims / f"{COORD_ID}.json").write_text(json.dumps(doc))
    (E.handoffs / "T.md").write_text(
        f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: {UNBOUND_COMMENT}\n")
    _refused(E, E.checker(session=None), "COORDINATOR")


@pytest.mark.parametrize("rel,content,commit", [
    ("scripts/check_no_secrets.py", "import sys; sys.exit(0)\n", True),
    ("scripts/lib/tradeai_push_budget.py", "def count_for(b): return 0\n", True),
    ("scripts/lib/guard_push_auth.py", "x = 1\n", False),
    (".cursor/hooks/guard_ledger.py", "x = 1\n", False),
    ("scripts/__init__.py", "import os\n", False),
    ("scripts/lib/json.py", "raise SystemExit(0)\n", False),
    ("sitecustomize.py", "import os\n", False),
    ("subprocess.py", "x = 1\n", True),
    (".cursor/hooks/uuid.py", "x = 1\n", False),
])
def test_f3_prepush_closure_and_stdlib_shadowing_refused(E, rel, content, commit):
    E.claim()
    p = E.repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    if commit:
        E.git("add", "-A")
        E.git("commit", "-qm", f"touch {rel}")
    _refused(E, E.checker(), rel)


def test_n5_config_beside_module_is_ignored(E, tmp_path):
    E.claim()
    planted = E.tree / ".cursor" / "hooks" / "guard_push_free.config.json"
    planted.write_text(json.dumps(E.cfg))
    out = E.checker(test_config=False)  # production defaults: canonical github URL, so this origin is refused
    _refused(E, out, "canonical")


def test_chain_verifier(E):
    E.claim()
    assert E.checker()["allow"]
    E.commit("work 2")
    assert E.checker()["allow"]
    v = E.checker_raw(["verify-chain", "--test-config", str(E.cfg_path)])
    assert v["ok"] and v["events"] == 4, v
    lines = E.audit.read_text().splitlines()
    lines[1] = lines[1].replace('"outcome":"pushed"', '"outcome":"forged"')
    E.audit.write_text("\n".join(lines) + "\n")
    v = E.checker_raw(["verify-chain", "--test-config", str(E.cfg_path)])
    assert not v["ok"] and any("does not match" in x for x in v["problems"]), v


def test_h3i_claim_of_another_session_refused(E):
    E.claim(session="someone-else-20261025")
    _refused(E, E.checker(), "no live claim")
    _refused(E, E.checker(session=None))


def test_stale_claim_refused(E):
    E.claim(heartbeat="2026-01-01T00:00:00Z")
    _refused(E, E.checker())


def test_approval_outside_goal_plan_refused(E):
    E.claim(note="x", worklog=f"## Goal\n\nx\n\n## Decisions\n\n- Operator-approval: {OK_COMMENT}\n")
    _refused(E, E.checker())


@pytest.mark.parametrize("name,body", [
    ("notes.md", f"Do NOT push {BRANCH}; operator rejected it.\n"),                               # X11 mention
    ("T.md", f"Assigned-branch: {BRANCH}\nOperator-approval: {OK_COMMENT}\n"),                    # no Assigned-by
    ("T.md", f"Assigned-branch: {BRANCH}\nAssigned-by: not-a-coordinator\nOperator-approval: {OK_COMMENT}\n"),
    ("T.md", f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: yes\n"),
    ("T.json", f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: {OK_COMMENT}\n"),
    ("PROGRESS_LOG.md", f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: {OK_COMMENT}\n"),
    ("T.md", f"Assigned-branch: {BRANCH}-v2\nAssigned-by: coord-20261025\nOperator-approval: {OK_COMMENT}\n"),
])
def test_h3ii_handoff_must_be_structured_coordinator_assignment(E, name, body):
    E.coordinator()
    (E.handoffs / name).write_text(body)
    _refused(E, E.checker(session=None))


def test_handoff_too_deep_or_symlink_or_group_writable_refused(E, tmp_path):
    E.coordinator()
    body = f"Assigned-branch: {BRANCH}\nAssigned-by: coord-20261025\nOperator-approval: {OK_COMMENT}\n"
    deep = E.handoffs / "b" / "evidence"
    deep.mkdir(parents=True)
    (deep / "T.md").write_text(body)
    outside = tmp_path / "outside.md"
    outside.write_text(body)
    (E.handoffs / "link.md").symlink_to(outside)
    gw = E.handoffs / "gw.md"
    gw.write_text(body)
    gw.chmod(0o664)
    _refused(E, E.checker(session=None))


@pytest.mark.parametrize("cmd", ["cp x ~/.cursor/hooks.json", "echo x > .cursor/hooks/guard-lib.sh",
                                 "sed -i s/a/b/ /r/.cursor/hooks/guard-shell.sh", "chmod 777 .cursor/hooks/guard-lib.sh"])
def test_n5_shell_writes_to_the_guard_are_guard_config(cmd):
    assert _classify(cmd) == "guard-config"


def test_handoff_writes_are_guarded():
    assert _classify("echo x > ~/trade-ai-releases/persistent-state/data/coordination/handoffs/T.md") == "release-write"
    assert _classify("cp a.md data/coordination/handoffs/T.md") == "release-write"
    assert _classify_path("/home/u/repo/data/coordination/handoffs/T.md") == "release-write"


# =========================================================================== (b) deps classification


def _classify(cmd: str) -> str:
    p = subprocess.run(["bash", "-c", 'source "$1"; classify_cmd "$2"', "_", str(HOOKS / "guard-lib.sh"), cmd],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


def _classify_path(path: str) -> str:
    p = subprocess.run(["bash", "-c", 'source "$1"; classify_path "$2" Write', "_", str(HOOKS / "guard-lib.sh"), path],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip()


@pytest.mark.parametrize("cmd", [
    "npm run build", "npm run test:e2e -- --project=phone", "npm test", "npm run lint",
    "npm --prefix apps/command-center-v3 run build", "cd apps/command-center-v3 && npm run build",
    "npx playwright test", "npx playwright test e2e/home.spec.ts --project=phone-412",
    "pytest", "pytest -q tests/test_x.py", "python3 -m pytest -x", "ruff check scripts", "ruff format --check .",
    "tsc --noEmit", "npx tsc -p apps/command-center-v3", "vite build", "npx vite build", "node scripts/x.mjs",
    "node --test", "npm run build && npx playwright test && pytest -q", "cat package-lock.json",
    "npm ls", "npm outdated", "yarn build", "uv run pytest", "npx tsc -p apps/x --noEmit",
    "git commit -m 'npm i fix'", 'git commit -m "pip install x"', "gh pr create --title 'npm ci in CI' --body 'x'",
])
def test_toolchain_runs_are_not_deps(cmd):
    assert _classify(cmd) == "none", cmd


@pytest.mark.parametrize("cmd", [
    "npm ci", "npm i", "npm install", "npm install vite@5", "npm i -D vite", "npm --prefix apps/x ci", "npm --prefix web ci",
    "cd apps/x && npm ci && npm run build", "npm uninstall x", "npm rm x", "npm update", "npm upgrade",
    "npm audit fix", "npm dedupe", "npm it", "npm install-test", "npm exec some-pkg",
    "pnpm add x", "pnpm install", "pnpm i", "yarn", "yarn add x", "yarn install", "yarn && npm run build",
    "bun add left-pad", "bun install", "bun i", "corepack prepare pnpm@9 --activate", "corepack enable",
    "npx --yes some-installer", "npx -y create-x", "npx --package=x y", "npx -q -y x", "conda install x", "mamba install x",
    "pip install x", "pip install -e .", "pip3 install -U x", "python -m pip install x",
    "python3 -m pip install -r requirements.txt", "pip uninstall -y x", "uv pip install x", "uv sync", "uv add x",
    "uv run --with requests python x.py", "pipx run x", "pipx install x", "poetry add x", "apt install jq",
    "apt-get install -y jq", "npx playwright install chromium", "npx playwright install-deps",
    "sed -i s/a/b/ apps/x/package-lock.json", "echo {} > package-lock.json", "cp /x/yarn.lock yarn.lock", "rm uv.lock",
    'git commit -m "$(npm install x)"',
])
def test_installs_and_lockfile_edits_are_deps(cmd):
    assert _classify(cmd) == "deps", cmd


@pytest.mark.parametrize("path", ["apps/command-center-v3/package-lock.json", "yarn.lock", "x/pnpm-lock.yaml",
                                  "poetry.lock", "uv.lock", "Pipfile.lock", "bun.lockb"])
def test_lockfile_writes_are_deps(path):
    assert _classify_path(path) == "deps"


@pytest.mark.parametrize("cmd", ["git -C /x push --force origin main", "git -c a=b push", "git --no-pager push",
                                 "git push", "git reset --hard", "git -C /x rebase main", "bin/agent-push feat/x-1",
                                 "~/wt/bin/agent-push -u origin HEAD",
                                 "python3 ~/x/.cursor/hooks/guard_push_free.py push --test-config /tmp/c.json"])
def test_push_shapes_classify_git_push(cmd):
    assert _classify(cmd) == "git-push"


def test_policy_reader_matches_hands_off_policy_when_present():
    sys.path.insert(0, str(HOOKS))
    import importlib

    gpf = importlib.import_module("guard_push_free")
    try:
        hop = importlib.import_module("scripts.lib.hands_off_policy")
    except ImportError:
        pytest.skip("scripts/lib/hands_off_policy.py not on this tree yet (PRs #2115/#2118/#2125)")
    for text in (agents_md(), agents_md("20.3.0"), agents_md("22.1.0"), agents_md(header="PROPOSED"),
                 agents_md(row="PROPOSED"), agents_md(header="ACTIVE (MAJOR)"), "", None):
        st = hop.policy_state_from_text(text)
        ver = gpf._semver(st.get("version"))
        assert gpf.policy_state_from_text(text)["active"] == (bool(st["active"]) and ver is not None
                                                              and ver >= gpf.MIN_POLICY), text

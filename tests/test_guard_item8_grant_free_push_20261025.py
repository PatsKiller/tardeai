"""AGENTS.md 21.0.0 §28.15 item 8: grant-free pushes for approved plans, and toolchain runs are never ``deps``.

Hermetic: every test builds a temp bare ``origin`` and a clone, a fake claim board, a fake handoffs directory, a fake
push-budget file, a temp approval ledger and audit log, and HOME pointed at the temp dir. Nothing reads or writes
the real ledger, guard log, claim board or budget. The hook under test is the tracked ``.cursor/hooks/guard-shell.sh``
run as Cursor runs it (JSON on stdin, verdict JSON on stdout).
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
CHECKER = HOOKS / "guard_push_free.py"
BRANCH = "feat/item8-demo-20261025"
CLAIM_ID = "20261025T120000Z-claude-0a1b2c3d"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None or shutil.which("git") is None, reason="needs jq + git")


# --------------------------------------------------------------------------- AGENTS.md states

def agents_md(version: str = "21.0.0", header: str = "ACTIVE", row: str = "ACTIVE") -> str:
    return (
        "# AGENTS.md\n\n```\n"
        f"Policy-Version:      {version}\n"
        f"Status:              {header}\n"
        "```\n\nbody\n\n# Version history\n\n"
        "| Version | Date | Status | Class | Summary | Ratification |\n|---|---|---|---|---|---|\n"
        f"| {version} | 2026-10-25 | {row} | MAJOR | item 8 | ratified |\n"
    )


# --------------------------------------------------------------------------- fixture


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
        self.budget = tmp / "budget" / "tradeai-push-budget.v2.json"
        self.budget.parent.mkdir()
        self.origin = tmp / "origin.git"
        self.repo = tmp / "work"
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "TMPDIR": str(tmp),
            "GUARD_APPROVALS_DIR": str(self.adir),
            "GUARD_AUDIT_LOG": str(self.audit),
            "TRADEAI_AGENT_CLAIMS_DIR": str(self.claims),
            "TRADEAI_COORDINATION_HANDOFFS_DIR": str(self.handoffs),
            "TRADEAI_PUSH_BUDGET_PATH": str(self.budget),
            "TRADEAI_STATE_ROOT": str(tmp / "state"),
            "CURSOR_PROJECT_DIR": str(tmp),
        }
        subprocess.run([sys.executable, str(HOOKS / "guard_ledger.py"), "init"], env=self.env, check=True,
                       capture_output=True)

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
        (self.repo / "README").write_text("x\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "seed")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-qb", BRANCH)
        self.commit("work 1")

    def commit(self, msg: str) -> str:
        (self.repo / "f.txt").write_text(msg + "\n")
        self.git("add", "-A")
        self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD")

    def claim(self, *, note: str = "Operator-approval: tracker item 12 (operator 2026-10-25)", branch: str = BRANCH,
              heartbeat: str | None = None, worklog: str | None = None, claim_id: str = CLAIM_ID) -> None:
        doc = {"schema": "AgentClaim@v1", "claim_id": claim_id, "agent": "claude-code", "vendor": "claude",
               "session": "s-demo", "branch": branch, "paths": ["scripts/x.py"], "status": "active",
               "task": "demo", "note": note, "started_at": heartbeat or _now(), "heartbeat_at": heartbeat or _now()}
        (self.claims / f"{claim_id}.json").write_text(json.dumps(doc))
        if worklog is not None:
            (self.claims / f"{claim_id}.worklog.md").write_text(worklog)

    def set_budget_count(self, n: int, branch: str = BRANCH) -> None:
        key = f"{self.budget.resolve().parent}#{branch}"
        self.budget.write_text(json.dumps({"schema": "TradeAIPushBudget@v2",
                                           "counters": {key: {"branch": branch, "authorized_push_count": n}}}))

    def hook(self, cmd: str, cwd: Path | None = None, hooks_dir: Path = HOOKS) -> dict:
        payload = {"command": cmd, "cwd": str(cwd or self.repo), "hook_event_name": "beforeShellExecution"}
        p = subprocess.run(["bash", str(hooks_dir / "guard-shell.sh")], input=json.dumps(payload), env=self.env,
                           capture_output=True, text=True, cwd=str(self.tmp))
        return json.loads(p.stdout.strip().splitlines()[-1])

    def check(self, cmd: str, cwd: Path | None = None) -> dict:
        p = subprocess.run([sys.executable, "-I", str(CHECKER), "check", "--command", cmd, "--cwd",
                            str(cwd or self.repo)], env=self.env, capture_output=True, text=True)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        assert (p.returncode == 0) == bool(out.get("allow")), out
        return out

    def audit_events(self, event: str = "grant-free-push") -> list[dict]:
        if not self.audit.exists():
            return []
        rows = [json.loads(x) for x in self.audit.read_text().splitlines() if x.strip()]
        return [r for r in rows if r.get("event") == event]

    def grant(self, uses: int = 3) -> None:
        subprocess.run([sys.executable, str(HOOKS / "guard_ledger.py"), "grant", "--tier", "git-push",
                        "--expires", str(int(datetime.now(timezone.utc).timestamp()) + 1800),
                        "--uses", str(uses), "--reason", f"push {BRANCH}"], env=self.env, check=True,
                       capture_output=True)

    def uses_left(self) -> int:
        out = subprocess.run([sys.executable, str(HOOKS / "guard_ledger.py"), "list"], env=self.env,
                             capture_output=True, text=True, check=True).stdout
        rec = (json.loads(out).get("active") or {}).get("git-push") or {}
        return int(rec.get("uses") or rec.get("uses_left") or 0)


@pytest.fixture
def E(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    e.build()
    return e


PUSH = f"TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin {BRANCH}"


def _allowed(v: dict) -> bool:
    return v.get("permission") == "allow"


# --------------------------------------------------------------------------- allow paths


def test_claim_note_approval_allows_and_records(E):
    E.claim()
    v = E.hook(PUSH)
    assert _allowed(v), v
    assert "GRANT-FREE PUSH" in v["user_message"]
    ev = E.audit_events()
    assert len(ev) == 1
    head = E.git("rev-parse", "HEAD")
    assert ev[0]["branch"] == BRANCH and ev[0]["head"] == head and ev[0]["tier"] == "git-push"
    assert ev[0]["approval_ref"].startswith("tracker item 12")
    assert ev[0]["plan"]["source"] == "claim" and ev[0]["plan"]["claim_id"] == CLAIM_ID
    assert ev[0]["ff"] == "new-branch" and ev[0]["policy"]["version"] == "21.0.0"


def test_worklog_plan_approval_allows(E):
    E.claim(note="working", worklog="# Worklog\n\n## Goal\n\ndemo\n\n## Plan\n\n- Operator-approval: PR #2128 item 8\n")
    out = E.check(PUSH)
    assert out["allow"] and out["plan"]["where"] == "worklog plan" and out["approval_ref"] == "PR #2128 item 8"


def test_handoff_file_naming_branch_allows(E):
    (E.handoffs / "batch-20261025").mkdir()
    (E.handoffs / "batch-20261025" / "CURSOR_ASSIGNMENT.md").write_text(f"Do page 3 on branch `{BRANCH}`.\n")
    out = E.check(PUSH)
    assert out["allow"] and out["plan"]["source"] == "handoff"
    assert out["approval_ref"] == "handoff:batch-20261025/CURSOR_ASSIGNMENT.md"


def test_handoff_naming_live_claim_id_allows(E):
    E.claim(note="no approval line here")
    (E.handoffs / "TASK.md").write_text(f"Assigned: claim {CLAIM_ID}.\nOperator-approval: tracker 7\n")
    out = E.check(PUSH)
    assert out["allow"] and out["plan"]["names"] == CLAIM_ID and "tracker 7" in out["approval_ref"]


def test_fast_forward_of_existing_remote_branch_allows(E):
    E.claim()
    E.git("push", "-q", "origin", BRANCH)
    E.commit("work 2")
    out = E.check(PUSH)
    assert out["allow"] and out["ff"] == "fast-forward" and out["remote_head"]


@pytest.mark.parametrize("cmd", [
    f"cd {{repo}} && TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin HEAD 2>&1 | tail -3",
    f"git add -A && git commit -qm 'a && b' ; git push origin HEAD:{BRANCH}",
    f"git -C {{repo}} push origin refs/heads/{BRANCH}",
    "git push",
    "git push -uq origin",
])
def test_command_shapes_allowed(E, cmd):
    E.claim()
    E.git("push", "-q", "-u", "origin", BRANCH)
    E.commit("work 2")
    v = E.hook(cmd.replace("{repo}", str(E.repo)), cwd=E.tmp if "{repo}" in cmd else E.repo)
    assert _allowed(v), v


def test_grant_free_path_does_not_consume_an_existing_grant(E):
    E.claim()
    E.grant(uses=3)
    before = E.uses_left()
    assert _allowed(E.hook(PUSH))
    assert E.uses_left() == before


def test_agent_push_wrapper_pushes_grant_free(E):
    E.claim()
    p = subprocess.run(["bash", str(ROOT / "bin" / "agent-push"), "-u", "origin", BRANCH], cwd=str(E.repo),
                       env=E.env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert E.git("rev-parse", BRANCH, cwd=E.origin) == E.git("rev-parse", "HEAD")
    assert E.audit_events()[0]["command"].startswith("bin/agent-push")


def test_agent_push_wrapper_refuses_force(E):
    E.claim()
    p = subprocess.run(["bash", str(ROOT / "bin" / "agent-push"), "--force", "origin", BRANCH], cwd=str(E.repo),
                       env=E.env, capture_output=True, text=True)
    assert p.returncode == 1 and "force" in p.stderr
    assert E.git("ls-remote", "origin", f"refs/heads/{BRANCH}") == ""


# --------------------------------------------------------------------------- refusals: policy


@pytest.mark.parametrize("agents", [
    agents_md("20.3.0"),
    agents_md("21.0.0", header="PROPOSED"),
    agents_md("21.0.0", row="PROPOSED"),
    None,
    "no control block",
])
def test_policy_not_active_refuses(tmp_path, agents):
    e = Env(tmp_path)
    e.build(agents=agents)
    e.claim()
    out = e.check(PUSH)
    assert not out["allow"] and "AGENTS.md" in out["reason"]
    v = e.hook(PUSH)
    assert v["permission"] == "deny" and "Grant-free push" in v["agent_message"]
    assert e.audit_events() == []


def test_local_origin_main_cannot_fake_ratification(tmp_path):
    e = Env(tmp_path)
    e.build(agents=agents_md("20.3.0"))
    e.claim()
    # An agent forges a local origin/main with a ratified AGENTS.md; the remote main is still 20.3.0.
    e.git("checkout", "-qb", "fake", "main")
    (e.repo / "AGENTS.md").write_text(agents_md())
    e.git("commit", "-qam", "fake ratification")
    e.git("update-ref", "refs/remotes/origin/main", "HEAD")
    e.git("checkout", "-q", BRANCH)
    assert not e.check(PUSH)["allow"]


def test_remote_main_not_fetched_refuses(E):
    E.claim()
    other = E.tmp / "other"
    E.git("clone", "-q", str(E.origin), str(other), cwd=E.tmp)
    (other / "AGENTS.md").write_text(agents_md("21.0.1"))
    E.git("commit", "-qam", "bump", cwd=other)
    E.git("push", "-q", "origin", "main", cwd=other)
    out = E.check(PUSH)
    assert not out["allow"] and "git fetch origin main" in out["reason"]
    E.git("fetch", "-q", "origin", "main")
    assert E.check(PUSH)["allow"]


# --------------------------------------------------------------------------- refusals: ref and flags


@pytest.mark.parametrize("cmd", [
    "git push origin main", "git push origin HEAD:main", "git push origin HEAD:refs/heads/main",
    "git push origin HEAD:master", "git push origin HEAD:release/2026-10-25", "git push origin HEAD:train/w1",
    "git push origin HEAD:Main", "git push origin HEAD:refs/tags/v1", "git push origin v1",
])
def test_protected_or_non_branch_destination_refuses(E, cmd):
    E.claim(branch="main")
    E.claim(branch=BRANCH, claim_id="20261025T120001Z-claude-0a1b2c3e")
    E.git("tag", "v1")
    out = E.check(cmd)
    assert not out["allow"], out
    assert E.hook(cmd)["permission"] == "deny"


@pytest.mark.parametrize("flag", [
    "-f", "--force", "--force-with-lease", f"--force-with-lease={BRANCH}", "--force-if-includes", "-uf",
    "--delete", "-d", "--mirror", "--all", "--tags", "--follow-tags", "--prune", "--no-verify", "-o ci.skip",
    "--push-option=x", "--repo=origin", "--receive-pack=x", "--signed", "--unknown-flag",
])
def test_force_delete_and_unknown_flags_refuse(E, flag):
    E.claim()
    cmd = f"git push {flag} origin {BRANCH}"
    assert not E.check(cmd)["allow"]
    v = E.hook(cmd)
    assert v["permission"] == "deny" and E.audit_events() == []


@pytest.mark.parametrize("refspec", [f"+{BRANCH}", f":{BRANCH}", f"{BRANCH} other/branch-x"])
def test_plus_refspec_delete_refspec_and_multiple_refs_refuse(E, refspec):
    E.claim()
    assert not E.check(f"git push origin {refspec}")["allow"]


def test_non_fast_forward_refuses(E):
    E.claim()
    E.git("push", "-q", "origin", BRANCH)
    E.git("reset", "-q", "--hard", "HEAD~1")
    E.commit("divergent")
    out = E.check(PUSH)
    assert not out["allow"] and "not a fast-forward" in out["reason"]


def test_remote_branch_not_local_refuses(E):
    E.claim()
    E.git("push", "-q", "origin", BRANCH)
    other = E.tmp / "other"
    E.git("clone", "-q", "-b", BRANCH, str(E.origin), str(other), cwd=E.tmp)
    (other / "g.txt").write_text("g\n")
    E.git("add", "-A", cwd=other)
    E.git("commit", "-qm", "elsewhere", cwd=other)
    E.git("push", "-q", "origin", BRANCH, cwd=other)
    assert not E.check(PUSH)["allow"]


@pytest.mark.parametrize("cmd", [
    f"git push upstream {BRANCH}",
    f"git push https://example.invalid/x.git {BRANCH}",
    f"git -c remote.origin.url=/x push origin {BRANCH}",
    f"git --git-dir=/x/.git push origin {BRANCH}",
    f"GIT_DIR=/x/.git git push origin {BRANCH}",
    f"TRADEAI_REMOTE_PUSH_OVERRIDE=1 git push origin {BRANCH}",
    f"env TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push origin {BRANCH}",
    f"timeout 60 git push origin {BRANCH}",
    f"git push origin {BRANCH} && git push -f origin main",
    f"git push origin {BRANCH}; git push origin {BRANCH}",
    f"git push origin $(git branch --show-current)",
    "git push origin `git branch --show-current`",
    "git push origin $BRANCH",
    "git push origin feat/*",
    f"git push origin {BRANCH} &",
    f"(git push origin {BRANCH})",
    f'git push origin {BRANCH} "&&" --force',
    f"git push origin {BRANCH}\ngit push -f origin main",
    f"git push origin {BRANCH} > /tmp/x",
    "cd $HOME && git push",
    "pushd /x && git push",
])
def test_unsafe_command_shapes_refuse(E, cmd):
    E.claim()
    out = E.check(cmd)
    assert not out["allow"], (cmd, out)


@pytest.mark.parametrize("other", [
    "sudo true", "rm -rf build", "crontab -l", "git reset --hard HEAD~1", "systemctl --user restart x.service",
    "npm ci", "psql -c 'DELETE FROM t'",
])
def test_guarded_companion_segment_refuses(E, other):
    E.claim()
    v = E.hook(f"{other} && {PUSH}") if not other.startswith("git reset") else E.hook(f"{PUSH} && {other}")
    assert not _allowed(v), (other, v)
    assert E.audit_events() == []


def test_detached_head_without_refspec_refuses(E):
    E.claim()
    E.git("checkout", "-q", "--detach")
    assert not E.check("git push origin")["allow"]


def test_matching_push_default_refuses(E):
    E.claim()
    E.git("config", "push.default", "matching")
    assert not E.check("git push")["allow"]


# --------------------------------------------------------------------------- refusals: plan and budget


def test_no_claim_and_no_handoff_refuses(E):
    out = E.check(PUSH)
    assert not out["allow"] and "no approved plan" in out["reason"]


@pytest.mark.parametrize("note", ["working on it", "Operator-approval: <ref>", "Operator-approval: TBD",
                                  "Operator-approval:"])
def test_claim_without_real_approval_refuses(E, note):
    E.claim(note=note)
    assert not E.check(PUSH)["allow"]


def test_stale_claim_refuses(E):
    E.claim(heartbeat="2026-01-01T00:00:00Z")
    assert not E.check(PUSH)["allow"]


def test_claim_on_other_branch_refuses(E):
    E.claim(branch="feat/someone-else-20261025")
    assert not E.check(PUSH)["allow"]


def test_approval_outside_goal_and_plan_sections_refuses(E):
    E.claim(note="x", worklog="## Goal\n\ndemo\n\n## Decisions\n\n- Operator-approval: relayed by another agent\n")
    assert not E.check(PUSH)["allow"]


def test_handoff_substring_is_not_a_match(E):
    (E.handoffs / "T.md").write_text(f"see docs {BRANCH}-v2 and origin{BRANCH}x\n")
    assert not E.check(PUSH)["allow"]


def test_handoff_symlink_is_ignored(E, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(f"branch {BRANCH}\n")
    (E.handoffs / "link.md").symlink_to(outside)
    assert not E.check(PUSH)["allow"]


def test_push_budget_exhausted_refuses(E):
    E.claim()
    E.set_budget_count(1)
    assert E.check(PUSH)["allow"]
    E.set_budget_count(50)
    out = E.check(PUSH)
    assert not out["allow"] and "push budget" in out["reason"]


# --------------------------------------------------------------------------- fail closed


def test_missing_checker_falls_back_to_grant_path(E, tmp_path):
    hooks = tmp_path / "hookcopy" / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    for f in ("guard-shell.sh", "guard-lib.sh", "guard_ledger.py"):
        shutil.copy2(HOOKS / f, hooks / f)
    E.claim()
    v = E.hook(PUSH, hooks_dir=hooks)
    assert v["permission"] == "deny" and "not installed" in v["agent_message"]


def test_guard_tree_without_lib_refuses(E, tmp_path):
    hooks = tmp_path / "hookcopy" / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    for f in ("guard-shell.sh", "guard-lib.sh", "guard_ledger.py", "guard_push_free.py"):
        shutil.copy2(HOOKS / f, hooks / f)
    E.claim()
    v = E.hook(PUSH, hooks_dir=hooks)
    assert v["permission"] == "deny" and "internal error" in v["agent_message"]


def test_without_grant_free_conditions_grant_path_unchanged(E):
    E.grant(uses=2)
    v = E.hook("git push --force origin main")
    assert _allowed(v) and "AUTO-ACCEPTED" in v["user_message"]  # today's behaviour: the operator's grant decides
    assert E.audit_events() == []


# --------------------------------------------------------------------------- (b) deps classification


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
    "npm ls", "npm outdated",
])
def test_toolchain_runs_are_not_deps(cmd):
    assert _classify(cmd) == "none", cmd


@pytest.mark.parametrize("cmd", [
    "npm ci", "npm i", "npm install", "npm install vite@5", "npm i -D vite", "npm --prefix apps/x ci",
    "cd apps/x && npm ci && npm run build", "npm uninstall x", "npm rm x", "npm update", "npm upgrade",
    "npm audit fix", "npm dedupe", "pnpm add x", "pnpm install", "yarn add x", "pip install x", "pip3 install -U x",
    "python3 -m pip install -r requirements.txt", "pip uninstall -y x", "uv pip install x", "uv sync", "uv add x",
    "poetry add x", "apt install jq", "apt-get install -y jq", "npx playwright install chromium",
    "npx playwright install-deps", "sed -i s/a/b/ apps/x/package-lock.json", "echo {} > package-lock.json",
    "cp /x/yarn.lock yarn.lock", "rm uv.lock",
])
def test_installs_and_lockfile_edits_are_deps(cmd):
    assert _classify(cmd) == "deps", cmd


@pytest.mark.parametrize("path", ["apps/command-center-v3/package-lock.json", "yarn.lock", "x/pnpm-lock.yaml",
                                  "poetry.lock", "uv.lock", "Pipfile.lock"])
def test_lockfile_writes_are_deps(path):
    assert _classify_path(path) == "deps"


@pytest.mark.parametrize("cmd", ["git -C /x push --force origin main", "git -c a=b push", "git --no-pager push",
                                 "git push", "git reset --hard", "git -C /x rebase main"])
def test_git_global_options_still_classify_git_push(cmd):
    assert _classify(cmd) == "git-push"


# --------------------------------------------------------------------------- reuse parity


def test_vendored_policy_reader_agrees_with_hands_off_policy():
    sys.path.insert(0, str(HOOKS))
    import importlib

    gpf = importlib.import_module("guard_push_free")
    try:
        hop = importlib.import_module("scripts.lib.hands_off_policy")
    except ImportError:
        pytest.skip("scripts/lib/hands_off_policy.py not on this tree yet (PRs #2115/#2118/#2125)")
    for text in (agents_md(), agents_md("20.3.0"), agents_md("22.1.0"), agents_md(header="PROPOSED"),
                 agents_md(row="PROPOSED"), agents_md(header="ACTIVE (MAJOR)"), "", None):
        def gate(st):  # what check_policy() acts on: ACTIVE and at least 21.0.0
            ver = gpf._semver(st.get("version"))
            return bool(st.get("active")) and ver is not None and ver >= gpf.MIN_POLICY

        assert gate(gpf._vendored_policy_state(text, "t")) == gate(hop.policy_state_from_text(text)), text
    for t in ("Operator-approval: x", "- [x] Operator-approval: `PR #1`", "Operator-approval: <ref>", "none"):
        assert hop.approval_ref(t) == _vendored_approval(gpf, t)


def _vendored_approval(gpf, text):
    for m in gpf._APPROVAL_RE.finditer(text or ""):
        ref = (m.group("ref") or "").strip().strip("`").strip()
        if ref and not gpf._PLACEHOLDER.match(ref):
            return ref[:300]
    return None

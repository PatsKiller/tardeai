#!/usr/bin/env python3
"""self_heal_fixer.py — route self-heal CODE DEFECTS to an iterative headless Claude Code fixer.

Operator 2026-10-16: "I don't want the regular LLM routing. I want it to connect into Claude Code to fix it in
iterations." Transient failures stay with the self-heal tier (rerun / reap); a ``code_error`` diagnosis becomes a fix
job here. Design and lifecycle: docs/ops/self_heal_claude_fixer.md. Decisions: scripts/lib/self_heal_fixer.py.

    # dry run (default): build the job, evidence pack, prompt and claude argv; no worktree, no model, no state write
    .venv/bin/python scripts/self_heal_fixer.py --cycle
    .venv/bin/python scripts/self_heal_fixer.py --cycle --incident tests/fixtures/self_heal_fixer/daily_incubator_refresh_20261016.json --out /tmp/shf
    # live (DISARMED until the operator grant): intake -> attempt one job -> advance lifecycles
    .venv/bin/python scripts/self_heal_fixer.py --cycle --apply
    .venv/bin/python scripts/self_heal_fixer.py --status

Exit codes: 0 cycle ran (including "nothing to do" and "not armed"), 2 cannot run (config/state unreadable).

AUTHORITY: runs on the host as the registered lane ``self-heal-fixer`` (never from n8n; no n8n allowlist row). It never
merges, releases, edits crontab/systemd, touches broker code or credentials, or writes the production DB. The model
edits files in a throwaway worktree only; the harness checks the diff, runs the tests, commits, and (only with the
AGENTS.md 24.11 amendment ACTIVE and an operator grant) pushes one branch and opens one PR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_fix_evaluator as E  # noqa: E402
from lib import self_heal_egress as EG  # noqa: E402
from lib import self_heal_fixer as F  # noqa: E402
from lib import self_heal_fixer_claims as C  # noqa: E402

CONFIG = ROOT / "config" / "self_heal_fixer.json"
REGISTRY = ROOT / "config" / "lane_registry.json"
CUTOVER_POLICY = ROOT / "config" / "lane_cutover_policy.json"


# ---------------------------------------------------------------- small I/O helpers


def _load_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _atomic_write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def state_root(environ) -> Path:
    return Path(environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def run(cmd: list[str], *, cwd: Optional[Path] = None, env: Optional[dict] = None, timeout: float = 600,
        stdin: Optional[str] = None) -> dict:
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, input=stdin, capture_output=True,
                           text=True, timeout=timeout)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        rc, out, err = 124, str(exc.stdout or ""), f"timeout after {timeout}s"
    except OSError as exc:
        rc, out, err = 127, "", f"{type(exc).__name__}: {exc}"
    return {"rc": rc, "out": out or "", "err": err or "", "seconds": round(time.monotonic() - t0, 1)}


def git(repo: Path, *args: str, env: Optional[dict] = None, timeout: float = 300) -> dict:
    return run(["git", "-C", str(repo), *args], env=env, timeout=timeout)


def _kind(path: str) -> Optional[str]:
    p = Path(path)
    return "dir" if p.is_dir() else ("file" if p.exists() else None)


# ---------------------------------------------------------------- read-only inputs


def failed_receipt(ledger: Path, lane: str, run_id: Optional[str] = None) -> Optional[dict]:
    """The failed run's receipt from the coordination ledger, opened read-only: the run the N8nCodeDefect@v1 record
    names (evidence.failed_run_id) when given, else the lane's newest RUN_FAILED."""
    if not ledger.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT receipt_json FROM runs WHERE run_id=? AND lane_id=?", (run_id, lane)).fetchone() \
                if run_id and run_id != "n/a" else None
            if not row:
                row = con.execute(
                    "SELECT receipt_json FROM runs WHERE lane_id=? AND state='RUN_FAILED' AND receipt_json IS NOT NULL "
                    "ORDER BY finished_at DESC LIMIT 1", (lane,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    try:
        rec = json.loads(row[0]) if row else None
    except (TypeError, ValueError):
        return None
    if isinstance(rec, dict):
        rec.pop("env_allowlist", None)  # env NAMES only, but never needed by the fixer
    return rec if isinstance(rec, dict) else None


def registry_row(lane: str) -> Optional[dict]:
    doc = _load_json(REGISTRY) or {}
    return next((r for r in doc.get("lanes") or [] if r.get("lane_id") == lane), None)


def operator_holds() -> dict:
    return (_load_json(CUTOVER_POLICY) or {}).get("holds") or {}


def default_grant_reader(tier: str) -> Optional[dict]:
    """Peek (never consume) the active guard grant of ``tier``."""
    try:
        from lib.guard_push_auth import _import_guard_ledger, approvals_dir

        gl = _import_guard_ledger()
        listed = gl.ledger_list(approvals_dir())
        if listed.get("state") not in {gl.VALID_EMPTY, gl.VALID_NONEMPTY}:
            return None
        rec = (listed.get("active") or {}).get(tier)
        return rec if isinstance(rec, dict) else None
    except Exception:  # noqa: BLE001 — an unreadable ledger arms nothing
        return None


def agents_text_at(repo: Path, ref: str) -> str:
    r = git(repo, "show", f"{ref}:AGENTS.md")
    return r["out"] if r["rc"] == 0 else ""


# ---------------------------------------------------------------- the attempt


def _probe(path: str) -> Optional[str]:
    """Filesystem probe for the agent sandbox: "link:<target>", "dir", "file" or None. stat only, never reads."""
    p = Path(path)
    if p.is_symlink():
        return "link:" + os.readlink(p)
    return "dir" if p.is_dir() else ("file" if p.exists() else None)


def checkout_digest(root: Path) -> str:
    """sha256 over every path, mode and content in a checkout INCLUDING its .git (only .git/index, a stat cache, is
    excluded). Taken before and after each harness test run: any write by a test to the checkout or its git admin
    data changes it."""
    h = hashlib.sha256()
    root = Path(root)
    for cur, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        rel_cur = os.path.relpath(cur, root)
        h.update(f"D {rel_cur}\n".encode())
        for name in sorted(files + [d for d in dirs if os.path.islink(os.path.join(cur, d))]):
            p = os.path.join(cur, name)
            rel = os.path.relpath(p, root)
            if rel == os.path.join(".git", "index"):
                continue
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                h.update(f"L {rel} {os.readlink(p)}\n".encode())
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as fh:
                    h.update(f"F {rel} {st.st_mode & 0o777:o} {hashlib.sha256(fh.read()).hexdigest()}\n".encode())
    return h.hexdigest()


class Attempt:
    """One fix job: the sandboxed agent, immutable candidate commits, harness test runs bound to them, and the
    ship step (local branch, or push + PR when allowed) that proves it ships exactly the evaluated commit."""

    def __init__(self, job: dict, evidence: dict, *, cfg: dict, environ: dict, now: Callable[[], datetime],
                 evidence_dir: Path, may_push: bool, backend: str):
        self.job, self.ev, self.cfg, self.environ, self.now = job, evidence, cfg, environ, now
        self.backend = backend
        self.dir = evidence_dir
        self.may_push = may_push
        r = cfg["repo"]
        self.repo = Path(r["repo_root"])
        self.py = r["python"]
        self.wt_root = Path(r["worktree_root"])
        self.base = evidence["base_sha"]
        tag = job["job_id"]
        #: the candidate worktree: the ONLY path the agent may write
        self.fix_wt = self.wt_root / tag
        #: fresh shared clones per evaluation run (red-first on base, targeted + CI on the candidate commit)
        self.eval_root = self.wt_root / f"{tag}-eval"
        self.scratch = self.wt_root / f"{tag}-state"
        #: the agent's throwaway HOME (its CLAUDE_CONFIG_DIR holds only the one scoped auth bind)
        self.agent_home = self.wt_root / f"{tag}-home"
        #: host side of the egress bridge (a unix socket, bound read-only into the agent sandbox)
        self.egress_dir = self.wt_root / f"{tag}-eg"
        #: The model's pytest wrapper lives OUTSIDE every sandbox-writable path, so a test cannot rewrite it.
        self.bindir = self.wt_root / f"{tag}-bin"
        self.pytest_cmd = str(self.bindir / "pytest")
        self.branch = F.branch_name(job, cfg, now())
        self.env = F.child_env(environ, cfg, scratch_state=str(self.scratch))
        self.asb = cfg.get("agent_sandbox") or {}
        self.sandbox: list[str] = []
        self.agent_prefix: list[str] = []
        self.agent_env: dict[str, str] = {}
        self.proxy_port: Optional[int] = None
        self.boundary: dict[str, Any] = {}

    def _backend_bins(self) -> list[str]:
        b = (self.cfg.get("backends") or {}).get(self.backend) or {}
        if b.get("kind") == "cli_stdin":
            return [str(b.get("bin"))]
        return [str(self.cfg["claude"]["bin"])]

    # -- worktrees + the agent's boundary
    def setup(self) -> Optional[str]:
        for d in (self.wt_root, self.scratch, self.eval_root, self.bindir, self.egress_dir, self.agent_home / ".claude"):
            d.mkdir(parents=True, exist_ok=True)
        a = git(self.repo, "worktree", "add", "-b", self.branch, str(self.fix_wt), self.base)
        if a["rc"] != 0:
            return f"worktree_add_failed:{a['err'][-200:]}"
        sb = self.cfg.get("sandbox") or {}
        if sb.get("enabled") and not os.access(str(sb.get("bwrap", "bwrap")), os.X_OK):
            return "sandbox_unavailable"
        home = self.environ.get("HOME") or str(Path.home())
        # harness test runs use eval_sandbox_prefix per checkout (see eval_run): allowlist filesystem, the checkout
        # and its .git read-only, only the scratch state writable, no network
        if self.asb.get("enabled"):
            if not os.access(str(self.asb.get("bwrap") or sb.get("bwrap", "bwrap")), os.X_OK):
                return "agent_sandbox_unavailable"
            binds, why = F.agent_auth_binds(self.cfg, home=home, agent_home=str(self.agent_home), probe=_probe)
            if not why.startswith("auth:"):
                return why
            for _src, dst, _rw in binds:  # an EMPTY mount point; the credential itself is never read or copied
                Path(dst).touch(exist_ok=True)
            allow = list(self.asb.get("egress_allow") or [])
            self.proxy_port = int(self.asb.get("proxy_port", 18977)) if allow else None
            self.agent_env = F.agent_env(self.environ, self.cfg, scratch_state=str(self.scratch),
                                         agent_home=str(self.agent_home), proxy_port=self.proxy_port)
            shutil.copyfile(Path(EG.__file__), self.bindir / "self_heal_egress.py")
            bins = sorted({os.path.realpath(b) for b in self._backend_bins()})
            self.agent_prefix = F.agent_sandbox_prefix(
                self.cfg, home=home, repo_root=str(self.repo), python_root=str(Path(self.py).parent.parent),
                extra_ro=[*bins, str(self.bindir), str(self.egress_dir)], fix_wt=str(self.fix_wt),
                agent_home=str(self.agent_home), scratch=str(self.scratch), auth_binds=binds, env=self.agent_env,
                probe=_probe)
            wrapper_env = {k: v for k, v in self.env.items() if k not in ("HOME", "PATH", "TMPDIR")}
            wrapper_env.update(HOME=str(self.scratch), PATH=self.agent_env["PATH"], TMPDIR="/tmp")
            wrapper = F.model_pytest_wrapper(python=self.py, env=wrapper_env, sandbox=[])
            self.boundary = {"agent_sandbox": True, "auth": why, "egress_allow": allow,
                             "writable": [str(self.fix_wt), str(self.agent_home), str(self.scratch)]}
        elif self.environ.get("TRADE_AI_CI") != "1":
            return "agent_sandbox_disabled"  # outside hermetic tests the agent NEVER runs unsandboxed
        else:
            wrapper = F.model_pytest_wrapper(
                python=self.py, env=self.env,
                sandbox=F.sandbox_prefix(self.cfg, home=home, repo_root=str(self.repo),
                                         writable=[self.fix_wt, self.scratch], existing=_kind))
            self.boundary = {"agent_sandbox": False, "why": "TRADE_AI_CI=1 hermetic test config"}
        w = Path(self.pytest_cmd)
        w.write_text(wrapper, encoding="utf-8")
        w.chmod(0o555)
        return None

    def teardown(self, *, keep_branch: bool) -> None:
        if self.fix_wt.exists():
            git(self.repo, "worktree", "remove", "--force", str(self.fix_wt))
        git(self.repo, "worktree", "prune")
        if not keep_branch:
            git(self.repo, "branch", "-D", self.branch)
        for d in (self.eval_root, self.scratch, self.bindir, self.agent_home, self.egress_dir):
            shutil.rmtree(d, ignore_errors=True)

    # -- the agent, inside its boundary
    def agent_cmd(self, argv: list[str]) -> list[str]:
        if not self.agent_prefix:
            return argv
        inner = [os.path.realpath(argv[0]), *argv[1:]]
        if self.proxy_port:
            inner = [self.py, "-I", str(self.bindir / "self_heal_egress.py"), "bridge", "--unix",
                     str(self.egress_dir / "s"), "--port", str(self.proxy_port), "--", *inner]
        return [*self.agent_prefix, *inner]

    def run_agent(self, argv: list[str], prompt: str) -> tuple[dict, Optional[dict]]:
        cmd = self.agent_cmd(argv)
        timeout = float(self.cfg["claude"]["timeout_s"])
        if self.agent_prefix and self.proxy_port:
            with EG.EgressProxy(str(self.egress_dir / "s"), self.asb.get("egress_allow") or []) as px:
                cr = run(cmd, cwd=self.fix_wt, env=self.env, timeout=timeout, stdin=prompt)
                return cr, px.summary()
        return run(cmd, cwd=self.fix_wt, env=self.env, timeout=timeout, stdin=prompt), None

    # -- the immutable candidate
    def _message(self) -> str:
        lane = self.job["lane"]
        exc = (self.ev.get("final_exception") or {}).get("type") or "code error"
        return (f"fix({lane}): self-heal fix for {exc} (job {self.job['job_id']})\n\n"
                f"Self-heal fixer job {self.job['job_id']}, signature {self.job['signature']}, incident "
                f"{self.job.get('incident_key')}. This exact commit (sha + tree) was evaluated by the harness: the "
                f"regression test fails on {self.base[:9]} and passes here, and run_cio_hardening_ci.py --profile pr "
                "is green, in fresh read-only checkouts of this commit.\n\n"
                + "\n".join(self.cfg["repo"]["commit_trailers"]) + "\n")

    def candidate(self) -> dict:
        """Stage the agent's worktree and write ONE commit object (parent = base) without moving any ref. Its sha
        and tree hash are what everything after this point is judged on."""
        git(self.fix_wt, "add", "-A")
        tree = git(self.fix_wt, "write-tree")
        if tree["rc"] != 0:
            return {"error": f"write_tree_failed:{tree['err'][-200:]}"}
        c = run(["git", "-C", str(self.fix_wt), "commit-tree", tree["out"].strip(), "-p", self.base, "-F", "-"],
                stdin=self._message(), timeout=60)
        if c["rc"] != 0:
            return {"error": f"commit_tree_failed:{c['err'][-200:]}"}
        sha = c["out"].strip()
        return {"commit_sha": sha, "tree_sha": self.tree_of(sha), "base_sha": self.base}

    def tree_of(self, commit: str) -> Optional[str]:
        r = git(self.repo, "rev-parse", "--verify", "-q", f"{commit}^{{tree}}")
        return r["out"].strip() if r["rc"] == 0 else None

    def commit_diff(self, commit: str) -> dict:
        ns = git(self.repo, "diff", "--name-status", "-M", self.base, commit)["out"]
        nm = git(self.repo, "diff", "--numstat", self.base, commit)["out"]
        u0 = git(self.repo, "diff", "-U0", self.base, commit)["out"]
        full = git(self.repo, "diff", self.base, commit)["out"]
        return {"name_status": ns, "numstat": nm, "unified": u0, "full": full}

    def guard(self, d: dict) -> list[dict]:
        base_ci = git(self.repo, "show", f"{self.base}:scripts/run_cio_hardening_ci.py")["out"]
        return F.guard_diff(name_status=d["name_status"], numstat=d["numstat"], unified=d["unified"],
                            base_ci_text=base_ci, cfg=self.cfg)

    # -- harness test runs, bound to the candidate
    def _blob(self, commit: str, path: str) -> Optional[bytes]:
        try:
            p = subprocess.run(["git", "-C", str(self.repo), "cat-file", "blob", f"{commit}:{path}"],
                               capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return p.stdout if p.returncode == 0 else None

    def checkout(self, name: str, sha: str, overlay: Optional[dict[str, bytes]] = None) -> Optional[Path]:
        """A FRESH shared clone at ``sha`` (its own .git; objects via alternates), optionally with files overlaid.
        Nothing else ever touches it, so its digest is exactly what the run saw."""
        d = self.eval_root / name
        shutil.rmtree(d, ignore_errors=True)
        c = git(self.repo, "clone", "-q", "--shared", "--no-checkout", str(self.repo), str(d))
        if c["rc"] != 0:
            return None
        co = git(d, "-c", "core.hooksPath=/dev/null", "-c", "advice.detachedHead=false", "checkout", "-q",
                 "--detach", sha)
        if co["rc"] != 0:
            return None
        for rel, data in (overlay or {}).items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return d

    def eval_run(self, kind: str, co: Optional[Path], expect: str, argv: list[str], timeout: float,
                 overlay_from: Optional[str] = None) -> dict:
        rid = f"{kind}-{uuid.uuid4().hex[:12]}"
        if co is None:
            return {"run_id": rid, "kind": kind, "rc": None, "out": "", "err": "checkout_failed",
                    "integrity_ok": False, "checkout_sha": None, "head_after": None, "overlay_from": overlay_from}
        head_before = git(co, "rev-parse", "HEAD")["out"].strip()
        before = checkout_digest(co)
        eval_env = {**self.env, "HOME": str(self.scratch), "TMPDIR": "/tmp"}
        prefix = F.eval_sandbox_prefix(self.cfg, repo_root=str(self.repo), python_root=str(Path(self.py).parent.parent),
                                       checkout=str(co), scratch=str(self.scratch), env=eval_env, probe=_probe)
        r = run([*prefix, *argv], cwd=co, env=eval_env if prefix else self.env, timeout=timeout)
        after = checkout_digest(co)
        head_after = git(co, "rev-parse", "HEAD")["out"].strip()
        ok = before == after and head_before == expect and head_after == expect
        return {"run_id": rid, "kind": kind, "rc": r["rc"], "out": r["out"], "err": r["err"], "seconds": r["seconds"],
                "checkout": str(co), "checkout_sha": head_before, "head_after": head_after,
                "digest_before": before[:16], "digest_after": after[:16], "integrity_ok": ok,
                "overlay_from": overlay_from}

    # -- one iteration
    def iterate(self, k: int, prev: Optional[dict], rails: str, spent: float) -> dict:
        it = self.cfg["iteration"]
        budget = min(float(it["per_iteration_budget_usd"]), max(0.0, float(it["max_cost_usd"]) - spent))
        prompt = F.build_prompt(self.ev, rails=rails, cfg=self.cfg, iteration=k, prev=prev,
                                pytest_cmd=self.pytest_cmd)
        (self.dir / f"prompt_iter{k}.md").write_text(prompt, encoding="utf-8")
        t0 = time.monotonic()
        argv = F.backend_argv(self.cfg, self.backend, budget_usd=budget, pytest_cmd=self.pytest_cmd)
        cr, egress = self.run_agent(argv, prompt)
        res = F.parse_backend_result(self.cfg, self.backend, cr["out"])
        res.update(rc=cr["rc"], stderr_tail=cr["err"][-500:], egress=egress)
        (self.dir / f"backend_iter{k}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        rec: dict[str, Any] = {"iteration": k, "backend": self.backend, "boundary": self.boundary,
                               # recorded for the operator, NEVER read by the evaluator (claims are not evidence)
                               "backend_result": {key: res.get(key) for key in ("ok", "cost_usd", "num_turns",
                                                                                "subtype", "summary", "rc")}}
        cand = self.candidate()
        if cand.get("error"):
            rec.update(candidate=cand, refusals=[], failing=[f"candidate:{cand['error']}"], tests_run=[],
                       red_first=None, test_runs=[], diffstat=F.diffstat(""))
            rec["seconds"], rec["output_tail"] = round(time.monotonic() - t0, 1), ""
            rec["acceptance"] = E.local_verdict(rec)
            rec["passed"] = rec["acceptance"]["accepted"]
            return rec
        commit = cand["commit_sha"]
        d = self.commit_diff(commit)
        patch = self.dir / f"diff_iter{k}.patch"
        patch.write_text(d["full"], encoding="utf-8")
        refusals = self.guard(d)
        rec.update(candidate=cand, guard={"tree_sha": self.tree_of(commit), "refusals": refusals},
                   diffstat=F.diffstat(d["numstat"]), diff_sha256=hashlib.sha256(d["full"].encode()).hexdigest()[:16],
                   patch=str(patch), refusals=list(refusals))
        tests = F.changed_tests(d["name_status"])
        rec["tests_run"] = tests
        rec["test_runs"] = []
        out_tail = ""
        if any(r["hard"] for r in refusals):
            rec.update(passed=False, failing=[f"guard:{r['code']}" for r in refusals], red_first=None)
        elif refusals:
            rec.update(passed=False, failing=sorted(f"guard:{r['code']}" for r in refusals), red_first=None)
            out_tail = json.dumps(refusals)
        else:
            pyt = [self.py, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", *tests]
            t_test = float(it["test_timeout_s"])
            overlay = {t: self._blob(commit, t) or b"" for t in tests}
            red = self.eval_run("red_first", self.checkout(f"it{k}-base", self.base, overlay), self.base, pyt,
                                t_test, overlay_from=commit)
            reproduced = red["rc"] not in (0, 5, None)
            co = self.checkout(f"it{k}-cand", commit)
            green = self.eval_run("targeted", co, commit, pyt, t_test)
            runs = [red, green]
            ci_argv = [str(a).replace("{python}", self.py).replace("{base_sha}", self.base) for a in it["ci_argv"]]
            if green["rc"] == 0 and reproduced and red["integrity_ok"] and green["integrity_ok"]:
                ci = self.eval_run("ci", co, commit, ci_argv, float(it["ci_timeout_s"]))
                runs.append(ci)
            else:
                ci = {"rc": None, "out": "", "err": "skipped"}
            for r in runs:
                if not r["integrity_ok"]:
                    rec["refusals"].append({"hard": True, "code": "integrity:checkout_or_git_mutated",
                                            "run": r["kind"], "run_id": r["run_id"]})
            if self.tree_of(commit) != cand["tree_sha"]:
                rec["refusals"].append({"hard": True, "code": "integrity:candidate_tree_changed"})
            failing = F.failing_set(green["out"], ci["out"])
            if not reproduced:
                failing.append("red_first:test_passes_on_base")
            if green["rc"] != 0 and not F.failing_set(green["out"]):
                failing.append(f"targeted:exit_{green['rc']}")
            if ci["rc"] not in (0, None) and not F.failing_set(ci["out"]):
                failing.append(f"ci:exit_{ci['rc']}")
            failing += [f"guard:{r['code']}" for r in rec["refusals"]]
            rec.update(red_first=reproduced, targeted_rc=green["rc"], ci_rc=ci["rc"], ci_argv=ci_argv,
                       failing=sorted(set(failing)),
                       test_runs=[{k2: v for k2, v in r.items() if k2 not in ("out", "err")} for r in runs])
            out_tail = (f"--- red-first on base (rc {red['rc']}) ---\n{red['out'][-1500:]}\n"
                        f"--- targeted (rc {green['rc']}) ---\n{green['out'][-2500:]}\n"
                        f"--- ci pr profile (rc {ci['rc']}) ---\n{ci['out'][-3000:]}{ci['err'][-500:]}")
            (self.dir / f"tests_iter{k}.log").write_text(out_tail, encoding="utf-8")
            shutil.rmtree(self.eval_root / f"it{k}-base", ignore_errors=True)
            shutil.rmtree(self.eval_root / f"it{k}-cand", ignore_errors=True)
        rec["seconds"] = round(time.monotonic() - t0, 1)
        rec["output_tail"] = out_tail
        rec["acceptance"] = E.local_verdict(rec)          # independent of the backend's claims
        rec["passed"] = rec["acceptance"]["accepted"]
        return rec

    # -- ship exactly the evaluated commit
    def prepush_check(self, rec: dict) -> dict:
        """Immediately before the branch update / push: the commit's tree is re-read from the object store and the
        diff guard re-run on it. The ship verdict refuses unless sha, tree and guard all match the evaluation."""
        commit = str((rec.get("candidate") or {}).get("commit_sha") or "")
        tree_now = self.tree_of(commit) if commit else None
        refusals = self.guard(self.commit_diff(commit)) if commit else [{"code": "no_candidate"}]
        return E.ship_verdict(rec.get("acceptance"), commit_sha=commit, tree_sha=tree_now or "",
                              prepush_refusals=refusals)

    def land_local(self, commit: str) -> dict:
        """Point the job branch at the evaluated commit (compare-and-swap from base) and write fix.patch from it."""
        r = git(self.repo, "update-ref", f"refs/heads/{self.branch}", commit, self.base)
        patch = git(self.repo, "format-patch", "-1", "--stdout", commit)["out"]
        (self.dir / "fix.patch").write_text(patch, encoding="utf-8")
        return {"rc": r["rc"], "head": commit, "err": r["err"][-300:]}

    def push_and_pr(self, body: str, commit: str, gh_view: Optional[Callable[[list[str]], dict]] = None) -> dict:
        env = dict(self.environ)
        env.pop("TRADEAI_REMOTE_PUSH_OVERRIDE", None)  # never an override: the budget binds
        env["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "1"
        # push the evaluated SHA itself, never "whatever the branch points at now"
        p = run(["git", "-C", str(self.fix_wt), "push", self.cfg["repo"]["remote"], f"{commit}:refs/heads/{self.branch}"],
                env=env, timeout=600)
        if p["rc"] != 0:
            return {"ok": False, "why": f"push_failed:{(p['err'] or p['out'])[-300:]}"}
        body_path = self.dir / "pr_body.md"
        body_path.write_text(body, encoding="utf-8")
        title = f"fix({self.job['lane']}): self-heal fix ({self.job['job_id']})"
        base_args = ["gh", "pr", "create", "--base", self.cfg["repo"]["base_branch"], "--head", self.branch,
                     "--title", title, "--body-file", str(body_path)]
        pr = run(base_args + ["--label", self.cfg["repo"]["pr_label"]], cwd=self.fix_wt, env=env, timeout=120)
        label = True
        if pr["rc"] != 0:
            label = False
            pr = run(base_args, cwd=self.fix_wt, env=env, timeout=120)
        if pr["rc"] != 0:
            return {"ok": False, "why": f"pr_create_failed:{pr['err'][-300:]}", "pushed": True}
        url = pr["out"].strip().splitlines()[-1] if pr["out"].strip() else ""
        num = url.rstrip("/").rsplit("/", 1)[-1]
        out = {"ok": True, "pr_url": url, "pr_number": int(num) if num.isdigit() else None, "labelled": label}
        # the PR head MUST be the evaluated commit
        view = run(["gh", "pr", "view", url or self.branch, "--json", "headRefOid"], cwd=self.fix_wt, env=env,
                   timeout=60)
        try:
            head = str(json.loads(view["out"] or "{}").get("headRefOid") or "")
        except ValueError:
            head = ""
        out["pr_head"] = head
        if head != commit:
            out.update(ok=False, why=f"pr_head_mismatch:{head[:12] or 'unreadable'}!={commit[:12]}", pushed=True,
                       head_mismatch=True)
        return out


def attempt_job(job: dict, evidence: dict, *, cfg: dict, environ: dict, now: Callable[[], datetime],
                evidence_dir: Path, may_push: bool, rails: str, backend: str,
                remember: Callable[[dict], None] = lambda row: None,
                persist: Callable[[dict], None] = lambda job: None,
                progress: Callable[[dict, dict], None] = lambda job, rec: None) -> dict:
    """Run the iteration loop for one job and move it to its next state. Returns the job. ``persist`` makes the job
    durable (called before the backend first runs and after every iteration); ``progress`` records partial evidence
    on the durable claim."""
    a = Attempt(job, evidence, cfg=cfg, environ=environ, now=now, evidence_dir=evidence_dir, may_push=may_push,
                backend=backend)
    job["backend"] = backend
    it = cfg["iteration"]
    start = time.monotonic()
    job["attempt_started_at"] = now().isoformat()
    job["branch"] = a.branch
    job["evidence_dir"] = str(evidence_dir)
    job["worktrees"] = [str(a.fix_wt), str(a.eval_root)]
    F.transition(job, F.FIX_ATTEMPTING, now(), iteration=0, updated_at=now().isoformat())
    persist(job)
    err = a.setup()
    if err:
        F.transition(job, F.FIX_FAILED, now(), reason=err, updated_at=now().isoformat())
        a.teardown(keep_branch=False)
        return job
    job["boundary"] = a.boundary
    prev, passed, stop, last = None, False, "max_iterations", None
    for k in range(1, int(it["max_iterations"]) + 1):
        if time.monotonic() - start > float(it["max_minutes"]) * 60:
            stop = "time_budget"
            break
        if float(job.get("cost_usd") or 0) >= float(it["max_cost_usd"]):
            stop = "cost_budget"
            break
        F.transition(job, F.FIX_ATTEMPTING, now(), iteration=k, updated_at=now().isoformat())
        persist(job)
        rec = a.iterate(k, prev, rails, float(job.get("cost_usd") or 0))
        job["cost_usd"] = round(float(job.get("cost_usd") or 0) + float(rec["backend_result"].get("cost_usd") or 0), 4)
        job["iterations"].append({k2: v for k2, v in rec.items() if k2 != "output_tail"})
        remember(F.memory_row(job, event="iteration", now=now(), backend=backend, iteration=rec))
        progress(job, rec)
        persist(job)
        last = rec
        if any(r["hard"] for r in rec["refusals"]):
            stop = "guard_refused"
            break
        if rec["passed"]:
            passed = True
            break
        if F.no_progress(job["iterations"], int(it["stop_on_same_failing_set"])):
            stop = "no_progress"
            break
        prev = rec
    if passed and last is not None:
        ship = a.prepush_check(last)
        job["ship_check"] = ship
        if not ship["accepted"]:
            F.transition(job, F.FIX_REFUSED, now(), reason=f"ship_check_failed:{','.join(ship['failed'])}",
                         updated_at=now().isoformat())
            a.teardown(keep_branch=False)
            return job
        commit = ship["commit_sha"]
        c = a.land_local(commit)
        if c["rc"] != 0:
            F.transition(job, F.FIX_FAILED, now(), reason=f"branch_update_failed:{c['err']}",
                         updated_at=now().isoformat())
            a.teardown(keep_branch=False)
            return job
        job["head_sha"] = commit
        job["evaluated"] = {"commit_sha": commit, "tree_sha": ship["tree_sha"],
                            "test_run_ids": last["acceptance"].get("test_run_ids"),
                            "guard_verdict": last["acceptance"].get("guard_verdict")}
        body = F.pr_body(job, evidence)
        (evidence_dir / "pr_body.md").write_text(body, encoding="utf-8")
        if may_push:
            pr = a.push_and_pr(body, commit)
            if pr.get("ok"):
                F.transition(job, F.FIX_PR_OPENED, now(), pr_url=pr["pr_url"], pr_number=pr["pr_number"],
                             labelled=pr["labelled"], pr_head=pr.get("pr_head"), updated_at=now().isoformat())
            elif pr.get("head_mismatch"):
                F.transition(job, F.FIX_REFUSED, now(), reason=pr["why"], pr_url=pr.get("pr_url"),
                             pr_number=pr.get("pr_number"), pr_head=pr.get("pr_head"), updated_at=now().isoformat())
            else:
                F.transition(job, F.FIX_READY_LOCAL, now(), reason=pr["why"], updated_at=now().isoformat())
        else:
            F.transition(job, F.FIX_READY_LOCAL, now(), reason="push_not_allowed", updated_at=now().isoformat())
        a.teardown(keep_branch=True)
        return job
    new = F.FIX_REFUSED if stop == "guard_refused" else F.FIX_FAILED
    F.transition(job, new, now(), reason=stop, updated_at=now().isoformat())
    a.teardown(keep_branch=False)
    return job


# ---------------------------------------------------------------- output recovered (one swappable hook)


def recovery_contract(cfg: dict, root: Path) -> dict:
    """The output contract ``output_recovered`` applies (architect review 2026-10-16, finding 4)."""
    return {"kind": "live_receipt_output_verdict@v1", "ledger": str(root / cfg["intake"]["ledger_rel"]),
            "output_verdicts": sorted(F.OUTPUT_MET), "effective_mode": "live", "state": "RUN_DONE", "exit_code": 0}


def output_recovered(lane: str, since: Optional[datetime], contract: dict) -> dict:
    """Did ``lane``'s OUTPUT recover after ``since`` by its contract? The ONLY recovery check the fixer makes.

    TODO(recovery-validator): one shared recovery validator is being built in ``scripts/lib/recovery_validator.py``
    (architect review 2026-10-16, finding 4). It was not on main when this landed. When it is, replace this body with
    a call to it; every caller already goes through this one function, so the swap is one edit here.

    Until then, conservatively: a LIVE ``RUN_DONE`` receipt in the coordination ledger (opened read-only), exit 0,
    effective mode live (no stage-clamp downgrade), finished after ``since``, whose ``output_verdict`` is produced or
    empty_allowed (lib/self_heal_fixer.receipt_meets_output_contract). A newer file mtime or JSON timestamp never
    counts. A lane with no such receipt (for example one still run by host cron) stays ``fix_deployed``."""
    base = {"validator": "self_heal_fixer.output_recovered@conservative-v1", "contract": contract.get("kind"),
            "lane": lane, "since": since.isoformat() if since else None, "recovered": False}
    ledger = Path(str(contract.get("ledger") or ""))
    if since is None:
        return {**base, "why": "no_deployed_at"}
    if not ledger.is_file():
        return {**base, "why": "ledger_missing"}
    try:
        con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT run_id, mode, state, exit_code, finished_at, receipt_json FROM runs "
                               "WHERE lane_id=? AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 200",
                               (lane,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {**base, "why": f"ledger_unreadable:{type(exc).__name__}"}
    reasons: dict[str, int] = {}
    for run_id, mode, state, exit_code, finished_at, receipt_json in rows:
        try:
            rec = json.loads(receipt_json) if receipt_json else {}
        except ValueError:
            rec = {}
        why = F.receipt_meets_output_contract({"run_id": run_id, "mode": mode, "state": state, "exit_code": exit_code,
                                               "finished_at": finished_at,
                                               "receipt": rec if isinstance(rec, dict) else {}}, since)
        if why is None:
            return {**base, "recovered": True, "basis": "live_receipt_output_verdict", "run_id": run_id,
                    "finished_at": finished_at, "output_verdict": (rec.get("output_verdict") or {}).get("verdict")}
        reasons[why] = reasons.get(why, 0) + 1
    return {**base, "why": "no_receipt_meets_contract", "checked": len(rows), "reasons": reasons}


# ---------------------------------------------------------------- lifecycle advance (read-only probes)


def advance(job: dict, *, cfg: dict, now: datetime, diag_state: Optional[dict], root: Path,
            gh: Callable[[list[str]], dict], repo: Path) -> Optional[str]:
    """Move a shipped job along fix_pr_opened -> fix_deployed -> output_recovered -> incident_resolved."""
    st = job.get("state")
    if st == F.FIX_READY_LOCAL and job.get("branch"):
        r = gh(["gh", "pr", "list", "--head", job["branch"], "--state", "all", "--json", "number,url"])
        rows = json.loads(r["out"] or "[]") if r["rc"] == 0 else []
        if rows:
            F.transition(job, F.FIX_PR_OPENED, now, pr_number=rows[0].get("number"), pr_url=rows[0].get("url"),
                         updated_at=now.isoformat(), opened_by="operator")
            return F.FIX_PR_OPENED
    if st == F.FIX_PR_OPENED and job.get("pr_number"):
        r = gh(["gh", "pr", "view", str(job["pr_number"]), "--json",
                "state,mergeCommit,mergedAt,headRefOid,statusCheckRollup"])
        doc = json.loads(r["out"] or "{}") if r["rc"] == 0 else {}
        if doc:
            local = next((i.get("acceptance") for i in reversed(job.get("iterations") or []) if i.get("passed")), None)
            prv = E.pr_head_verdict(doc, expected_head=str(job.get("head_sha") or ""))
            job["acceptance"] = E.final_acceptance(local, prv)
            job["acceptance"]["pr_head"] = prv
        if doc.get("state") == "CLOSED":
            F.transition(job, F.FIX_CLOSED, now, reason="pr_closed_unmerged", updated_at=now.isoformat())
            return F.FIX_CLOSED
        merge = (doc.get("mergeCommit") or {}).get("oid")
        if doc.get("state") == "MERGED" and merge:
            job["merged_sha"], job["merged_at"] = merge, doc.get("mergedAt")
            cur = Path(cfg["lifecycle"]["release_current_sha_file"])
            try:
                cur_sha = cur.read_text(encoding="utf-8").strip()
            except OSError:
                cur_sha = ""
            if cur_sha and git(repo, "merge-base", "--is-ancestor", merge, cur_sha)["rc"] == 0:
                F.transition(job, F.FIX_DEPLOYED, now, release_sha=cur_sha, deployed_at=now.isoformat(),
                             updated_at=now.isoformat())
                return F.FIX_DEPLOYED
        return None
    if st == F.FIX_DEPLOYED:
        rv = output_recovered(job["lane"], F._parse(job.get("deployed_at")), recovery_contract(cfg, root))
        job["recovery_check"] = rv
        if rv.get("recovered"):
            F.transition(job, F.OUTPUT_RECOVERED, now, output_at=rv.get("finished_at"), output_run=rv.get("run_id"),
                         recovery_basis=rv.get("basis"), updated_at=now.isoformat())
            return F.OUTPUT_RECOVERED
        return None
    if st == F.OUTPUT_RECOVERED:
        esc = ((diag_state or {}).get("escalations") or {}).get(job.get("escalation_key") or "")
        if not esc or esc.get("heal_state") in ("output_recovered", "incident_resolved"):
            F.transition(job, F.INCIDENT_RESOLVED, now, updated_at=now.isoformat())
            return F.INCIDENT_RESOLVED
    return None


# ---------------------------------------------------------------- escalation (written, never sent)


def escalation_for(job: dict, now: datetime) -> dict:
    tried = [{"k": r.get("iteration"), "failing": (r.get("failing") or [])[:6], "passed": r.get("passed"),
              "refusals": [x.get("code") for x in r.get("refusals") or []]} for r in job.get("iterations") or []]
    return {"schema": "SelfHealFixEscalation@v1", "priority": "P1", "route": "operator_once",
            "job_id": job["job_id"], "lane": job["lane"], "signature": job["signature"],
            "incident_key": job.get("incident_key"), "state": job["state"],
            "reason": job.get("reason") or (job.get("refusal") or ["?"])[0],
            "detail": f"self-heal fixer could not ship a fix for {job['lane']}: {job.get('reason')}; "
                      f"iterations={len(tried)}; cost=${job.get('cost_usd', 0):.2f}",
            "tried": tried, "at": now.isoformat()}


# ---------------------------------------------------------------- incident intake


def _tail_jsonl(path: Path, n: int) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def incidents_from(args, cfg: dict, root: Path) -> tuple[list[dict], Optional[dict]]:
    """(incidents, diag_state). Production intake = N8nCodeDefect@v1 records (diagnoses store + escalations). An
    --incident file carries one record (``code_defect``) plus its receipt and registry row."""
    i = cfg["intake"]
    if args.incident:
        doc = _load_json(Path(args.incident)) or {}
        found = F.code_defects([doc], None, cfg)
        if not found:
            return [], None
        inc = found[0]
        inc["_receipt"] = doc.get("receipt")
        inc["_registry_row"] = doc.get("registry_row")
        return [inc], None
    diag = _load_json(root / i["diagnosis_state_rel"])
    records = _tail_jsonl(root / i["diagnoses_rel"], int(i.get("diagnoses_tail_lines", 5000)))
    return F.code_defects(records, diag, cfg), diag


def main(argv: Optional[list[str]] = None, *, now: Optional[Callable[[], datetime]] = None,
         grant_reader: Callable[[str], Optional[dict]] = default_grant_reader,
         environ: Optional[dict] = None, gh: Optional[Callable[[list[str]], dict]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cycle", action="store_true", help="intake -> attempt (max_jobs_per_cycle) -> advance")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--apply", action="store_true", help="live: write state, run claude, commit/push (when armed)")
    ap.add_argument("--dry-run", action="store_true", help="default; explicit for cron argv symmetry")
    ap.add_argument("--incident", help="intake from one incident file instead of the diagnoser state")
    ap.add_argument("--out", help="dry run: write job/evidence/prompt/plan here")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args(argv)
    environ = dict(os.environ if environ is None else environ)
    now = now or (lambda: datetime.now(timezone.utc))
    gh = gh or (lambda cmd: run(cmd, timeout=60))
    cfg = _load_json(Path(args.config))
    if not cfg or cfg.get("schema") != "SelfHealFixerConfig@v1":
        print(json.dumps({"ok": False, "why": "config unreadable"}))
        return 2
    apply = bool(args.apply) and not args.dry_run
    root = state_root(environ)
    s = cfg["state"]
    state_path, receipt_path = root / s["state_rel"], root / s["receipt_rel"]
    claims_db = root / s.get("claims_rel", "data/runtime/self_heal_fixer_claims.sqlite")
    if args.status:
        state = _load_json(state_path) or {"schema": F.STATE_SCHEMA, "jobs": {}}
        rows = [{k: j.get(k) for k in ("job_id", "lane", "state", "pr_url", "cost_usd", "updated_at")}
                for j in state.get("jobs", {}).values()]
        print(json.dumps({"jobs": rows, "claims": [{k: c.get(k) for k in ("claim_id", "job_id", "state", "day",
                                                                          "reserved_usd", "spent_usd", "outcome")}
                                                   for c in C.rows(claims_db)]}, indent=1))
        return 0
    if not args.cycle:
        ap.print_help()
        return 0
    # ONE live cycle per state root at a time (finding 3): a second --apply exits "busy" before reading any state.
    lock = C.CycleLock(root / s.get("lock_rel", "data/runtime/self_heal_fixer.lock")) if apply else None
    if lock is not None and not lock.acquire():
        print(json.dumps({"mode": "apply", "busy": True, "why": "another self-heal-fixer cycle holds the lock"}))
        return 0
    try:
        return _cycle(args, cfg=cfg, apply=apply, root=root, state_path=state_path, receipt_path=receipt_path,
                      claims_db=claims_db, environ=environ, now=now, grant_reader=grant_reader, gh=gh)
    finally:
        if lock is not None:
            lock.release()


def _cycle(args, *, cfg: dict, apply: bool, root: Path, state_path: Path, receipt_path: Path, claims_db: Path,
           environ: dict, now: Callable[[], datetime], grant_reader: Callable[[str], Optional[dict]],
           gh: Callable[[list[str]], dict]) -> int:
    s = cfg["state"]
    lease = cfg.get("lease") or {}
    lease_ttl, beat_every = float(lease.get("ttl_s", 300)), float(lease.get("heartbeat_s", 60))
    state = _load_json(state_path) or {"schema": F.STATE_SCHEMA, "jobs": {}}
    t = now()
    repo = Path(cfg["repo"]["repo_root"])
    out: dict[str, Any] = {"schema": F.RECEIPT_SCHEMA, "mode": "apply" if apply else "dry_run",
                           "started_at": t.isoformat(), "admitted": [], "skipped": [], "attempted": [],
                           "advanced": [], "escalations": [], "reconciled": []}
    work = state if apply else json.loads(json.dumps(state))

    def save() -> None:
        if apply:
            _atomic_write(state_path, work)

    memory_path = root / s["repair_memory_rel"]
    memory_old = _tail_jsonl(memory_path, 20000)
    memory_new: list[dict] = []

    def remember(row: dict) -> None:
        memory_new.append(row)
        if apply:  # durable immediately: a crash keeps every row written so far
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            with memory_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    # restart reconciliation (finding 3): a dead owner's attempt becomes fix_interrupted, never restarted blindly
    if apply:
        for c in C.reconcile(claims_db):
            job = work.get("jobs", {}).get(c["job_id"])
            row = {"claim_id": c["claim_id"], "job_id": c["job_id"], "why": c["why"]}
            if job and job.get("state") in (F.FIX_ATTEMPTING, F.FIX_REQUESTED):
                F.transition(job, F.FIX_INTERRUPTED, t, reason=f"interrupted:{c['why']}", interrupted=c,
                             updated_at=t.isoformat())
                remember(F.memory_row(job, event="attempt_interrupted", now=t, backend=job.get("backend"),
                                      reason=c["why"], partial=c.get("partial"),
                                      reserved_usd_counted=c.get("reserved_usd_counted")))
                out["escalations"].append(escalation_for(job, t))
                job["escalated_at"] = t.isoformat()
                row["job_state"] = job["state"]
            out["reconciled"].append(row)
        save()
    incidents, diag = incidents_from(args, cfg, root)
    held = operator_holds()
    ledger = root / cfg["intake"]["ledger_rel"]
    ev_by_job: dict[str, dict] = {}
    for inc in incidents:
        lane = str(inc.get("lane") or "")
        rc = inc.pop("_receipt", None) or failed_receipt(ledger, lane, inc.get("failed_run_id"))
        row = inc.pop("_registry_row", None) or registry_row(lane)
        if rc and not inc.get("stderr_tail"):
            inc["stderr_tail"] = rc.get("stderr_tail")
        inc.setdefault("script", F.script_from_argv((rc or {}).get("argv") or [])
                       or ((row or {}).get("scheduler") or {}).get("match"))
        job, why = F.admit(work, inc, now=t, cfg=cfg, held=held)
        if not job:
            out["skipped"].append({"lane": lane, "why": why})
            continue
        out["admitted"].append({"job_id": job["job_id"], "lane": lane, "state": job["state"], "why": why,
                                "defect_id": job.get("defect_id")})
        remember(F.memory_row(job, event="consumed", now=t, backend=None, contract=job.get("contract")))
        ev_by_job[job["job_id"]] = {"incident": inc, "receipt": rc, "row": row}
        if job["state"] == F.FIX_REFUSED:
            out["escalations"].append(escalation_for(job, t))
            job["escalated_at"] = t.isoformat()
    save()
    # arming + policy
    fetch = git(repo, "fetch", "-q", cfg["repo"]["remote"], cfg["repo"]["base_branch"]) if apply else {"rc": 0}
    base_sha = git(repo, "rev-parse", f"{cfg['repo']['remote']}/{cfg['repo']['base_branch']}")["out"].strip()
    agents = agents_text_at(repo, base_sha) if base_sha else ""
    grant = grant_reader(cfg["arming"]["grant_tier"])
    day = F.et_day(t)

    def jobs_today() -> int:
        ledger_jobs = C.day_usage(claims_db, day)["jobs"] if apply else 0
        return max(F.jobs_started_today(work, now()), ledger_jobs)

    arming = F.arming_verdict(grant, cfg=cfg, jobs_today=jobs_today())
    policy = F.policy_verdict(agents, cfg)
    backend, backend_why = F.select_backend(cfg)
    out.update(arming=arming, policy=policy, base_sha=base_sha, fetch_rc=fetch["rc"],
               backend={"name": backend, "why": backend_why})
    names = [n for n in (cfg.get("backends") or {}) if not n.startswith("_")]
    queue = [j for j in work.get("jobs", {}).values() if j.get("state") == F.FIX_REQUESTED]
    queue.sort(key=lambda j: str(j.get("created_at")))
    it = cfg["iteration"]
    for job in queue[: int(cfg["arming"]["max_jobs_per_cycle"])]:
        src = ev_by_job.get(job["job_id"]) or {"incident": {"lane": job["lane"], "key": job.get("escalation_key")},
                                               "receipt": failed_receipt(ledger, job["lane"],
                                                                         job.get("failed_run_id")),
                                               "row": registry_row(job["lane"])}
        evidence = F.build_evidence(job, incident=src["incident"], receipt=src["receipt"], registry_row=src["row"],
                                    base_sha=base_sha, cfg=cfg)
        try:
            rails = F.extract_rails(agents)
        except ValueError as exc:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"no_rails:{exc}"})
            continue
        if not backend:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"no_backend:{backend_why}"})
            continue
        job["shadow_route"] = F.shadow_route(memory_old + memory_new, failure_kind=job.get("failure_kind"),
                                             backends=names, chosen=backend)
        if not apply:
            wt = Path(cfg["repo"]["worktree_root"])
            pytest_cmd = str(wt / f"{job['job_id']}-bin" / "pytest")
            home = environ.get("HOME") or str(Path.home())
            ah = str(wt / f"{job['job_id']}-home")
            asb = cfg.get("agent_sandbox") or {}
            binds, auth_why = F.agent_auth_binds(cfg, home=home, agent_home=ah, probe=_probe)
            plan = {"job": job, "evidence": evidence, "backend": backend,
                    "backend_argv": F.backend_argv(cfg, backend, budget_usd=float(
                        cfg["iteration"]["per_iteration_budget_usd"]), pytest_cmd=pytest_cmd),
                    "backend_call": "STUBBED (dry run: no model call)",
                    "sandbox_prefix": F.eval_sandbox_prefix(
                        cfg, repo_root=str(repo), python_root=str(Path(cfg["repo"]["python"]).parent.parent),
                        checkout="<eval-checkout>", scratch="<scratch>", env={"<env>": "<child_env_names>"},
                        probe=_probe),
                    "agent_sandbox_prefix": F.agent_sandbox_prefix(
                        cfg, home=home, repo_root=str(repo), python_root=str(Path(cfg["repo"]["python"]).parent.parent),
                        extra_ro=["<claude-bin>", "<bindir>", "<egress-dir>"], fix_wt="<fix_wt>", agent_home=ah,
                        scratch="<scratch>", auth_binds=binds, env={"<env>": "<agent_env_names>"}, probe=_probe),
                    "agent_auth": auth_why,
                    "agent_env_names": sorted(F.agent_env(environ, cfg, scratch_state="<scratch>", agent_home=ah,
                                                          proxy_port=asb.get("proxy_port"))),
                    "egress_allow": asb.get("egress_allow"),
                    "budget_reservation": {"iterations": it["max_iterations"], "usd": it["max_cost_usd"],
                                           "seconds": float(it["max_minutes"]) * 60},
                    "branch": F.branch_name(job, cfg, t), "would_push": bool(arming["armed"] and policy["push_allowed"]),
                    "env_names": sorted(F.child_env(environ, cfg, scratch_state="<scratch>"))}
            prompt = F.build_prompt(evidence, rails=rails, cfg=cfg, iteration=1, pytest_cmd=pytest_cmd)
            if args.out:
                od = Path(args.out)
                od.mkdir(parents=True, exist_ok=True)
                (od / "job.json").write_text(json.dumps(job, indent=1, default=str) + "\n", encoding="utf-8")
                (od / "evidence.json").write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
                (od / "prompt_iter1.md").write_text(prompt, encoding="utf-8")
                (od / "plan.json").write_text(json.dumps(plan, indent=1, default=str) + "\n", encoding="utf-8")
            out["attempted"].append({"job_id": job["job_id"], "outcome": "dry_run_planned",
                                     "prompt_chars": len(prompt), "would_push": plan["would_push"]})
            continue
        if not arming["armed"]:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"not_armed:{arming['why']}"})
            continue
        ev_dir = root / s["evidence_rel"] / job["job_id"]
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "evidence.json").write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
        # durable claim + the WHOLE budget reserved BEFORE the backend is launched (finding 3)
        claim_id, claim_why = C.claim(
            claims_db, dedupe_key=job["dedupe_key"], job_id=job["job_id"], day=day,
            reserve_iterations=int(it["max_iterations"]), reserve_usd=float(it["max_cost_usd"]),
            reserve_seconds=float(it["max_minutes"]) * 60, lease_ttl_s=lease_ttl,
            daily_job_cap=int(cfg["arming"]["daily_job_cap"]),
            daily_usd_cap=float(cfg["arming"].get("daily_cost_cap_usd", it["max_cost_usd"])),
            evidence_dir=str(ev_dir))
        if not claim_id:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"not_claimed:{claim_why}"})
            continue
        job["claim_id"] = claim_id
        job["budget_reserved"] = {"iterations": int(it["max_iterations"]), "usd": float(it["max_cost_usd"]),
                                  "seconds": float(it["max_minutes"]) * 60}

        def progress(j: dict, rec: dict, _cid: str = claim_id, _ev: Path = ev_dir) -> None:
            C.record_progress(claims_db, _cid, iterations_done=len(j.get("iterations") or []),
                              spent_usd=float(j.get("cost_usd") or 0),
                              partial={"iteration": rec.get("iteration"), "failing": (rec.get("failing") or [])[:6],
                                       "candidate": rec.get("candidate"), "patch": rec.get("patch"),
                                       "evidence_dir": str(_ev), "branch": j.get("branch"),
                                       "worktrees": j.get("worktrees")})

        try:
            with C.Heartbeat(claims_db, claim_id, lease_ttl_s=lease_ttl, every_s=beat_every):
                attempt_job(job, evidence, cfg=cfg, environ=environ, now=now, evidence_dir=ev_dir,
                            may_push=bool(policy["push_allowed"]), rails=rails, backend=backend, remember=remember,
                            persist=lambda _j: save(), progress=progress)
        except Exception as exc:  # noqa: BLE001 — a harness bug ends the attempt, never leaves it "attempting"
            if job.get("state") in (F.FIX_REQUESTED, F.FIX_ATTEMPTING):
                if job["state"] == F.FIX_REQUESTED:
                    F.transition(job, F.FIX_ATTEMPTING, now(), iteration=0)
                F.transition(job, F.FIX_FAILED, now(), reason=f"harness_exception:{type(exc).__name__}:{exc}"[:300],
                             updated_at=now().isoformat())
        C.settle(claims_db, claim_id, outcome=str(job.get("state")), spent_usd=float(job.get("cost_usd") or 0),
                 iterations_done=len(job.get("iterations") or []))
        save()
        remember(F.memory_row(job, event="attempt_outcome", now=now(), backend=backend, reason=job.get("reason"),
                              iterations=len(job.get("iterations") or []), cost_usd=job.get("cost_usd"),
                              head_sha=job.get("head_sha"), pr_url=job.get("pr_url"),
                              shadow_route=job.get("shadow_route")))
        out["attempted"].append({"job_id": job["job_id"], "outcome": job["state"], "reason": job.get("reason"),
                                 "iterations": len(job.get("iterations") or []), "cost_usd": job.get("cost_usd")})
        if job["state"] in (F.FIX_FAILED, F.FIX_REFUSED) and not job.get("escalated_at"):
            out["escalations"].append(escalation_for(job, now()))
            job["escalated_at"] = now().isoformat()
        arming = F.arming_verdict(grant, cfg=cfg, jobs_today=jobs_today())
    for job in work.get("jobs", {}).values():
        if job.get("state") in (F.FIX_READY_LOCAL, F.FIX_PR_OPENED, F.FIX_DEPLOYED, F.OUTPUT_RECOVERED):
            moved = advance(job, cfg=cfg, now=t, diag_state=diag, root=root, gh=gh, repo=repo)
            if moved:
                out["advanced"].append({"job_id": job["job_id"], "to": moved})
            if moved or job.get("acceptance"):
                remember(F.memory_row(job, event=f"lifecycle:{moved or job['state']}", now=t,
                                      backend=job.get("backend"), acceptance=job.get("acceptance"),
                                      merged_sha=job.get("merged_sha"), release_sha=job.get("release_sha")))
    out["finished_at"] = now().isoformat()
    out["counts"] = {st: sum(1 for j in work.get("jobs", {}).values() if j.get("state") == st) for st in F.STATES}
    out["repair_memory_rows"] = len(memory_new)
    if apply:
        out["budget_today"] = C.day_usage(claims_db, day)
        save()
        if out["escalations"]:
            esc_path = root / s["escalations_rel"]
            esc_path.parent.mkdir(parents=True, exist_ok=True)
            with esc_path.open("a", encoding="utf-8") as fh:
                for e in out["escalations"]:
                    fh.write(json.dumps(e, sort_keys=True) + "\n")
        out["ok_at"] = out["finished_at"]
        _atomic_write(receipt_path, out)
    elif args.out:
        _atomic_write(Path(args.out) / "receipt.json", out)
    print(json.dumps({k: out.get(k) for k in ("mode", "admitted", "skipped", "attempted", "advanced", "reconciled",
                                              "arming", "policy", "backend", "counts")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

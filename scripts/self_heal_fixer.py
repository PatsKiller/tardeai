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
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_fix_evaluator as E  # noqa: E402
from lib import self_heal_fixer as F  # noqa: E402

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


class Attempt:
    """One fix job: worktrees, iterations, commit, and (when allowed) push + PR."""

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
        self.fix_wt = self.wt_root / tag
        self.base_wt = self.wt_root / f"{tag}-base"
        self.scratch = self.wt_root / f"{tag}-state"
        #: The model's pytest wrapper lives OUTSIDE every sandbox-writable path, so a test cannot rewrite it.
        self.bindir = self.wt_root / f"{tag}-bin"
        self.pytest_cmd = str(self.bindir / "pytest")
        self.branch = F.branch_name(job, cfg, now())
        self.env = F.child_env(environ, cfg, scratch_state=str(self.scratch))
        self.sandbox: list[str] = []

    # -- worktrees
    def setup(self) -> Optional[str]:
        self.wt_root.mkdir(parents=True, exist_ok=True)
        self.scratch.mkdir(parents=True, exist_ok=True)
        a = git(self.repo, "worktree", "add", "-b", self.branch, str(self.fix_wt), self.base)
        if a["rc"] != 0:
            return f"worktree_add_failed:{a['err'][-200:]}"
        b = git(self.repo, "worktree", "add", "--detach", str(self.base_wt), self.base)
        if b["rc"] != 0:
            return f"base_worktree_add_failed:{b['err'][-200:]}"
        sb = self.cfg.get("sandbox") or {}
        if sb.get("enabled") and not os.access(str(sb.get("bwrap", "bwrap")), os.X_OK):
            return "sandbox_unavailable"
        admin = [git(w, "rev-parse", "--absolute-git-dir")["out"].strip() for w in (self.fix_wt, self.base_wt)]
        self.sandbox = F.sandbox_prefix(self.cfg, home=self.environ.get("HOME") or str(Path.home()),
                                        repo_root=str(self.repo),
                                        writable=[self.fix_wt, self.base_wt, self.scratch, *[a for a in admin if a]],
                                        existing=_kind)
        self.bindir.mkdir(parents=True, exist_ok=True)
        wrapper = Path(self.pytest_cmd)
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join([*self.sandbox, self.py, "-m", "pytest", "-p",
                                                           "no:cacheprovider"]) + ' "$@"\n', encoding="utf-8")
        wrapper.chmod(0o555)
        return None

    def teardown(self, *, keep_branch: bool) -> None:
        for wt in (self.fix_wt, self.base_wt):
            if wt.exists():
                git(self.repo, "worktree", "remove", "--force", str(wt))
        git(self.repo, "worktree", "prune")
        if not keep_branch:
            git(self.repo, "branch", "-D", self.branch)
        shutil.rmtree(self.scratch, ignore_errors=True)
        shutil.rmtree(self.bindir, ignore_errors=True)

    # -- one iteration
    def _diff(self) -> dict:
        git(self.fix_wt, "add", "-A")
        ns = git(self.fix_wt, "diff", "--cached", "--name-status", "-M", self.base)["out"]
        nm = git(self.fix_wt, "diff", "--cached", "--numstat", self.base)["out"]
        u0 = git(self.fix_wt, "diff", "--cached", "-U0", self.base)["out"]
        return {"name_status": ns, "numstat": nm, "unified": u0}

    def _pytest(self, cwd: Path, tests: list[str]) -> dict:
        if not tests:
            return {"rc": 5, "out": "", "err": "no tests", "seconds": 0.0}
        return run([*self.sandbox, self.py, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", *tests], cwd=cwd,
                   env=self.env, timeout=float(self.cfg["iteration"]["test_timeout_s"]))

    def _red_first(self, tests: list[str]) -> dict:
        """Copy the changed tests onto the base commit; they MUST fail there (reproduction proof)."""
        git(self.base_wt, "checkout", "--force", self.base, "--", ".")
        git(self.base_wt, "clean", "-fdq")
        for t in tests:
            src, dst = self.fix_wt / t, self.base_wt / t
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        r = self._pytest(self.base_wt, tests)
        r["reproduced"] = r["rc"] not in (0, 5)
        return r

    def iterate(self, k: int, prev: Optional[dict], rails: str, spent: float) -> dict:
        it = self.cfg["iteration"]
        budget = min(float(it["per_iteration_budget_usd"]), max(0.0, float(it["max_cost_usd"]) - spent))
        prompt = F.build_prompt(self.ev, rails=rails, cfg=self.cfg, iteration=k, prev=prev,
                                pytest_cmd=self.pytest_cmd)
        (self.dir / f"prompt_iter{k}.md").write_text(prompt, encoding="utf-8")
        t0 = time.monotonic()
        argv = F.backend_argv(self.cfg, self.backend, budget_usd=budget, pytest_cmd=self.pytest_cmd)
        cr = run(argv, cwd=self.fix_wt, env=self.env, timeout=float(self.cfg["claude"]["timeout_s"]), stdin=prompt)
        res = F.parse_backend_result(self.cfg, self.backend, cr["out"])
        res.update(rc=cr["rc"], stderr_tail=cr["err"][-500:])
        (self.dir / f"backend_iter{k}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        d = self._diff()
        full = git(self.fix_wt, "diff", "--cached", self.base)["out"]
        patch = self.dir / f"diff_iter{k}.patch"
        patch.write_text(full, encoding="utf-8")
        base_ci = git(self.repo, "show", f"{self.base}:scripts/run_cio_hardening_ci.py")["out"]
        refusals = F.guard_diff(name_status=d["name_status"], numstat=d["numstat"], unified=d["unified"],
                                base_ci_text=base_ci, cfg=self.cfg)
        rec: dict[str, Any] = {"iteration": k, "backend": self.backend, "diffstat": F.diffstat(d["numstat"]),
                               "diff_sha256": hashlib.sha256(full.encode()).hexdigest()[:16], "patch": str(patch),
                               "refusals": refusals,
                               # recorded for the operator, NEVER read by the evaluator (claims are not evidence)
                               "backend_result": {key: res.get(key) for key in ("ok", "cost_usd", "num_turns",
                                                                                "subtype", "summary", "rc")}}
        tests = F.changed_tests(d["name_status"])
        rec["tests_run"] = tests
        out_tail = ""
        if any(r["hard"] for r in refusals):
            rec.update(passed=False, failing=[f"guard:{r['code']}" for r in refusals], red_first=None)
        elif refusals:
            rec.update(passed=False, failing=sorted(f"guard:{r['code']}" for r in refusals), red_first=None)
            out_tail = json.dumps(refusals)
        else:
            red = self._red_first(tests)
            green = self._pytest(self.fix_wt, tests)
            ci_argv = [str(a).replace("{python}", self.py).replace("{base_sha}", self.base) for a in it["ci_argv"]]
            ci = run([*self.sandbox, *ci_argv], cwd=self.fix_wt, env=self.env, timeout=float(it["ci_timeout_s"])) \
                if green["rc"] == 0 and red["reproduced"] else {"rc": None, "out": "", "err": "skipped", "seconds": 0}
            failing = F.failing_set(green["out"], ci["out"])
            if not red["reproduced"]:
                failing.append("red_first:test_passes_on_base")
            if green["rc"] != 0 and not F.failing_set(green["out"]):
                failing.append(f"targeted:exit_{green['rc']}")
            if ci["rc"] not in (0, None) and not F.failing_set(ci["out"]):
                failing.append(f"ci:exit_{ci['rc']}")
            rec.update(red_first=red["reproduced"], targeted_rc=green["rc"], ci_rc=ci["rc"],
                       ci_argv=ci_argv, failing=sorted(set(failing)))
            out_tail = (f"--- red-first on base (rc {red['rc']}) ---\n{red['out'][-1500:]}\n"
                        f"--- targeted (rc {green['rc']}) ---\n{green['out'][-2500:]}\n"
                        f"--- ci pr profile (rc {ci['rc']}) ---\n{ci['out'][-3000:]}{ci['err'][-500:]}")
            (self.dir / f"tests_iter{k}.log").write_text(out_tail, encoding="utf-8")
        rec["seconds"] = round(time.monotonic() - t0, 1)
        rec["output_tail"] = out_tail
        rec["acceptance"] = E.local_verdict(rec)          # independent of the backend's claims
        rec["passed"] = rec["acceptance"]["accepted"]
        return rec

    # -- ship
    def commit(self) -> dict:
        lane = self.job["lane"]
        exc = (self.ev.get("final_exception") or {}).get("type") or "code error"
        msg = (f"fix({lane}): self-heal fix for {exc} (job {self.job['job_id']})\n\n"
               f"Self-heal fixer job {self.job['job_id']}, signature {self.job['signature']}, incident "
               f"{self.job.get('incident_key')}. Regression test fails on {self.base[:9]} and passes here; targeted "
               "tests and run_cio_hardening_ci.py --profile pr green in the worktree.\n\n"
               + "\n".join(self.cfg["repo"]["commit_trailers"]) + "\n")
        r = git(self.fix_wt, "commit", "-q", "-m", msg)
        head = git(self.fix_wt, "rev-parse", "HEAD")["out"].strip()
        patch = git(self.fix_wt, "format-patch", "-1", "--stdout", "HEAD")["out"]
        (self.dir / "fix.patch").write_text(patch, encoding="utf-8")
        return {"rc": r["rc"], "head": head, "err": r["err"][-300:]}

    def push_and_pr(self, body: str) -> dict:
        env = dict(self.environ)
        env.pop("TRADEAI_REMOTE_PUSH_OVERRIDE", None)  # never an override: the budget binds
        env["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "1"
        p = run(["git", "-C", str(self.fix_wt), "push", "-u", self.cfg["repo"]["remote"], self.branch], env=env,
                timeout=600)
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
        return {"ok": True, "pr_url": url, "pr_number": int(num) if num.isdigit() else None, "labelled": label}


def attempt_job(job: dict, evidence: dict, *, cfg: dict, environ: dict, now: Callable[[], datetime],
                evidence_dir: Path, may_push: bool, rails: str, backend: str,
                remember: Callable[[dict], None] = lambda row: None) -> dict:
    """Run the iteration loop for one job and move it to its next state. Returns the job."""
    a = Attempt(job, evidence, cfg=cfg, environ=environ, now=now, evidence_dir=evidence_dir, may_push=may_push,
                backend=backend)
    job["backend"] = backend
    it = cfg["iteration"]
    start = time.monotonic()
    job["attempt_started_at"] = now().isoformat()
    job["branch"] = a.branch
    err = a.setup()
    if err:
        F.transition(job, F.FIX_ATTEMPTING, now(), iteration=0)
        F.transition(job, F.FIX_FAILED, now(), reason=err, updated_at=now().isoformat())
        a.teardown(keep_branch=False)
        return job
    prev, passed, stop = None, False, "max_iterations"
    for k in range(1, int(it["max_iterations"]) + 1):
        if time.monotonic() - start > float(it["max_minutes"]) * 60:
            stop = "time_budget"
            break
        if float(job.get("cost_usd") or 0) >= float(it["max_cost_usd"]):
            stop = "cost_budget"
            break
        F.transition(job, F.FIX_ATTEMPTING, now(), iteration=k, updated_at=now().isoformat())
        rec = a.iterate(k, prev, rails, float(job.get("cost_usd") or 0))
        job["cost_usd"] = round(float(job.get("cost_usd") or 0) + float(rec["backend_result"].get("cost_usd") or 0), 4)
        job["iterations"].append({k2: v for k2, v in rec.items() if k2 != "output_tail"})
        remember(F.memory_row(job, event="iteration", now=now(), backend=backend, iteration=rec))
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
    if passed:
        c = a.commit()
        if c["rc"] != 0:
            F.transition(job, F.FIX_FAILED, now(), reason=f"commit_failed:{c['err']}", updated_at=now().isoformat())
            a.teardown(keep_branch=False)
            return job
        job["head_sha"] = c["head"]
        body = F.pr_body(job, evidence)
        (evidence_dir / "pr_body.md").write_text(body, encoding="utf-8")
        if may_push:
            pr = a.push_and_pr(body)
            if pr.get("ok"):
                F.transition(job, F.FIX_PR_OPENED, now(), pr_url=pr["pr_url"], pr_number=pr["pr_number"],
                             labelled=pr["labelled"], updated_at=now().isoformat())
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
            prv = E.pr_head_verdict(doc, expected_head=job.get("head_sha"))
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
        row = registry_row(job["lane"]) or {}
        sig = row.get("output_signal") or {}
        path = root / str(sig.get("path") or f"data/runtime/{job['lane']}_last.json")
        since = F._parse(job.get("deployed_at"))
        fresh_at = None
        if sig.get("kind") == "json_key":
            fresh_at = F._parse((_load_json(path) or {}).get(sig.get("key") or "ok_at"))
        elif path.exists():
            fresh_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if since and fresh_at and fresh_at > since:
            F.transition(job, F.OUTPUT_RECOVERED, now, output_at=fresh_at.isoformat(), updated_at=now.isoformat())
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
    state = _load_json(state_path) or {"schema": F.STATE_SCHEMA, "jobs": {}}
    if args.status:
        rows = [{k: j.get(k) for k in ("job_id", "lane", "state", "pr_url", "cost_usd", "updated_at")}
                for j in state.get("jobs", {}).values()]
        print(json.dumps({"jobs": rows}, indent=1))
        return 0
    if not args.cycle:
        ap.print_help()
        return 0
    t = now()
    repo = Path(cfg["repo"]["repo_root"])
    out: dict[str, Any] = {"schema": F.RECEIPT_SCHEMA, "mode": "apply" if apply else "dry_run",
                           "started_at": t.isoformat(), "admitted": [], "skipped": [], "attempted": [],
                           "advanced": [], "escalations": []}
    incidents, diag = incidents_from(args, cfg, root)
    held = operator_holds()
    work = state if apply else json.loads(json.dumps(state))
    ledger = root / cfg["intake"]["ledger_rel"]
    ev_by_job: dict[str, dict] = {}
    memory_path = root / s["repair_memory_rel"]
    memory_old = _tail_jsonl(memory_path, 20000)
    memory_new: list[dict] = []
    remember = memory_new.append
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
    # arming + policy
    fetch = git(repo, "fetch", "-q", cfg["repo"]["remote"], cfg["repo"]["base_branch"]) if apply else {"rc": 0}
    base_sha = git(repo, "rev-parse", f"{cfg['repo']['remote']}/{cfg['repo']['base_branch']}")["out"].strip()
    agents = agents_text_at(repo, base_sha) if base_sha else ""
    grant = grant_reader(cfg["arming"]["grant_tier"])
    arming = F.arming_verdict(grant, cfg=cfg, jobs_today=F.jobs_started_today(work, t))
    policy = F.policy_verdict(agents, cfg)
    backend, backend_why = F.select_backend(cfg)
    out.update(arming=arming, policy=policy, base_sha=base_sha, fetch_rc=fetch["rc"],
               backend={"name": backend, "why": backend_why})
    names = [n for n in (cfg.get("backends") or {}) if not n.startswith("_")]
    queue = [j for j in work.get("jobs", {}).values() if j.get("state") == F.FIX_REQUESTED]
    queue.sort(key=lambda j: str(j.get("created_at")))
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
            pytest_cmd = str(Path(cfg["repo"]["worktree_root"]) / f"{job['job_id']}-bin" / "pytest")
            plan = {"job": job, "evidence": evidence, "backend": backend,
                    "backend_argv": F.backend_argv(cfg, backend, budget_usd=float(
                        cfg["iteration"]["per_iteration_budget_usd"]), pytest_cmd=pytest_cmd),
                    "backend_call": "STUBBED (dry run: no model call)",
                    "sandbox_prefix": F.sandbox_prefix(cfg, home=environ.get("HOME") or str(Path.home()),
                                                       repo_root=str(repo), writable=["<fix_wt>", "<base_wt>",
                                                                                      "<scratch>", "<git-admin>"],
                                                       existing=_kind),
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
        attempt_job(job, evidence, cfg=cfg, environ=environ, now=now, evidence_dir=ev_dir,
                    may_push=bool(policy["push_allowed"]), rails=rails, backend=backend, remember=remember)
        remember(F.memory_row(job, event="attempt_outcome", now=now(), backend=backend, reason=job.get("reason"),
                              iterations=len(job.get("iterations") or []), cost_usd=job.get("cost_usd"),
                              head_sha=job.get("head_sha"), pr_url=job.get("pr_url"),
                              shadow_route=job.get("shadow_route")))
        out["attempted"].append({"job_id": job["job_id"], "outcome": job["state"], "reason": job.get("reason"),
                                 "iterations": len(job.get("iterations") or []), "cost_usd": job.get("cost_usd")})
        if job["state"] in (F.FIX_FAILED, F.FIX_REFUSED) and not job.get("escalated_at"):
            out["escalations"].append(escalation_for(job, now()))
            job["escalated_at"] = now().isoformat()
        arming = F.arming_verdict(grant, cfg=cfg, jobs_today=F.jobs_started_today(work, now()))
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
        _atomic_write(state_path, work)
        if memory_new:
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            with memory_path.open("a", encoding="utf-8") as fh:
                for row in memory_new:
                    fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
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
    print(json.dumps({k: out[k] for k in ("mode", "admitted", "skipped", "attempted", "advanced", "arming", "policy",
                                          "backend", "counts")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

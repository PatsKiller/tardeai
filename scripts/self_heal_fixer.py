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
AGENTS.md 24.16 amendment ACTIVE and an operator grant) pushes one branch and opens one PR.
"""

from __future__ import annotations

import argparse
import contextvars
import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_fix_evaluator as E  # noqa: E402
from lib import self_heal_egress as EG  # noqa: E402
from lib import self_heal_fixer as F  # noqa: E402
from lib import self_heal_fixer_claims as C  # noqa: E402
from lib import self_heal_metrics as M  # noqa: E402
from lib import self_heal_runbooks as R  # noqa: E402
from lib import self_heal_safety as SAFE  # noqa: E402
from lib import self_heal_verify as V  # noqa: E402
from scripts.lib import recovery_validator as RV  # noqa: E402

CONFIG = ROOT / "config" / "self_heal_fixer.json"
REGISTRY = ROOT / "config" / "lane_registry.json"
HEALTH_CONTRACTS = ROOT / "config" / "n8n_health_contracts.json"
RUN_ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
#: The served release's commit (LQ-20261107-1228). Read relative to the home directory, so no user path is committed.
SERVED_SHA_FILE_DEFAULT = Path("trade-ai-releases") / "portfolio-server" / "CURRENT" / "GIT_SHA"
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
#: LQ-1236 safety/metrics paths, relative to the state root (config ``safety`` may override them).
KILL_FILE_REL = "data/runtime/self_heal/KILL"
METRICS_REL = "data/runtime/self_heal/metrics.jsonl"
CUTOVER_POLICY = ROOT / "config" / "lane_cutover_policy.json"
_DEADLINE = contextvars.ContextVar("self_heal_absolute_deadline", default=None)


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


def run(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    timeout: float = 600,
    stdin: Optional[str] = None,
    text: bool = True,
) -> dict:
    t0 = time.monotonic()
    deadline = _DEADLINE.get()
    timeout = min(float(timeout), deadline - t0) if deadline is not None else float(timeout)
    if timeout <= 0:
        return {"rc": 124, "out": "" if text else b"", "err": "absolute job deadline exceeded", "seconds": 0}
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            start_new_session=True,
        )
        try:
            out, err = p.communicate(input=stdin, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            # Kill descendants as well: a timed-out model/test may have spawned another process.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = p.communicate()
            rc, err = 124, f"timeout after {timeout}s (absolute job deadline respected)"
    except OSError as exc:
        rc, out, err = 127, "", f"{type(exc).__name__}: {exc}"
    return {"rc": rc, "out": out or "", "err": err or "", "seconds": round(time.monotonic() - t0, 1)}


def git(repo: Path, *args: str, env: Optional[dict] = None, timeout: float = 300) -> dict:
    return run(["git", "-C", str(repo), *args], env=env, timeout=timeout)


def _deadline_at(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _job_deadline(fn):
    @functools.wraps(fn)
    def bounded(job, evidence, **kwargs):
        now = kwargs["now"]()
        limit = float(kwargs["cfg"]["iteration"]["max_minutes"]) * 60
        previous = _deadline_at(job.get("deadline_at"))
        if "deadline_at" in job and previous is None:
            job["deadline_hold"] = "absolute_job_deadline_invalid"
            limit = 0
        if previous is not None:
            limit = min(limit, (previous - now).total_seconds())
        if "deadline_at" not in job or (previous is not None and limit > 0):
            job["deadline_at"] = (now + timedelta(seconds=max(0, limit))).isoformat()
        token = _DEADLINE.set(time.monotonic() + max(0, limit))
        try:
            return fn(job, evidence, **kwargs)
        finally:
            _DEADLINE.reset(token)

    return bounded


def pytest_proof(report: Path) -> dict:
    """Read only the harness-created pytest JUnit report; collection errors are never red-first proof."""
    import xml.etree.ElementTree as ET

    empty = {"assertion_failures": [], "passed": [], "errors": None, "report_sha256": None}
    try:
        raw = report.read_bytes()
        doc = ET.fromstring(raw)
    except (OSError, ET.ParseError):
        return empty
    failed, passed, errors = [], [], 0
    for case in doc.iter("testcase"):
        identity = case.get("classname", "") + "::" + case.get("name", "")
        errors += len(case.findall("error"))
        failures = case.findall("failure")
        # Pytest's exception summary identifies the failure. A source line or another exception's
        # arbitrary message mentioning "assert" is not evidence of an assertion failure.
        if failures and all(
            re.match(r"^(?:AssertionError\b|assert\s)", (f.get("message") or "").strip()) for f in failures
        ):
            failed.append(identity)
        if not failures and not case.findall("error") and not case.findall("skipped"):
            passed.append(identity)
    return {
        "assertion_failures": sorted(failed),
        "passed": sorted(passed),
        "errors": errors,
        "report_sha256": hashlib.sha256(raw).hexdigest(),
    }


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
            row = (
                con.execute("SELECT receipt_json FROM runs WHERE run_id=? AND lane_id=?", (run_id, lane)).fetchone()
                if run_id and run_id != "n/a"
                else None
            )
            if not row:
                row = con.execute(
                    "SELECT receipt_json FROM runs WHERE lane_id=? AND state='RUN_FAILED' AND receipt_json IS NOT NULL "
                    "ORDER BY finished_at DESC LIMIT 1",
                    (lane,),
                ).fetchone()
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


def lane_contracts_for(lane: str, row: Optional[dict]) -> dict:
    """The lane's health-contract, registry and n8n-run rows from this code root's config (the served release)."""
    return F.lane_contracts(
        lane, health_doc=_load_json(HEALTH_CONTRACTS), registry_row=row, allowlist_doc=_load_json(RUN_ALLOWLIST)
    )


def resolve_base(repo: Path, cfg: dict, *, apply: bool, environ: dict) -> dict:
    """The commit a fix worktree starts from (LQ-20261107-1228).

    ``repo.base_ref`` "served" (the default): the served release's GIT_SHA (``repo.served_sha_file``, else
    ``lifecycle.release_current_sha_file``, else ~/trade-ai-releases/portfolio-server/CURRENT/GIT_SHA). That is
    the code the failing lane actually ran. Under the no-push order the live release holds local-only folds that
    origin/main lacks, so a fix based on origin/main targets stale code. The SHA must be a full 40-hex commit that
    exists in the repo. Otherwise there is NO base and every attempt is refused, never a silent fallback to
    origin/main.
    ``repo.base_ref`` "remote": the old behaviour, ``<remote>/<base_branch>`` after a fetch (apply only)."""
    rcfg = cfg["repo"]
    ref = str(rcfg.get("base_ref") or "served")
    if ref == "remote":
        fetch = git(repo, "fetch", "-q", rcfg["remote"], rcfg["base_branch"]) if apply else {"rc": 0}
        sha = git(repo, "rev-parse", f"{rcfg['remote']}/{rcfg['base_branch']}")["out"].strip()
        return {"sha": sha, "ref": ref, "source": f"{rcfg['remote']}/{rcfg['base_branch']}", "fetch_rc": fetch["rc"],
                "why": None if sha else "remote_ref_unresolved"}
    if ref != "served":
        return {"sha": "", "ref": ref, "source": None, "fetch_rc": 0, "why": f"unknown_base_ref:{ref}"}
    home = Path(environ.get("HOME") or Path.home())
    src = Path(
        rcfg.get("served_sha_file")
        or (cfg.get("lifecycle") or {}).get("release_current_sha_file")
        or home / SERVED_SHA_FILE_DEFAULT
    )
    try:
        sha = src.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {"sha": "", "ref": ref, "source": str(src), "fetch_rc": 0, "why": f"served_sha_unreadable:{exc.errno}"}
    if not _FULL_SHA.fullmatch(sha):
        return {"sha": "", "ref": ref, "source": str(src), "fetch_rc": 0, "why": "served_sha_not_a_full_sha"}
    if git(repo, "cat-file", "-e", f"{sha}^{{commit}}")["rc"] != 0:
        return {"sha": "", "ref": ref, "source": str(src), "fetch_rc": 0, "why": "served_sha_not_in_repo"}
    return {"sha": sha, "ref": ref, "source": str(src), "fetch_rc": 0, "why": None}


def already_fixed_on_served(repo: Path, evidence: dict, base_sha: str) -> Optional[dict]:
    """LQ-1236: did the served release change the failing code after the failing run? Read-only git.

    Only a definite answer counts: the failing run names its full ``code_sha``, that commit is in the repo and is not
    the served commit, and ``git diff --quiet`` exits 1 over the files the failure names (the script plus every repo
    file in the error text). Anything less (no code_sha, unknown commit, no paths, a git error) returns None and the
    attempt proceeds; a model is never spared on a guess."""
    code_sha = str((evidence.get("failing_run") or {}).get("code_sha") or "").strip().lower()
    paths = F.error_paths(evidence)
    if not base_sha or not _FULL_SHA.fullmatch(code_sha) or code_sha == base_sha or not paths:
        return None
    if git(repo, "cat-file", "-e", f"{code_sha}^{{commit}}", timeout=60)["rc"] != 0:
        return None
    d = git(repo, "diff", "--quiet", code_sha, base_sha, "--", *paths, timeout=120)
    if d["rc"] != 1:
        return None
    changed = git(repo, "diff", "--name-only", code_sha, base_sha, "--", *paths, timeout=120)["out"].split()
    return {"code_sha": code_sha, "served_sha": base_sha, "paths": paths, "changed": changed[:20]}


def run_runbook(
    cls: str, ev: dict, contract: Optional[dict], *, state: dict, now: datetime, apply_enabled: bool
) -> dict:
    """LQ-1231 wired in by LQ-1236: plan the non-code runbook for ``cls`` and apply it (a dry run unless the caller's
    config arms it). ``state`` is the lane's durable runbook facts and is updated only when an action was taken.
    A runbook error never stops the cycle: it is reported and the escalation stands."""
    try:
        plan = R.plan_runbook(cls, ev, contract, now, state=state)
        rcpt = R.apply_runbook(plan, dry_run=not apply_enabled, now=now)
    except Exception as exc:  # noqa: BLE001 -- the runbook layer is advisory to the escalation; it never ends a cycle
        return {"error": f"{type(exc).__name__}:{exc}"[:300]}
    taken = str(rcpt.get("action_taken") or "none")
    mutating = str(plan.get("action") or "none") not in (*R.NON_MUTATING_ACTIONS, "none")
    if apply_enabled and mutating and "refused" not in taken:
        state["attempts"] = int(state.get("attempts") or 0) + 1
        state["lane_last_action_at"] = state["entry_last_attempt_at"] = now.isoformat()
    return {
        "entry": plan.get("entry"),
        "category": plan.get("category"),
        "action": plan.get("action"),
        "reason": plan.get("reason"),
        "action_taken": taken,
        "dry_run": bool(rcpt.get("dry_run")),
        "human_steps": list(plan.get("human_steps") or [])[:6],
        "finding_text": rcpt.get("finding_text"),
    }


def past_findings(cfg: dict, root: Path) -> list[str]:
    """FINDING-SELF-HEAL* file names the triage may link a failure to (names only; it reads no file)."""
    try:
        return sorted(p.name for p in findings_dir(cfg, root).glob("FINDING-SELF-HEAL*"))[-200:]
    except OSError:
        return []


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


#: What ``claude.provider`` says about the model backend. ``off`` = the Claude CLI on its own credential;
#: ``active`` = a complete non-Anthropic provider; ``incomplete`` = a provider is NAMED but cannot run, and that is a
#: refusal, never a fallback (operator 2026-11-08, LQ-20261107-1258: self-heal must not spend Anthropic). Before this,
#: a half-configured block silently kept the CLI's own OAuth login -- the one outcome the operator ruled out.
PROVIDER_OFF = "off"
PROVIDER_ACTIVE = "active"
PROVIDER_INCOMPLETE = "incomplete"


def _provider_path(raw: Any, cfg: dict, environ: dict) -> str:
    """A provider path with the placeholders every credential-shaped path in this config uses."""
    home = environ.get("HOME") or str(Path.home())
    repo = str((cfg.get("repo") or {}).get("repo_root") or "")
    return str(raw).replace("{repo_root}", repo).replace("{home}", home)


def provider_block_state(cfg: dict, environ: Optional[dict] = None, *, require_egress: bool = True) -> dict:
    """Classify ``claude.provider`` for the cycle, the plan view and the attempt: state, typed reason, resolved paths.

    ``off``: no provider block, or an explicit ``"name": "anthropic"`` -- the CLI's own auth, the legacy path.
    ``active``: name + launcher + key_file, ``auth_mode`` exactly ``"none"``, at least one egress host.
    ``incomplete``: a provider is named but one of those is missing -- the cycle REFUSES it.
    ``launcher_readable``/``key_readable`` are ``os.access`` on the PATHS only, reported beside the state because a
    missing launcher or key is a runtime fact about THIS host, not the shape of the config; the key's content is
    never read here.
    """
    environ = dict(os.environ if environ is None else environ)
    prov = dict(((cfg.get("claude") or {}).get("provider") or {}))
    name = str(prov.get("name") or "").strip().lower()
    egress = [str(h) for h in (prov.get("egress_allow") or []) if str(h).strip()]
    state: dict[str, Any] = {
        "name": name or None,
        "state": PROVIDER_OFF,
        "reason": "provider_absent",
        "auth_mode": prov.get("auth_mode"),
        "egress_allow": egress,
        "launcher": _provider_path(prov["launcher"], cfg, environ) if prov.get("launcher") else None,
        "key_file": _provider_path(prov["key_file"], cfg, environ) if prov.get("key_file") else None,
        "launcher_readable": False,
        "key_readable": False,
    }
    if not name:
        return state
    if name == "anthropic":
        state["reason"] = "provider_is_anthropic_cli"
        return state

    def incomplete(reason: str) -> dict:
        state.update(state=PROVIDER_INCOMPLETE, reason=reason)
        return state

    if not state["launcher"]:
        return incomplete("provider_launcher_missing")
    if not state["key_file"]:
        return incomplete("provider_key_file_missing")
    if str(prov.get("auth_mode") or "") != "none":
        # The provider carries its own key, so the CLI's OAuth credential MUST NOT be bound inside its run.
        return incomplete("provider_auth_mode_invalid")
    if require_egress and not egress:
        return incomplete("provider_egress_missing")
    state.update(state=PROVIDER_ACTIVE, reason="provider_active")
    state["launcher_readable"] = os.access(state["launcher"], os.R_OK)
    state["key_readable"] = os.access(state["key_file"], os.R_OK)
    return state


def provider_cycle_refusal(
    cfg: dict, environ: Optional[dict] = None, *, apply: bool
) -> tuple[Optional[str], dict]:
    """The cycle-level refusal, ``(reason, state)``. None means the cycle may run.

    An incomplete block refuses a DRY RUN too: the plan would otherwise quote an Anthropic run the operator has
    ruled out. An active block whose launcher is not readable cannot start on this host at all, and a live
    (``--apply``) cycle also refuses when the provider's key file is not readable -- better a visible refusal than
    jobs that can only end in ``provider_key_unavailable`` after a claim and a worktree.
    """
    state = provider_block_state(cfg, environ)
    if state["state"] == PROVIDER_INCOMPLETE:
        return f"provider_block_incomplete:{state['reason']}", state
    if state["state"] == PROVIDER_ACTIVE and not state["launcher_readable"]:
        return "provider_launcher_unavailable", state
    if state["state"] == PROVIDER_ACTIVE and apply and not state["key_readable"]:
        return "provider_key_unavailable", state
    return None, state


def provider_plan_view(cfg: dict, environ: Optional[dict] = None) -> tuple[list[str], dict]:
    """The effective egress list and auth config a provider block WOULD use (dry-run planning).

    Mirrors Attempt.egress_allow() and Attempt.setup()'s auth_mode override so a quoted dry run shows the provider
    host and no OAuth bind, never the static defaults. It reuses the same classifier the cycle refuses on, so the
    plan cannot describe a provider state the run would not use; an incomplete block adds nothing (the cycle refuses
    before any plan is printed).
    """
    asb = cfg.get("agent_sandbox") or {}
    prov = provider_block_state(cfg, environ)
    egress = [str(h) for h in (asb.get("egress_allow") or [])]
    if prov["state"] == PROVIDER_ACTIVE:
        for host in prov["egress_allow"]:
            if host not in egress:
                egress.append(host)
    auth_cfg = cfg
    if prov["state"] == PROVIDER_ACTIVE:
        auth_cfg = {**cfg, "claude": {**cfg["claude"], "auth": {
            **(cfg["claude"].get("auth") or {}), "mode": str(prov["auth_mode"])}}}
    return egress, auth_cfg


class Attempt:
    """One fix job: the sandboxed agent, immutable candidate commits, harness test runs bound to them, and the
    ship step (local branch, or push + PR when allowed) that proves it ships exactly the evaluated commit."""

    def __init__(
        self,
        job: dict,
        evidence: dict,
        *,
        cfg: dict,
        environ: dict,
        now: Callable[[], datetime],
        evidence_dir: Path,
        may_push: bool,
        backend: str,
    ):
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
        #: the model provider for THIS job (absent/"" = the Claude CLI with its own auth)
        self.provider: dict[str, Any] = dict((cfg.get("claude") or {}).get("provider") or {})
        #: the provider key, read on the host and handed over on the agent's stdin (never env, path or argv)
        self.key_line: Optional[bytes] = None

    def python_install(self) -> list[str]:
        """The interpreter's real install prefix (a venv's python is a symlink into it; on this host /usr, on a CI
        runner e.g. /opt/hostedtoolcache/...), bound read-only so python starts inside an allowlist sandbox."""
        return [str(Path(os.path.realpath(self.py)).parent.parent)]

    def _backend_bins(self) -> list[str]:
        b = (self.cfg.get("backends") or {}).get(self.backend) or {}
        if b.get("kind") == "cli_stdin":
            return [str(b.get("bin"))]
        return [str(self.cfg["claude"]["bin"])]

    def _provider_active(self) -> bool:
        """The MECHANICS of a provider: a non-Anthropic name with a launcher and a key file, so its host is added to
        the allowlist and the launcher wraps the CLI. Whether the block is complete enough to RUN is decided by
        ``provider_setup_problem`` (and, one level up, by the cycle's ``provider_cycle_refusal``): a block that names
        DeepSeek never silently falls back to the CLI's own OAuth login."""
        return (str(self.provider.get("name") or "").lower() not in ("", "anthropic")
                and bool(self.provider.get("launcher")) and bool(self.provider.get("key_file")))

    def provider_setup_problem(self) -> Optional[str]:
        """A provider block must be complete AND safe: DeepSeek carries its own key, so it may never reuse the
        CLI's OAuth credential. auth_mode must therefore be exactly "none"; anything else is a half-configured
        block that would bind the Anthropic credential inside a DeepSeek run. A block missing a field is a problem
        here too, so an Attempt built directly cannot launch the CLI on the operator's Anthropic credential."""
        state = provider_block_state(self.cfg, self.environ, require_egress=False)
        if state["state"] == PROVIDER_INCOMPLETE:
            return state["reason"]
        if state["state"] == PROVIDER_ACTIVE and not state["launcher_readable"]:
            return "provider_launcher_unavailable"
        return None

    def egress_allow(self) -> list[str]:
        """Hosts the egress bridge may CONNECT to. A provider host is added ONLY while that provider is active;
        on the Anthropic path the allowlist stays Anthropic-only, so a prompt-injected model cannot take the
        bound OAuth credential to a third party."""
        hosts = [str(h) for h in (self.asb.get("egress_allow") or [])]
        if self._provider_active():
            for h in self.provider.get("egress_allow") or []:
                if str(h) not in hosts:
                    hosts.append(str(h))
        return hosts

    def launcher_path(self) -> str:
        raw = str(self.provider.get("launcher") or "").replace("{repo_root}", str(self.repo))
        return raw.replace("{home}", self.environ.get("HOME") or str(Path.home()))

    def _read_provider_key(self) -> Optional[bytes]:
        """Read the provider key on the HOST. O_NOFOLLOW: a symlink plant must not become a credential read.

        The key cannot cross bwrap as an inherited descriptor here (this host's bubblewrap 0.11.1 has no
        --preserve-fds), and a bind mount would put it at a path the model's Bash can open. So it travels as the
        FIRST LINE of the agent's stdin: the launcher consumes that line before it execs the CLI, seals the key in
        a memfd and names that descriptor. It is never in the env, never a path and never in argv."""
        raw = str(self.provider.get("key_file") or "").replace("{home}", self.environ.get("HOME") or str(Path.home()))
        if not raw:
            return None
        try:
            fd = os.open(raw, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        try:
            data = os.read(fd, 4096)
        finally:
            os.close(fd)
        data = data.strip()
        return data if data and b"\n" not in data and b"\r" not in data else None

    # -- worktrees + the agent's boundary
    def setup(self) -> Optional[str]:
        for d in (
            self.wt_root,
            self.scratch,
            self.eval_root,
            self.bindir,
            self.egress_dir,
            self.agent_home / ".claude",
        ):
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
            auth_cfg = self.cfg
            if self.provider.get("auth_mode"):
                # A provider key replaces the CLI's own credential: bind no OAuth file for it.
                auth_cfg = {**self.cfg, "claude": {**self.cfg["claude"], "auth": {
                    **(self.cfg["claude"].get("auth") or {}), "mode": str(self.provider["auth_mode"])}}}
            binds, why = F.agent_auth_binds(auth_cfg, home=home, agent_home=str(self.agent_home), probe=_probe)
            if not why.startswith("auth:"):
                return why
            for _src, dst, _rw in binds:  # an EMPTY mount point; the credential itself is never read or copied
                Path(dst).touch(exist_ok=True)
            allow = self.egress_allow()
            self.proxy_port = int(self.asb.get("proxy_port", 18977)) if allow else None
            self.agent_env = F.agent_env(
                self.environ,
                self.cfg,
                scratch_state=str(self.scratch),
                agent_home=str(self.agent_home),
                proxy_port=self.proxy_port,
            )
            problem = self.provider_setup_problem()
            if problem:
                return problem
            if self._provider_active():
                self.key_line = self._read_provider_key()
                if self.key_line is None:
                    return "provider_key_unavailable"
                # AFTER agent_env(): these are flags, not secrets. The launcher reads the key line from stdin and
                # names the CLI binary, which is not on the sandbox PATH.
                self.agent_env["TRADEAI_DEEPSEEK_KEY_STDIN"] = "1"
                self.agent_env["TRADEAI_CLAUDE_BIN"] = str(
                    self.provider.get("cli_bin") or self.cfg["claude"]["bin"]).replace("{home}", home)
            shutil.copyfile(Path(EG.__file__), self.bindir / "self_heal_egress.py")
            bins = sorted({os.path.realpath(b) for b in self._backend_bins()}
                          | ({os.path.realpath(self.launcher_path())} if self._provider_active() else set()))
            self.agent_prefix = F.agent_sandbox_prefix(
                self.cfg,
                home=home,
                repo_root=str(self.repo),
                python_root=str(Path(self.py).parent.parent),
                extra_ro=[*self.python_install(), *bins, str(self.bindir), str(self.egress_dir)],
                fix_wt=str(self.fix_wt),
                agent_home=str(self.agent_home),
                scratch=str(self.scratch),
                auth_binds=binds,
                env=self.agent_env,
                probe=_probe,
            )
            wrapper_env = {k: v for k, v in self.env.items() if k not in ("HOME", "PATH", "TMPDIR")}
            wrapper_env.update(HOME=str(self.scratch), PATH=self.agent_env["PATH"], TMPDIR="/tmp")
            wrapper = F.model_pytest_wrapper(python=self.py, env=wrapper_env, sandbox=[])
            self.boundary = {
                "agent_sandbox": True,
                "auth": why,
                "egress_allow": allow,
                "writable": [str(self.fix_wt), str(self.agent_home), str(self.scratch)],
            }
        elif self.environ.get("TRADE_AI_CI") != "1":
            return "agent_sandbox_disabled"  # outside hermetic tests the agent NEVER runs unsandboxed
        else:
            wrapper = F.model_pytest_wrapper(
                python=self.py,
                env=self.env,
                sandbox=F.sandbox_prefix(
                    self.cfg, home=home, repo_root=str(self.repo), writable=[self.fix_wt, self.scratch], existing=_kind
                ),
            )
            self.boundary = {"agent_sandbox": False, "why": "TRADE_AI_CI=1 hermetic test config"}
        w = Path(self.pytest_cmd)
        w.write_text(wrapper, encoding="utf-8")
        w.chmod(0o555)
        return None

    def teardown(self, *, keep_branch: bool) -> None:
        if _DEADLINE.get() is not None and time.monotonic() >= _DEADLINE.get():
            # No cleanup subprocess may start after the deadline. Preserve paths for an explicit later cleanup.
            self.job["cleanup_deferred"] = {
                "reason": "absolute_job_deadline",
                "branch": self.branch,
                "worktrees": [str(self.fix_wt), str(self.eval_root)],
            }
            return
        if self.fix_wt.exists():
            git(self.repo, "worktree", "remove", "--force", str(self.fix_wt))
        git(self.repo, "worktree", "prune")
        if not keep_branch:
            git(self.repo, "branch", "-D", self.branch)
        self.key_line = None
        for d in (self.eval_root, self.scratch, self.bindir, self.agent_home, self.egress_dir):
            shutil.rmtree(d, ignore_errors=True)

    # -- the agent, inside its boundary
    def agent_cmd(self, argv: list[str]) -> list[str]:
        if not self.agent_prefix:
            return argv
        if self._provider_active() and self.provider.get("launcher"):
            # the launcher names the descriptor to the CLI and execs it; cwd (the candidate worktree) is preserved
            inner = [self.py, "-I", os.path.realpath(self.launcher_path()), *argv[1:]]
        else:
            inner = [os.path.realpath(argv[0]), *argv[1:]]
        if self.proxy_port:
            inner = [
                self.py,
                "-I",
                str(self.bindir / "self_heal_egress.py"),
                "bridge",
                "--unix",
                str(self.egress_dir / "s"),
                "--port",
                str(self.proxy_port),
                "--",
                *inner,
            ]
        return [*self.agent_prefix, *inner]

    def run_agent(self, argv: list[str], prompt: str) -> tuple[dict, Optional[dict]]:
        cmd = self.agent_cmd(argv)
        timeout = float(self.cfg["claude"]["timeout_s"])
        if self.key_line is not None and self._provider_active():
            # first line = the key, consumed by the launcher before the CLI starts; the rest is the prompt
            prompt = self.key_line.decode("utf-8", "replace") + "\n" + prompt
        if self.agent_prefix and self.proxy_port:
            with EG.EgressProxy(str(self.egress_dir / "s"), self.egress_allow()) as px:
                cr = run(cmd, cwd=self.fix_wt, env=self.env, timeout=timeout, stdin=prompt)
                return cr, px.summary()
        return run(cmd, cwd=self.fix_wt, env=self.env, timeout=timeout, stdin=prompt), None

    # -- the immutable candidate
    def _message(self) -> str:
        lane = self.job["lane"]
        exc = (self.ev.get("final_exception") or {}).get("type") or "code error"
        return (
            f"fix({lane}): self-heal fix for {exc} (job {self.job['job_id']})\n\n"
            f"Self-heal fixer job {self.job['job_id']}, signature {self.job['signature']}, incident "
            f"{self.job.get('incident_key')}. This exact commit (sha + tree) was evaluated by the harness: the "
            f"regression test fails on {self.base[:9]} and passes here, and run_cio_hardening_ci.py --profile pr "
            "is green, in fresh read-only checkouts of this commit.\n\n"
            + "\n".join(self.cfg["repo"]["commit_trailers"])
            + "\n"
        )

    def candidate(self) -> dict:
        """Stage the agent's worktree and write ONE commit object (parent = base) without moving any ref. Its sha
        and tree hash are what everything after this point is judged on."""
        git(self.fix_wt, "add", "-A")
        tree = git(self.fix_wt, "write-tree")
        if tree["rc"] != 0:
            return {"error": f"write_tree_failed:{tree['err'][-200:]}"}
        c = run(
            ["git", "-C", str(self.fix_wt), "commit-tree", tree["out"].strip(), "-p", self.base, "-F", "-"],
            stdin=self._message(),
            timeout=60,
        )
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
        return F.guard_diff(
            name_status=d["name_status"], numstat=d["numstat"], unified=d["unified"], base_ci_text=base_ci, cfg=self.cfg
        )

    # -- harness test runs, bound to the candidate
    def _blob(self, commit: str, path: str) -> Optional[bytes]:
        r = run(["git", "-C", str(self.repo), "cat-file", "blob", f"{commit}:{path}"], timeout=60, text=False)
        return r["out"] if r["rc"] == 0 else None

    def checkout(self, name: str, sha: str, overlay: Optional[dict[str, bytes]] = None) -> Optional[Path]:
        """A FRESH shared clone at ``sha`` (its own .git; objects via alternates), optionally with files overlaid.
        Nothing else ever touches it, so its digest is exactly what the run saw."""
        d = self.eval_root / name
        shutil.rmtree(d, ignore_errors=True)
        c = git(self.repo, "clone", "-q", "--shared", "--no-checkout", str(self.repo), str(d))
        if c["rc"] != 0:
            return None
        co = git(
            d, "-c", "core.hooksPath=/dev/null", "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", sha
        )
        if co["rc"] != 0:
            return None
        for rel, data in (overlay or {}).items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return d

    def eval_run(
        self,
        kind: str,
        co: Optional[Path],
        expect: str,
        argv: list[str],
        timeout: float,
        overlay_from: Optional[str] = None,
    ) -> dict:
        rid = f"{kind}-{uuid.uuid4().hex[:12]}"
        if co is None:
            return {
                "run_id": rid,
                "kind": kind,
                "rc": None,
                "out": "",
                "err": "checkout_failed",
                "integrity_ok": False,
                "checkout_sha": None,
                "head_after": None,
                "overlay_from": overlay_from,
            }
        head_before = git(co, "rev-parse", "HEAD")["out"].strip()
        before = checkout_digest(co)
        eval_env = {**self.env, "HOME": str(self.scratch), "TMPDIR": "/tmp"}
        prefix = F.eval_sandbox_prefix(
            self.cfg,
            repo_root=str(self.repo),
            python_root=str(Path(self.py).parent.parent),
            checkout=str(co),
            scratch=str(self.scratch),
            env=eval_env,
            probe=_probe,
            extra_ro=self.python_install(),
        )
        report = self.scratch / f"{rid}.xml"
        actual = [*argv, f"--junitxml={report}"] if kind in ("red_first", "targeted") else argv
        r = run([*prefix, *actual], cwd=co, env=eval_env if prefix else self.env, timeout=timeout)
        proof = pytest_proof(report) if kind in ("red_first", "targeted") else None
        if report.is_file():
            shutil.copyfile(report, self.dir / f"{rid}.xml")
        after = checkout_digest(co)
        head_after = git(co, "rev-parse", "HEAD")["out"].strip()
        ok = before == after and head_before == expect and head_after == expect
        return {
            "run_id": rid,
            "kind": kind,
            "rc": r["rc"],
            "out": r["out"],
            "err": r["err"],
            "seconds": r["seconds"],
            "checkout": str(co),
            "checkout_sha": head_before,
            "head_after": head_after,
            "digest_before": before[:16],
            "digest_after": after[:16],
            "integrity_ok": ok,
            "overlay_from": overlay_from,
            "test_command": argv,
            "pytest_proof": proof,
            "report_ref": str(self.dir / f"{rid}.xml") if proof else None,
        }

    # -- one iteration
    def iterate(self, k: int, prev: Optional[dict], rails: str, spent: float) -> dict:
        it = self.cfg["iteration"]
        budget = min(float(it["per_iteration_budget_usd"]), max(0.0, float(it["max_cost_usd"]) - spent))
        prompt = F.build_prompt(self.ev, rails=rails, cfg=self.cfg, iteration=k, prev=prev, pytest_cmd=self.pytest_cmd)
        (self.dir / f"prompt_iter{k}.md").write_text(prompt, encoding="utf-8")
        t0 = time.monotonic()
        argv = F.backend_argv(self.cfg, self.backend, budget_usd=budget, pytest_cmd=self.pytest_cmd)
        cr, egress = self.run_agent(argv, prompt)
        res = F.parse_backend_result(self.cfg, self.backend, cr["out"])
        res.update(rc=cr["rc"], stderr_tail=cr["err"][-500:], egress=egress)
        (self.dir / f"backend_iter{k}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        rec: dict[str, Any] = {
            "iteration": k,
            "backend": self.backend,
            "boundary": self.boundary,
            # recorded for the operator, NEVER read by the evaluator (claims are not evidence)
            "backend_result": {
                key: res.get(key) for key in ("ok", "cost_usd", "num_turns", "subtype", "summary", "rc")
            },
            # the sanctioned NOT_CODE exit (LQ-1235): only the reply's LAST line counts; None when not taken
            "not_code": SAFE.agent_says_not_code(res.get("result"))[1] or None,
        }
        cand = self.candidate()
        if cand.get("error"):
            rec.update(
                candidate=cand,
                refusals=[],
                failing=[f"candidate:{cand['error']}"],
                tests_run=[],
                red_first=None,
                test_runs=[],
                diffstat=F.diffstat(""),
            )
            rec["seconds"], rec["output_tail"] = round(time.monotonic() - t0, 1), ""
            rec["acceptance"] = E.local_verdict(rec)
            rec["passed"] = rec["acceptance"]["accepted"]
            return rec
        commit = cand["commit_sha"]
        d = self.commit_diff(commit)
        patch = self.dir / f"diff_iter{k}.patch"
        patch.write_text(d["full"], encoding="utf-8")
        refusals = self.guard(d)
        vcfg = self.cfg.get("verify") or {}
        # LQ-1234 masking lint (wired by LQ-1236): a fix that hides the failure is refused, softly, so the next
        # iteration can redo it. Textual over added lines; the codes name the rule and the place.
        if vcfg.get("masking_lint", True):
            refusals = [*refusals, *(
                {"hard": False, "code": f"masking:{m['rule']}", "path": m.get("path"), "line": m.get("line")}
                for m in V.lint_masking(d["full"])
            )]
        rec.update(
            candidate=cand,
            guard={"tree_sha": self.tree_of(commit), "refusals": refusals},
            diffstat=F.diffstat(d["numstat"]),
            diff_sha256=hashlib.sha256(d["full"].encode()).hexdigest()[:16],
            patch=str(patch),
            refusals=list(refusals),
        )
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
            red = self.eval_run(
                "red_first",
                self.checkout(f"it{k}-base", self.base, overlay),
                self.base,
                pyt,
                t_test,
                overlay_from=commit,
            )
            reproduced = bool(
                red["rc"] == 1
                and (red.get("pytest_proof") or {}).get("assertion_failures")
                and (red.get("pytest_proof") or {}).get("errors") == 0
            )
            co = self.checkout(f"it{k}-cand", commit)
            green = self.eval_run("targeted", co, commit, pyt, t_test)
            # LQ-1234 reliability (wired by LQ-1236): the first red/green must hold in every one of ``verify.runs``
            # runs, each on a fresh checkout. A run with no verdict (timeout, integrity break) is neither red nor green.
            n_runs = max(1, int(vcfg.get("runs", V.DEFAULT_RUNS)))
            reps: list[dict] = []

            def again(kind: str, name: str, sha: str, ov: Optional[dict] = None, ov_from: Optional[str] = None):
                def runner(argv, *, cwd=None, env=None, timeout_s=t_test):  # noqa: ARG001 -- run_n's runner seam
                    r = self.eval_run(kind, self.checkout(name, sha, ov), sha, list(argv), timeout_s, overlay_from=ov_from)
                    reps.append(r)
                    return r["rc"] if r["integrity_ok"] else None

                return runner

            red_ok = reproduced and (
                n_runs == 1
                or V.repro_reliable(
                    pyt, n_runs - 1, runner=again("red_first", f"it{k}-base-rep", self.base, overlay, commit), timeout_s=t_test
                )
            )
            green_ok = green["rc"] == 0 and (
                n_runs == 1
                or V.fixed_reliably(pyt, n_runs - 1, runner=again("targeted", f"it{k}-cand-rep", commit), timeout_s=t_test)
            )
            runs = [red, green, *reps]
            ci_argv = [str(a).replace("{python}", self.py).replace("{base_sha}", self.base) for a in it["ci_argv"]]
            if green_ok and red_ok and red["integrity_ok"] and green["integrity_ok"]:
                ci = self.eval_run("ci", co, commit, ci_argv, float(it["ci_timeout_s"]))
                runs.append(ci)
            else:
                ci = {"rc": None, "out": "", "err": "skipped"}
            suite = self.companion_suite(d, co, commit, vcfg) if ci["rc"] == 0 else {"rc": None, "out": "", "err": "skipped"}
            if suite.get("run_id"):
                runs.append(suite)
            for r in runs:
                if not r["integrity_ok"]:
                    rec["refusals"].append(
                        {
                            "hard": True,
                            "code": "integrity:checkout_or_git_mutated",
                            "run": r["kind"],
                            "run_id": r["run_id"],
                        }
                    )
            if self.tree_of(commit) != cand["tree_sha"]:
                rec["refusals"].append({"hard": True, "code": "integrity:candidate_tree_changed"})
            failing = F.failing_set(green["out"], ci["out"])
            if not reproduced:
                failing.append("red_first:test_passes_on_base")
            if green["rc"] != 0 and not F.failing_set(green["out"]):
                failing.append(f"targeted:exit_{green['rc']}")
            if ci["rc"] not in (0, None) and not F.failing_set(ci["out"]):
                failing.append(f"ci:exit_{ci['rc']}")
            if reproduced and not red_ok:
                failing.append("verify:repro_not_reliable")
            if green["rc"] == 0 and not green_ok:
                failing.append("verify:fix_not_reliable")
            if suite["rc"] not in (0, None):
                failing += F.failing_set(suite["out"]) or [f"suite:exit_{suite['rc']}"]
            failing += [f"guard:{r['code']}" for r in rec["refusals"]]
            rec.update(
                red_first=red_ok,
                targeted_rc=green["rc"],
                ci_rc=ci["rc"],
                ci_argv=ci_argv,
                verify={
                    "runs": n_runs,
                    "repro_reliable": red_ok,
                    "fixed_reliably": green_ok,
                    "repeat_rcs": [r["rc"] for r in reps],
                    "suite_rc": suite["rc"],
                    "suite": suite.get("test_command") or suite.get("err"),
                },
                failing=sorted(set(failing)),
                test_runs=[{k2: v for k2, v in r.items() if k2 not in ("out", "err")} for r in runs],
            )
            out_tail = (
                f"--- red-first on base (rc {red['rc']}) ---\n{red['out'][-1500:]}\n"
                f"--- targeted (rc {green['rc']}) ---\n{green['out'][-2500:]}\n"
                f"--- ci pr profile (rc {ci['rc']}) ---\n{ci['out'][-3000:]}{ci['err'][-500:]}\n"
                f"--- companion suite (rc {suite['rc']}) ---\n{suite['out'][-1500:]}{str(suite.get('err') or '')[-300:]}"
            )
            (self.dir / f"tests_iter{k}.log").write_text(out_tail, encoding="utf-8")
            shutil.rmtree(self.eval_root / f"it{k}-base", ignore_errors=True)
            shutil.rmtree(self.eval_root / f"it{k}-cand", ignore_errors=True)
            shutil.rmtree(self.eval_root / f"it{k}-base-rep", ignore_errors=True)
            shutil.rmtree(self.eval_root / f"it{k}-cand-rep", ignore_errors=True)
        rec["seconds"] = round(time.monotonic() - t0, 1)
        rec["output_tail"] = out_tail
        rec["acceptance"] = E.local_verdict(rec)  # independent of the backend's claims
        rec["passed"] = rec["acceptance"]["accepted"]
        return rec

    def companion_suite(self, d: dict, co: Optional[Path], commit: str, vcfg: dict) -> dict:
        """LQ-1234 ``full_suite_cmd`` (wired by LQ-1236): every test the diff touches plus every test named for a
        changed module, run on the candidate checkout. The CI gate registry is excluded from "changed" (its test IS
        the CI run). When the selection widens to the whole ``tests/`` tree, the broad CI profile that already passed
        stands in for it, and the record says so: a whole-tree run inside one fix attempt would only time out."""
        if not vcfg.get("suite", True):
            return {"rc": None, "out": "", "err": "suite_disabled"}
        changed = [
            ln.split("\t")[-1]
            for ln in d["name_status"].splitlines()
            if ln.strip() and not ln.startswith("D") and ln.split("\t")[-1] != "scripts/run_cio_hardening_ci.py"
        ]
        known = git(self.repo, "ls-tree", "-r", "--name-only", commit, "--", "tests")["out"].split()
        argv = V.full_suite_cmd(
            changed, pytest_cmd=[self.py, "-m", "pytest", "-rfE", "-p", "no:cacheprovider"], known_tests=known
        )
        if argv[argv.index("-q") + 1 :] == ["tests"]:
            return {"rc": None, "out": "", "err": "whole_tree:covered_by_ci_profile"}
        return self.eval_run("suite", co, commit, argv, float(self.cfg["iteration"]["ci_timeout_s"]))

    # -- ship exactly the evaluated commit
    def prepush_check(self, rec: dict) -> dict:
        """Immediately before the branch update / push: the commit's tree is re-read from the object store and the
        diff guard re-run on it. The ship verdict refuses unless sha, tree and guard all match the evaluation."""
        commit = str((rec.get("candidate") or {}).get("commit_sha") or "")
        tree_now = self.tree_of(commit) if commit else None
        refusals = self.guard(self.commit_diff(commit)) if commit else [{"code": "no_candidate"}]
        return E.ship_verdict(
            rec.get("acceptance"), commit_sha=commit, tree_sha=tree_now or "", prepush_refusals=refusals
        )

    def land_local(self, commit: str) -> dict:
        """Point the job branch at the evaluated commit (compare-and-swap from base) and write fix.patch from it."""
        r = git(self.repo, "update-ref", f"refs/heads/{self.branch}", commit, self.base)
        patch = git(self.repo, "format-patch", "-1", "--stdout", commit)["out"]
        (self.dir / "fix.patch").write_text(patch, encoding="utf-8")
        return {"rc": r["rc"], "head": commit, "err": r["err"][-300:]}

    def push_and_pr(self, body: str, commit: str, gh_view: Optional[Callable[[list[str]], dict]] = None) -> dict:
        # Belt (operator 2026-11-08 no-push order): under the local-only switch, or without push permission, this
        # method refuses before any git/gh call, whatever the caller decided.
        if F.local_only(self.cfg) is not None or not self.may_push:
            return {"ok": False, "why": "local_only_no_push", "local_only_refused": True}
        env = dict(self.environ)
        env.pop("TRADEAI_REMOTE_PUSH_OVERRIDE", None)  # never an override: the budget binds
        env["TRADEAI_REMOTE_PUSH_AUTHORIZED"] = "1"
        # push the evaluated SHA itself, never "whatever the branch points at now"
        p = run(
            ["git", "-C", str(self.fix_wt), "push", self.cfg["repo"]["remote"], f"{commit}:refs/heads/{self.branch}"],
            env=env,
            timeout=600,
        )
        if p["rc"] != 0:
            return {"ok": False, "why": f"push_failed:{(p['err'] or p['out'])[-300:]}"}
        body_path = self.dir / "pr_body.md"
        body_path.write_text(body, encoding="utf-8")
        title = f"fix({self.job['lane']}): self-heal fix ({self.job['job_id']})"
        base_args = [
            "gh",
            "pr",
            "create",
            "--base",
            self.cfg["repo"]["base_branch"],
            "--head",
            self.branch,
            "--title",
            title,
            "--body-file",
            str(body_path),
        ]
        # AGENTS.md §24.16 (approved text): ONE **draft** PR labelled `pr_label` per fix job. The old path created a
        # ready-for-review PR and, when the label could not be applied, silently retried WITHOUT it — so the lane
        # could ship a non-draft, unlabelled PR that the policy text says cannot exist (cx-openai-2 F1, lead-verified).
        # The label is now a PRECONDITION, checked before anything is created: if the repository does not carry it the
        # job fails visibly rather than shipping something the operator did not authorise.
        label = str(self.cfg["repo"]["pr_label"])
        listed = run(["gh", "label", "list", "--limit", "200", "--json", "name"],
                     cwd=self.fix_wt, env=env, timeout=60)
        try:
            known_labels = {str(x.get("name")) for x in json.loads(listed["out"] or "[]") if isinstance(x, dict)}
        except ValueError:
            known_labels = set()
        if listed["rc"] != 0 or label not in known_labels:
            # Visible failure, and no PR exists to be merged by mistake.
            return {"ok": False, "why": f"pr_label_unavailable:{label}", "pushed": True, "policy_breach": True}
        pr = run(base_args + ["--draft", "--label", label], cwd=self.fix_wt, env=env, timeout=120)
        if pr["rc"] != 0:
            return {"ok": False, "why": f"pr_create_failed:{pr['err'][-300:]}", "pushed": True}
        url = pr["out"].strip().splitlines()[-1] if pr["out"].strip() else ""
        num = url.rstrip("/").rsplit("/", 1)[-1]
        out = {"ok": True, "pr_url": url, "pr_number": int(num) if num.isdigit() else None, "labelled": True}
        # Verify what actually exists rather than trusting the exit code: the head MUST be the evaluated commit, and
        # the PR MUST really be a draft carrying the label (a create can succeed while either is wrong).
        view = run(
            ["gh", "pr", "view", url or self.branch, "--json", "headRefOid,isDraft,labels"],
            cwd=self.fix_wt, env=env, timeout=60,
        )
        try:
            meta = json.loads(view["out"] or "{}")
        except ValueError:
            meta = {}
        head = str(meta.get("headRefOid") or "")
        out["pr_head"] = head
        out["draft"] = bool(meta.get("isDraft"))
        actual_labels = {str(x.get("name")) for x in (meta.get("labels") or []) if isinstance(x, dict)}
        if not out["draft"]:
            # §24.16 says draft; a ready PR here is a policy breach, not a cosmetic difference.
            out.update(ok=False, why="pr_not_draft", pushed=True, draft_missing=True, policy_breach=True)
        if label not in actual_labels:
            out.update(ok=False, why=out.get("why") or f"pr_label_missing:{label}", pushed=True,
                       label_missing=True, policy_breach=True)
        if head != commit:
            out.update(
                ok=False,
                why=out.get("why") or f"pr_head_mismatch:{head[:12] or 'unreadable'}!={commit[:12]}",
                pushed=True,
                head_mismatch=True,
            )
        return out


@_job_deadline
def attempt_job(
    job: dict,
    evidence: dict,
    *,
    cfg: dict,
    environ: dict,
    now: Callable[[], datetime],
    evidence_dir: Path,
    may_push: bool,
    rails: str,
    backend: str,
    remember: Callable[[dict], None] = lambda row: None,
    persist: Callable[[dict], None] = lambda job: None,
    progress: Callable[[dict, dict], None] = lambda job, rec: None,
) -> dict:
    """Run the iteration loop for one job and move it to its next state. Returns the job. ``persist`` makes the job
    durable (called before the backend first runs and after every iteration); ``progress`` records partial evidence
    on the durable claim."""
    a = Attempt(
        job, evidence, cfg=cfg, environ=environ, now=now, evidence_dir=evidence_dir, may_push=may_push, backend=backend
    )
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
        lower = F.reported_cost(job.get("cost_usd")) or 0
        # Persist uncertain spend BEFORE starting the provider. A harness crash must retain the full reservation.
        job.update(cost_usd=None, cost_status="unknown", known_cost_lower_bound_usd=lower)
        persist(job)
        rec = a.iterate(k, prev, rails, lower)
        cost = F.reported_cost(rec["backend_result"].get("cost_usd"))
        job["cost_usd"] = round(lower + cost, 4) if cost is not None else None
        job["cost_status"] = "known" if cost is not None else "unknown"
        job["known_cost_lower_bound_usd"] = round(lower + (cost or 0), 4)
        job["iterations"].append({k2: v for k2, v in rec.items() if k2 != "output_tail"})
        remember(F.memory_row(job, event="iteration", now=now(), backend=backend, iteration=rec))
        progress(job, rec)
        persist(job)
        last = rec
        nc_why = rec.get("not_code")
        if nc_why:
            # The agent says the cause is not in this repo: escalate to a person, keep nothing it changed.
            F.transition(
                job, F.ESCALATED_NOT_CODE, now(), reason=f"agent_not_code:{nc_why}"[:300], updated_at=now().isoformat()
            )
            a.teardown(keep_branch=False)
            return job
        if cost is None:
            stop = "cost_unknown"
            break
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
            F.transition(
                job,
                F.FIX_REFUSED,
                now(),
                reason=f"ship_check_failed:{','.join(ship['failed'])}",
                updated_at=now().isoformat(),
            )
            a.teardown(keep_branch=False)
            return job
        commit = ship["commit_sha"]
        c = a.land_local(commit)
        if c["rc"] != 0:
            F.transition(
                job, F.FIX_FAILED, now(), reason=f"branch_update_failed:{c['err']}", updated_at=now().isoformat()
            )
            a.teardown(keep_branch=False)
            return job
        job["head_sha"] = commit
        job["evaluated"] = {
            "commit_sha": commit,
            "tree_sha": ship["tree_sha"],
            "test_run_ids": last["acceptance"].get("test_run_ids"),
            "guard_verdict": last["acceptance"].get("guard_verdict"),
        }
        body = F.pr_body(job, evidence)
        (evidence_dir / "pr_body.md").write_text(body, encoding="utf-8")
        if may_push and F.local_only(cfg) is None:
            pr = a.push_and_pr(body, commit)
            if pr.get("ok"):
                F.transition(
                    job,
                    F.FIX_PR_OPENED,
                    now(),
                    pr_url=pr["pr_url"],
                    pr_number=pr["pr_number"],
                    labelled=pr["labelled"],
                    pr_head=pr.get("pr_head"),
                    updated_at=now().isoformat(),
                )
            elif pr.get("head_mismatch"):
                F.transition(
                    job,
                    F.FIX_REFUSED,
                    now(),
                    reason=pr["why"],
                    pr_url=pr.get("pr_url"),
                    pr_number=pr.get("pr_number"),
                    pr_head=pr.get("pr_head"),
                    updated_at=now().isoformat(),
                )
            elif pr.get("policy_breach"):
                # §24.16 requires ONE draft PR labelled pr_label. Anything else is refused, not "ready local":
                # the work is fine, but the lane may not ship a PR the approved text forbids.
                F.transition(
                    job,
                    F.FIX_REFUSED,
                    now(),
                    reason=pr["why"],
                    pr_url=pr.get("pr_url"),
                    pr_number=pr.get("pr_number"),
                    pr_head=pr.get("pr_head"),
                    updated_at=now().isoformat(),
                )
            else:
                F.transition(job, F.FIX_READY_LOCAL, now(), reason=pr["why"], updated_at=now().isoformat())
        else:
            why = "local_only_no_push" if F.local_only(cfg) is not None else "push_not_allowed"
            F.transition(job, F.FIX_READY_LOCAL, now(), reason=why, updated_at=now().isoformat())
        a.teardown(keep_branch=True)
        return job
    new = F.FIX_REFUSED if stop == "guard_refused" else F.FIX_FAILED
    F.transition(job, new, now(), reason=stop, updated_at=now().isoformat())
    a.teardown(keep_branch=False)
    return job


# ---------------------------------------------------------------- output recovered (one swappable hook)


def recovery_contract(cfg: dict, root: Path) -> dict:
    """The output contract ``output_recovered`` applies (architect review 2026-10-16, finding 4)."""
    return {
        "kind": "live_receipt_output_verdict@v1",
        "ledger": str(root / cfg["intake"]["ledger_rel"]),
        "output_verdicts": sorted(F.OUTPUT_MET),
        "effective_mode": "live",
        "state": "RUN_DONE",
        "exit_code": 0,
    }


def output_recovered(lane: str, since: Optional[datetime], contract: dict) -> dict:
    """Did ``lane``'s OUTPUT recover after ``since`` by its contract? The ONLY recovery check the fixer makes.

    Reads the coordination ledger without mutation and delegates every decision to the existing shared
    RecoveryVerdict owner through lib/self_heal_fixer.receipt_meets_output_contract. Keep the full durable row:
    projecting away lane/attempt would prevent the validator from detecting a conflicting embedded receipt.
    A lane with no qualifying live output remains ``fix_deployed``.
    """
    base = {
        "validator": "self_heal_fixer.output_recovered@shared-v2",
        "contract": contract.get("kind"),
        "lane": lane,
        "since": since.isoformat() if since else None,
        "recovered": False,
    }
    ledger = Path(str(contract.get("ledger") or ""))
    if since is None:
        return {**base, "why": "no_deployed_at"}
    if not ledger.is_file():
        return {**base, "why": "ledger_missing"}
    try:
        con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT * FROM runs WHERE lane_id=? AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 200",
                (lane,),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return {**base, "why": f"ledger_unreadable:{type(exc).__name__}"}
    reasons: dict[str, int] = {}
    for durable_row in rows:
        row = dict(durable_row)
        why = F.receipt_meets_output_contract(row, since, lane=lane)
        if why is None:
            rec = RV.receipt_of(row)
            return {
                **base,
                "recovered": True,
                "basis": "live_receipt_output_verdict",
                "run_id": row["run_id"],
                "finished_at": row["finished_at"],
                "output_verdict": (rec.get("output_verdict") or {}).get("verdict"),
            }
        reasons[why] = reasons.get(why, 0) + 1
    return {**base, "why": "no_receipt_meets_contract", "checked": len(rows), "reasons": reasons}


# ---------------------------------------------------------------- lifecycle advance (read-only probes)


def _lifecycle_deadline(fn):
    @functools.wraps(fn)
    def bounded(job, **kwargs):
        if job.get("state") not in (F.FIX_READY_LOCAL, F.FIX_PR_OPENED, F.FIX_DEPLOYED, F.OUTPUT_RECOVERED):
            return None
        deadline = _deadline_at(job.get("deadline_at"))
        now = kwargs["now"]
        if deadline is None or deadline.tzinfo is None or now.tzinfo is None:
            job["deadline_hold"] = "absolute_job_deadline_unavailable"
            return None
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            job["deadline_hold"] = "absolute_job_deadline_exceeded"
            return None
        absolute = time.monotonic() + remaining
        existing = _DEADLINE.get()
        if existing is not None:
            absolute = min(absolute, existing)
        token = _DEADLINE.set(absolute)
        original_gh = kwargs["gh"]

        def gh(argv):
            if time.monotonic() >= absolute:
                return {"rc": 124, "out": "", "err": "absolute job deadline exceeded"}
            result = original_gh(argv)  # canonical transport calls run(), which uses this same deadline
            return (
                result
                if time.monotonic() < absolute
                else {"rc": 124, "out": "", "err": "absolute job deadline exceeded"}
            )

        kwargs["gh"] = gh
        try:
            return fn(job, **kwargs)
        finally:
            _DEADLINE.reset(token)

    return bounded


@_lifecycle_deadline
def advance(
    job: dict,
    *,
    cfg: dict,
    now: datetime,
    diag_state: Optional[dict],
    root: Path,
    gh: Callable[[list[str]], dict],
    repo: Path,
) -> Optional[str]:
    """Move a shipped job along fix_pr_opened -> fix_deployed -> output_recovered -> incident_resolved."""
    st = job.get("state")
    if st == F.FIX_READY_LOCAL and job.get("branch"):
        r = gh(["gh", "pr", "list", "--head", job["branch"], "--state", "all", "--json", "number,url"])
        rows = json.loads(r["out"] or "[]") if r["rc"] == 0 else []
        if rows:
            F.transition(
                job,
                F.FIX_PR_OPENED,
                now,
                pr_number=rows[0].get("number"),
                pr_url=rows[0].get("url"),
                updated_at=now.isoformat(),
                opened_by="operator",
            )
            return F.FIX_PR_OPENED
    if st == F.FIX_PR_OPENED and job.get("pr_number"):
        r = gh(
            [
                "gh",
                "pr",
                "view",
                str(job["pr_number"]),
                "--json",
                "state,mergeCommit,mergedAt,headRefOid,statusCheckRollup",
            ]
        )
        doc = json.loads(r["out"] or "{}") if r["rc"] == 0 else {}
        if doc:
            local = next((i.get("acceptance") for i in reversed(job.get("iterations") or []) if i.get("passed")), None)
            policy = E.ci_policy(cfg.get("acceptance"))
            prv = E.pr_head_verdict(
                doc,
                expected_head=str(job.get("head_sha") or ""),
                required=policy["required_checks"],
                policy_version=policy["version"],
            )
            job["acceptance"] = E.final_acceptance(local, prv)
            job["acceptance"]["pr_head"] = prv
        if doc.get("state") == "CLOSED":
            F.transition(job, F.FIX_CLOSED, now, reason="pr_closed_unmerged", updated_at=now.isoformat())
            return F.FIX_CLOSED
        merge = (doc.get("mergeCommit") or {}).get("oid")
        if doc.get("state") == "MERGED" and merge:
            job["merged_sha"], job["merged_at"] = merge, doc.get("mergedAt")
            if not E.accepted_for_policy(job.get("acceptance"), cfg.get("acceptance"), job.get("head_sha")):
                job["acceptance_hold"] = "required_exact_head_acceptance_unavailable_or_rejected"
                return None
            cur = Path(cfg["lifecycle"]["release_current_sha_file"])
            try:
                cur_sha = cur.read_text(encoding="utf-8").strip()
            except OSError:
                cur_sha = ""
            if cur_sha and git(repo, "merge-base", "--is-ancestor", merge, cur_sha)["rc"] == 0:
                F.transition(
                    job,
                    F.FIX_DEPLOYED,
                    now,
                    release_sha=cur_sha,
                    deployed_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
                return F.FIX_DEPLOYED
        return None
    if st in (F.FIX_DEPLOYED, F.OUTPUT_RECOVERED) and not E.accepted_for_policy(
        job.get("acceptance"), cfg.get("acceptance"), job.get("head_sha")
    ):
        job["acceptance_hold"] = "required_exact_head_acceptance_unavailable_or_rejected"
        return None
    if st == F.FIX_DEPLOYED:
        rv = output_recovered(job["lane"], F._parse(job.get("deployed_at")), recovery_contract(cfg, root))
        job["recovery_check"] = rv
        if rv.get("recovered"):
            F.transition(
                job,
                F.OUTPUT_RECOVERED,
                now,
                output_at=rv.get("finished_at"),
                output_run=rv.get("run_id"),
                recovery_basis=rv.get("basis"),
                updated_at=now.isoformat(),
            )
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
    tried = [
        {
            "k": r.get("iteration"),
            "failing": (r.get("failing") or [])[:6],
            "passed": r.get("passed"),
            "refusals": [x.get("code") for x in r.get("refusals") or []],
        }
        for r in job.get("iterations") or []
    ]
    return {
        "schema": "SelfHealFixEscalation@v1",
        "priority": "P1",
        "route": "operator_once",
        "job_id": job["job_id"],
        "lane": job["lane"],
        "signature": job["signature"],
        "incident_key": job.get("incident_key"),
        "state": job["state"],
        "reason": job.get("reason") or (job.get("refusal") or ["?"])[0],
        "detail": f"self-heal fixer could not ship a fix for {job['lane']}: {job.get('reason')}; "
        f"iterations={len(tried)}; cost={F.cost_label(job.get('cost_usd'))}",
        "tried": tried,
        "at": now.isoformat(),
    }


# ---------------------------------------------------------------- findings for the lead (written, never sent)
FINDINGS_INBOX_REL = "data/coordination/coordinator/inbox/claude-lead"


def findings_dir(cfg: dict, root: Path) -> Path:
    rel = str((cfg.get("findings") or {}).get("inbox_rel") or FINDINGS_INBOX_REL)
    return root / rel


def _slug(text: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")[:80] or "x"


def write_finding(cfg: dict, root: Path, name: str, text: str) -> str:
    """Atomically write one FINDING file into the lead's inbox. Never overwrites an existing file."""
    d = findings_dir(cfg, root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    if path.exists():
        return str(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def ready_local_finding(job: dict, now: datetime) -> tuple[str, str]:
    """(file name, markdown) for a job that reached fix_ready_local: the lead reviews and folds it; nothing was pushed."""
    its = job.get("iterations") or []
    last = its[-1] if its else {}
    name = f"FINDING-SELF-HEAL-READY-LOCAL-{_slug(job['job_id'])}.md"
    lines = [
        f"# FINDING — self-heal fix ready locally: {job['lane']} ({job['job_id']})",
        "",
        "The self-heal fixer ran under `arming.local_only`: the fix is committed on a LOCAL branch only. Nothing was "
        "pushed and no PR was opened. Lead: review the branch, then fold it or close it.",
        "",
        f"- lane: `{job['lane']}`",
        f"- job_id: `{job['job_id']}`",
        f"- defect_id: `{job.get('defect_id')}`",
        f"- signature: `{job.get('signature')}`",
        f"- branch (local, repo `{job.get('repo_root') or ''}`): `{job.get('branch')}`",
        f"- commit: `{job.get('head_sha')}`",
        f"- evidence dir: `{job.get('evidence_dir')}`",
        f"- iterations: {len(its)}; cost: {F.cost_label(job.get('cost_usd'))}",
        f"- test result (last iteration): passed={last.get('passed')} red_first={last.get('red_first')} "
        f"ci_rc={last.get('ci_rc')} tests_run={last.get('tests_run')}",
        f"- reason: `{job.get('reason')}`",
        f"- at: {now.isoformat()}",
        "",
        f"Review line: `Adversarial-review: MERGE|CHANGES reviewer=<non-author> head={job.get('head_sha')}`",
        "",
    ]
    return name, "\n".join(lines)


def non_code_finding(row: dict, now: datetime) -> tuple[str, str]:
    """(file name, markdown) for a failure a code change cannot fix: escalated to the lead, never admitted."""
    name = f"FINDING-SELF-HEAL-ESCALATION-{F.et_day(now)}-{_slug(row['lane'])}-{_slug(row.get('signature'))[:24]}.md"
    no_ev = str(row["class"]).startswith("no_evidence:")
    lines = [
        f"# FINDING — self-heal escalation ({'no evidence' if no_ev else 'non-code'}): {row['lane']} — {row['class']}",
        "",
        (
            "The self-heal fixer did NOT hand this failure to an agent: its evidence pack has no error text or no "
            "script (LQ-20261107-1228), so a fix could only be a guess. A person must find the failing run and its "
            "stderr, or the producer must attach them. One finding per signature per ET day."
            if no_ev
            else "The self-heal fixer did NOT admit this failure for a code fix: its class is not a code defect. It "
            "needs a person (dependency, data, timeout, audit block). One finding per signature per ET day."
        ),
        "",
        f"- lane: `{row['lane']}`",
        f"- class: `{row['class']}`",
        f"- signature: `{row.get('signature')}`",
        f"- defect_id: `{row.get('defect_id')}`",
        f"- job_id: `{row.get('job_id')}`",
        f"- incident_key: `{row.get('incident_key')}`",
        f"- failed_run_id: `{row.get('failed_run_id')}`",
        f"- at: {now.isoformat()}",
        "",
        "Error tail (redacted):",
        "",
        "```",
        F.redact(str(row.get("tail") or ""))[-1500:],
        "```",
        "",
    ]
    rb = row.get("runbook")
    if rb:
        lines += [
            "## Runbook (LQ-1231)",
            "",
            f"- entry: `{rb.get('entry')}` (category {rb.get('category')}) · action: `{rb.get('action')}`",
            f"- plan reason: `{rb.get('reason')}` · taken: `{rb.get('action_taken')}` · dry run: {rb.get('dry_run')}",
            *([f"- error: `{rb['error']}`"] if rb.get("error") else []),
            *(f"- step: {step}" for step in rb.get("human_steps") or []),
            "",
            *([str(rb["finding_text"]), ""] if rb.get("finding_text") else []),
        ]
    return name, "\n".join(lines)


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


def main(
    argv: Optional[list[str]] = None,
    *,
    now: Optional[Callable[[], datetime]] = None,
    grant_reader: Callable[[str], Optional[dict]] = default_grant_reader,
    environ: Optional[dict] = None,
    gh: Optional[Callable[[list[str]], dict]] = None,
) -> int:
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
        rows = [
            {k: j.get(k) for k in ("job_id", "lane", "state", "pr_url", "cost_usd", "updated_at")}
            for j in state.get("jobs", {}).values()
        ]
        print(
            json.dumps(
                {
                    "jobs": rows,
                    "claims": [
                        {
                            k: c.get(k)
                            for k in ("claim_id", "job_id", "state", "day", "reserved_usd", "spent_usd", "outcome")
                        }
                        for c in C.rows(claims_db)
                    ],
                },
                indent=1,
            )
        )
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
        return _cycle(
            args,
            cfg=cfg,
            apply=apply,
            root=root,
            state_path=state_path,
            receipt_path=receipt_path,
            claims_db=claims_db,
            environ=environ,
            now=now,
            grant_reader=grant_reader,
            gh=gh,
        )
    finally:
        if lock is not None:
            lock.release()


def _cycle(
    args,
    *,
    cfg: dict,
    apply: bool,
    root: Path,
    state_path: Path,
    receipt_path: Path,
    claims_db: Path,
    environ: dict,
    now: Callable[[], datetime],
    grant_reader: Callable[[str], Optional[dict]],
    gh: Callable[[list[str]], dict],
) -> int:
    s = cfg["state"]
    lease = cfg.get("lease") or {}
    lease_ttl, beat_every = float(lease.get("ttl_s", 300)), float(lease.get("heartbeat_s", 60))
    state = _load_json(state_path) or {"schema": F.STATE_SCHEMA, "jobs": {}}
    t = now()
    repo = Path(cfg["repo"]["repo_root"])
    out: dict[str, Any] = {
        "schema": F.RECEIPT_SCHEMA,
        "mode": "apply" if apply else "dry_run",
        "started_at": t.isoformat(),
        "admitted": [],
        "skipped": [],
        "attempted": [],
        "advanced": [],
        "escalations": [],
        "reconciled": [],
        "findings": [],
    }
    work = state if apply else json.loads(json.dumps(state))
    lo = F.local_only(cfg)
    if lo is not None:
        out["local_only"] = {"enabled": True, "why": str(lo.get("why") or "")[:200]}
    # REFUSAL, never a fallback (operator 2026-11-08, LQ-20261107-1258): self-heal runs on DeepSeek. If
    # `claude.provider` names a provider that cannot run -- or, for a live cycle, its key file is not readable on this
    # host -- the cycle stops HERE: no intake, no state write, no claim, and no model call on the operator's
    # Anthropic credential. A dry run is refused too, because its plan would otherwise quote a run that cannot happen.
    refusal, provider = provider_cycle_refusal(cfg, environ, apply=apply)
    out["provider"] = {k: provider[k] for k in (
        "name", "state", "reason", "auth_mode", "egress_allow", "launcher", "key_file",
        "launcher_readable", "key_readable")}
    if refusal:
        out["refused"] = refusal
        out["finished_at"] = t.isoformat()
        out["counts"] = {st: sum(1 for j in work.get("jobs", {}).values() if j.get("state") == st) for st in F.STATES}
        if apply:
            _atomic_write(receipt_path, out)
        elif args.out:
            _atomic_write(Path(args.out) / "receipt.json", out)
        print(json.dumps({k: out.get(k) for k in ("mode", "refused", "provider", "counts", "finished_at")},
                         indent=1, default=str))
        return 2

    def escalate_non_code(
        cls: str,
        *,
        lane: str,
        signature: Any,
        rc: Optional[dict],
        src: dict,
        runbook: Optional[tuple[str, dict, Optional[dict]]] = None,
    ) -> dict:
        """One ESCALATION FINDING per (ET day, lane, signature); dry runs report it without writing anything.

        ``runbook`` = (failure class, evidence, lane contract): a non-code failure also gets its LQ-1231 runbook plan,
        applied only when config ``runbooks.apply`` arms it (else a dry run), and rendered into the finding."""
        key = F.non_code_finding_key(lane, str(signature or ""), t)
        seen = work.setdefault("non_code_findings", {})
        row = {
            "kind": "non_code_escalation",
            "class": cls,
            "lane": lane,
            "signature": signature,
            "defect_id": src.get("defect_id"),
            "job_id": src.get("job_id"),
            "incident_key": src.get("incident_key") or src.get("key"),
            "failed_run_id": src.get("failed_run_id"),
            "tail": str((rc or {}).get("stderr_tail") or src.get("stderr_tail") or "")[-1500:],
            "key": key,
        }
        if key in seen:
            row["deduped"] = True
            return row
        if runbook is not None:
            rb_cls, rb_ev, rb_contract = runbook
            rb_state = work.setdefault("runbook_state", {}).setdefault(lane, {})
            row["runbook"] = run_runbook(
                rb_cls, {**rb_ev, "lane": lane}, rb_contract, state=rb_state, now=t,
                apply_enabled=apply and bool(rbcfg.get("apply")),
            )
            out["runbooks"].append(
                {"lane": lane, "class": rb_cls, **{k: v for k, v in row["runbook"].items() if k != "finding_text"}}
            )
        name, text = non_code_finding(row, t)
        row["path"] = write_finding(cfg, root, name, text) if apply else str(findings_dir(cfg, root) / name)
        row["written"] = bool(apply)
        seen[key] = {"at": t.isoformat(), "path": row["path"], "class": cls}
        # keep a week of dedupe keys; older days can never collide with today's key
        for k in [k for k in seen if k.split("|", 1)[0] < F.et_day(t - timedelta(days=7))]:
            seen.pop(k, None)
        out["findings"].append({k: v for k, v in row.items() if k not in ("tail", "runbook")})
        return row

    safety = cfg.get("safety") or {}
    rbcfg = cfg.get("runbooks") or {}
    tcfg = cfg.get("triage") or {}
    out["runbooks"] = []
    metrics_path = root / str(safety.get("metrics_rel") or METRICS_REL)
    metric_extra: list[dict] = []
    out["metrics_rows"] = 0

    def emit_metrics() -> None:
        """One metrics row per job transition not yet emitted (cursor ``metrics_n`` on the job), plus any extra
        rows (insufficient_evidence). Append-only; dry runs only count the rows they would write."""
        rows: list[dict] = []
        for job in work.get("jobs", {}).values():
            hist = job.get("history") or []
            done = int(job.get("metrics_n") or 0)
            for h in hist[done:]:
                at = M.parse_ts(h.get("at")) or t
                rows.append(M.row_from_job(job, str(h.get("state")), at, F.reported_cost(job.get("cost_usd"))))
            job["metrics_n"] = len(hist)
        rows.extend(metric_extra)
        metric_extra.clear()
        out["metrics_rows"] += len(rows)
        if apply:
            for row in rows:
                M.append_row(row, metrics_path)

    def save() -> None:
        emit_metrics()
        if apply:
            _atomic_write(state_path, work)

    def finish() -> int:
        out["finished_at"] = now().isoformat()
        if apply:
            _atomic_write(receipt_path, {**out, "ok_at": out["finished_at"]})
        elif args.out:
            _atomic_write(Path(args.out) / "receipt.json", out)
        print(json.dumps({k: out.get(k) for k in ("mode", "killed")}, default=str))
        return 0

    # LQ-1236 order: kill switch first. Nothing is reconciled, admitted, attempted or advanced while it is set.
    killed, kill_why = SAFE.kill_switch_active(
        safety, environ, root / str(safety.get("kill_file_rel") or KILL_FILE_REL)
    )
    if killed:
        out["killed"] = kill_why
        return finish()

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
                F.transition(
                    job, F.FIX_INTERRUPTED, t, reason=f"interrupted:{c['why']}", interrupted=c, updated_at=t.isoformat()
                )
                remember(
                    F.memory_row(
                        job,
                        event="attempt_interrupted",
                        now=t,
                        backend=job.get("backend"),
                        reason=c["why"],
                        partial=c.get("partial"),
                        reserved_usd_counted=c.get("reserved_usd_counted"),
                    )
                )
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
        inc.setdefault(
            "script",
            F.script_from_argv((rc or {}).get("argv") or []) or ((row or {}).get("scheduler") or {}).get("match"),
        )
        nc = F.non_code_class(inc, rc, cfg)
        if nc:
            sig = inc.get("signature") or F.local_signature(lane, (rc or {}).get("stderr_tail") or inc.get("stderr_tail"))
            esc = escalate_non_code(
                nc, lane=lane, signature=sig, rc=rc, src=inc,
                runbook=(nc, {**(rc or {}), **inc}, lane_contracts_for(lane, row)),
            )
            out["skipped"].append({"lane": lane, "why": f"non_code:{nc}", "finding": esc.get("path"),
                                   "deduped": bool(esc.get("deduped"))})
            continue
        # LQ-20261107-1228: no error text or no script -> nothing for an agent to fix from; a person finds the run.
        gap = F.evidence_gap(
            F.build_evidence({"lane": lane}, incident=inc, receipt=rc, registry_row=row, base_sha="", cfg=cfg)
        )
        if gap:
            sig = inc.get("signature") or F.local_signature(lane, (rc or {}).get("stderr_tail") or inc.get("stderr_tail"))
            esc = escalate_non_code(f"no_evidence:{gap}", lane=lane, signature=sig, rc=rc, src=inc)
            out["skipped"].append({"lane": lane, "why": f"no_evidence:{gap}", "finding": esc.get("path"),
                                   "deduped": bool(esc.get("deduped"))})
            if not esc.get("deduped"):
                metric_extra.append(M.row_from_job({"job_id": f"noev:{F.dedupe_key(lane, str(sig))}", "lane": lane},
                                                   "insufficient_evidence", t))
            continue
        job, why = F.admit(work, inc, now=t, cfg=cfg, held=held)
        if not job:
            out["skipped"].append({"lane": lane, "why": why})
            continue
        out["admitted"].append(
            {
                "job_id": job["job_id"],
                "lane": lane,
                "state": job["state"],
                "why": why,
                "defect_id": job.get("defect_id"),
            }
        )
        remember(F.memory_row(job, event="consumed", now=t, backend=None, contract=job.get("contract")))
        ev_by_job[job["job_id"]] = {"incident": inc, "receipt": rc, "row": row}
        if job["state"] == F.FIX_REFUSED:
            out["escalations"].append(escalation_for(job, t))
            job["escalated_at"] = t.isoformat()
    save()
    # arming + policy
    base = resolve_base(repo, cfg, apply=apply, environ=environ)
    base_sha = base["sha"]
    agents = agents_text_at(repo, base_sha) if base_sha else ""
    grant = grant_reader(cfg["arming"]["grant_tier"])
    day = F.et_day(t)

    def jobs_today() -> int:
        ledger_jobs = C.day_usage(claims_db, day)["jobs"] if apply else 0
        return max(F.jobs_started_today(work, now()), ledger_jobs)

    arming = F.arming_verdict(grant, cfg=cfg, jobs_today=jobs_today())
    policy = F.policy_verdict(agents, cfg)
    # Under the local-only switch nothing may push, whatever AGENTS.md at the base says (operator 2026-11-08).
    may_push = bool(policy["push_allowed"]) and lo is None and arming.get("may_push", True) is not False
    backend, backend_why = F.select_backend(cfg)
    out.update(
        arming=arming,
        policy=policy,
        base_sha=base_sha,
        base={k: base[k] for k in ("ref", "source", "why")},
        fetch_rc=base["fetch_rc"],
        backend={"name": backend, "why": backend_why,
                 "model_provider": provider["name"] or "anthropic_cli",
                 "provider_state": provider["state"]},
    )
    names = [n for n in (cfg.get("backends") or {}) if not n.startswith("_")]
    queue = [j for j in work.get("jobs", {}).values() if j.get("state") == F.FIX_REQUESTED]
    queue.sort(key=lambda j: str(j.get("created_at")))
    it = cfg["iteration"]
    budget = int(cfg["arming"]["max_jobs_per_cycle"])
    for job in queue:
        if budget <= 0:
            break
        src = ev_by_job.get(job["job_id"]) or {
            "incident": {"lane": job["lane"], "key": job.get("escalation_key")},
            "receipt": failed_receipt(ledger, job["lane"], job.get("failed_run_id")),
            "row": registry_row(job["lane"]),
        }
        # A job queued before the non-code rule (or whose failing run shows a non-code cause) is refused, not fixed;
        # it does not use the cycle's job budget.
        nc = F.non_code_class({**src["incident"], "failure_kind": job.get("failure_kind")}, src["receipt"], cfg)
        if nc:
            F.transition(job, F.FIX_REFUSED, t, reason=f"non_code:{nc}", updated_at=t.isoformat())
            job["escalated_at"] = t.isoformat()
            esc = escalate_non_code(
                nc, lane=job["lane"], signature=job.get("signature"), rc=src["receipt"], src=job,
                runbook=(nc, {**(src["receipt"] or {}), **src["incident"]}, lane_contracts_for(job["lane"], src["row"])),
            )
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"refused:non_code:{nc}",
                                     "finding": esc.get("path"), "deduped": bool(esc.get("deduped"))})
            continue
        evidence = F.build_evidence(
            job,
            incident=src["incident"],
            receipt=src["receipt"],
            registry_row=src["row"],
            base_sha=base_sha,
            cfg=cfg,
            contracts=lane_contracts_for(job["lane"], src["row"]),
        )
        # LQ-20261107-1228: a job queued with an empty pack (no error text / no script) is refused and escalated,
        # never handed to a model; it does not use the cycle's job budget.
        gap = F.evidence_gap(evidence)
        if gap:
            F.transition(job, F.FIX_REFUSED, t, reason=f"no_evidence:{gap}", updated_at=t.isoformat())
            job["escalated_at"] = t.isoformat()
            metric_extra.append(M.row_from_job(job, "insufficient_evidence", t))
            esc = escalate_non_code(
                f"no_evidence:{gap}", lane=job["lane"], signature=job.get("signature"), rc=src["receipt"], src=job
            )
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"refused:no_evidence:{gap}",
                                     "finding": esc.get("path"), "deduped": bool(esc.get("deduped"))})
            continue
        # No served base -> no attempt (never a silent fallback to a stale origin/main); the job stays queued.
        if not base_sha:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"no_base:{base['why']}"})
            continue
        # Global daily cap across ALL lanes (LQ-1235): when reached, nothing more is attempted this cycle.
        usage = C.day_usage(claims_db, day) if apply else {"usd": 0.0}
        cap_ok, cap_why = SAFE.global_daily_cap({"jobs_today": jobs_today(), "cost_today_usd": usage["usd"]}, safety)
        if not cap_ok:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"global_cap:{cap_why}"})
            break
        # Already fixed on the served release (LQ-1236): the failing code changed since the failing run -> no model
        # is spent; the job closes (a fresh failure on the served code is admitted again after the cooldown).
        af = already_fixed_on_served(repo, evidence, base_sha) if (cfg.get("already_fixed") or {}).get("enabled", True) else None
        if af:
            F.transition(job, F.FIX_CLOSED, t, reason=f"already_fixed_on_served:{base_sha[:12]}", already_fixed=af,
                         updated_at=t.isoformat())
            out["attempted"].append({"job_id": job["job_id"], "outcome": "closed:already_fixed_on_served",
                                     "changed": af["changed"]})
            continue
        # Triage (LQ-1233): advisory, read-only, fail-closed to the rules. A confident non-code answer routes the job
        # to its runbook + a person instead of an agent. Off unless config ``triage.enabled``; never in a dry run
        # (it is a paid model call).
        if tcfg.get("enabled"):
            if apply:
                from lib import self_heal_triage as T  # lazy: only an enabled, applying cycle loads the model client

                tri = T.triage(evidence, evidence.get("contracts"), past_findings(cfg, root), now=t)
            else:
                tri = {"source": "skipped", "error": "dry_run"}
            job["triage"] = {k: tri.get(k) for k in ("class", "confidence", "source", "error", "similar",
                                                     "suggested_runbook")}
            job["triage"]["root_cause"] = str(tri.get("root_cause") or "")[:300] or None
            evidence["triage"] = job["triage"]
            tcls = str(tri.get("class") or "")
            if (tri.get("source") == "llm" and tcls in F.NON_CODE_CLASSES
                    and float(tri.get("confidence") or 0) >= float(tcfg.get("min_confidence", 0.8))):
                F.transition(job, F.FIX_REFUSED, t, reason=f"triage_non_code:{tcls}", updated_at=t.isoformat())
                job["escalated_at"] = t.isoformat()
                esc = escalate_non_code(
                    f"triage:{tcls}", lane=job["lane"], signature=job.get("signature"), rc=src["receipt"], src=job,
                    runbook=(tcls, {**(src["receipt"] or {}), **src["incident"]}, evidence.get("contracts")),
                )
                out["attempted"].append({"job_id": job["job_id"], "outcome": f"refused:triage_non_code:{tcls}",
                                         "finding": esc.get("path"), "deduped": bool(esc.get("deduped"))})
                continue
        budget -= 1
        try:
            rails = F.extract_rails(agents)
        except ValueError as exc:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"no_rails:{exc}"})
            continue
        if not backend:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"no_backend:{backend_why}"})
            continue
        job["shadow_route"] = F.shadow_route(
            memory_old + memory_new, failure_kind=job.get("failure_kind"), backends=names, chosen=backend
        )
        if not apply:
            wt = Path(cfg["repo"]["worktree_root"])
            pytest_cmd = str(wt / f"{job['job_id']}-bin" / "pytest")
            home = environ.get("HOME") or str(Path.home())
            ah = str(wt / f"{job['job_id']}-home")
            asb = cfg.get("agent_sandbox") or {}
            # The dry run must describe what WOULD run, not the static defaults: provider_plan_view
            # mirrors Attempt.egress_allow() and the provider auth_mode override.
            plan_egress, _auth_cfg = provider_plan_view(cfg)
            binds, auth_why = F.agent_auth_binds(_auth_cfg, home=home, agent_home=ah, probe=_probe)
            plan = {
                "job": job,
                "evidence": evidence,
                "backend": backend,
                "provider": {k: provider[k] for k in (
                    "name", "state", "auth_mode", "egress_allow", "launcher", "key_file",
                    "launcher_readable", "key_readable")},
                "backend_argv": F.backend_argv(
                    cfg, backend, budget_usd=float(cfg["iteration"]["per_iteration_budget_usd"]), pytest_cmd=pytest_cmd
                ),
                "backend_call": "STUBBED (dry run: no model call)",
                "sandbox_prefix": F.eval_sandbox_prefix(
                    cfg,
                    repo_root=str(repo),
                    python_root=str(Path(cfg["repo"]["python"]).parent.parent),
                    checkout="<eval-checkout>",
                    scratch="<scratch>",
                    env={"<env>": "<child_env_names>"},
                    probe=_probe,
                ),
                "agent_sandbox_prefix": F.agent_sandbox_prefix(
                    cfg,
                    home=home,
                    repo_root=str(repo),
                    python_root=str(Path(cfg["repo"]["python"]).parent.parent),
                    extra_ro=["<claude-bin>", "<bindir>", "<egress-dir>"],
                    fix_wt="<fix_wt>",
                    agent_home=ah,
                    scratch="<scratch>",
                    auth_binds=binds,
                    env={"<env>": "<agent_env_names>"},
                    probe=_probe,
                ),
                "agent_auth": auth_why,
                "agent_env_names": sorted(
                    F.agent_env(
                        environ, cfg, scratch_state="<scratch>", agent_home=ah, proxy_port=asb.get("proxy_port")
                    )
                ),
                "egress_allow": plan_egress,
                "budget_reservation": {
                    "iterations": it["max_iterations"],
                    "usd": it["max_cost_usd"],
                    "seconds": float(it["max_minutes"]) * 60,
                },
                "branch": F.branch_name(job, cfg, t),
                "would_push": bool(arming["armed"] and may_push),
                "local_only": lo is not None,
                "env_names": sorted(F.child_env(environ, cfg, scratch_state="<scratch>")),
            }
            prompt = F.build_prompt(evidence, rails=rails, cfg=cfg, iteration=1, pytest_cmd=pytest_cmd)
            if args.out:
                od = Path(args.out)
                od.mkdir(parents=True, exist_ok=True)
                (od / "job.json").write_text(json.dumps(job, indent=1, default=str) + "\n", encoding="utf-8")
                (od / "evidence.json").write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
                (od / "prompt_iter1.md").write_text(prompt, encoding="utf-8")
                (od / "plan.json").write_text(json.dumps(plan, indent=1, default=str) + "\n", encoding="utf-8")
            out["attempted"].append(
                {
                    "job_id": job["job_id"],
                    "outcome": "dry_run_planned",
                    "prompt_chars": len(prompt),
                    "would_push": plan["would_push"],
                }
            )
            continue
        if not arming["armed"]:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"not_armed:{arming['why']}"})
            continue
        ev_dir = root / s["evidence_rel"] / job["job_id"]
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "evidence.json").write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
        # durable claim + the WHOLE budget reserved BEFORE the backend is launched (finding 3)
        claim_id, claim_why = C.claim(
            claims_db,
            dedupe_key=job["dedupe_key"],
            job_id=job["job_id"],
            day=day,
            reserve_iterations=int(it["max_iterations"]),
            reserve_usd=float(it["max_cost_usd"]),
            reserve_seconds=float(it["max_minutes"]) * 60,
            lease_ttl_s=lease_ttl,
            daily_job_cap=int(cfg["arming"]["daily_job_cap"]),
            daily_usd_cap=float(cfg["arming"].get("daily_cost_cap_usd", it["max_cost_usd"])),
            evidence_dir=str(ev_dir),
        )
        if not claim_id:
            out["attempted"].append({"job_id": job["job_id"], "outcome": f"not_claimed:{claim_why}"})
            continue
        job["claim_id"] = claim_id
        job["budget_reserved"] = {
            "iterations": int(it["max_iterations"]),
            "usd": float(it["max_cost_usd"]),
            "seconds": float(it["max_minutes"]) * 60,
        }

        def progress(j: dict, rec: dict, _cid: str = claim_id, _ev: Path = ev_dir) -> None:
            C.record_progress(
                claims_db,
                _cid,
                iterations_done=len(j.get("iterations") or []),
                spent_usd=j.get("cost_usd"),
                partial={
                    "iteration": rec.get("iteration"),
                    "failing": (rec.get("failing") or [])[:6],
                    "candidate": rec.get("candidate"),
                    "patch": rec.get("patch"),
                    "evidence_dir": str(_ev),
                    "branch": j.get("branch"),
                    "worktrees": j.get("worktrees"),
                },
            )

        try:
            with C.Heartbeat(claims_db, claim_id, lease_ttl_s=lease_ttl, every_s=beat_every):
                attempt_job(
                    job,
                    evidence,
                    cfg=cfg,
                    environ=environ,
                    now=now,
                    evidence_dir=ev_dir,
                    may_push=may_push,
                    rails=rails,
                    backend=backend,
                    remember=remember,
                    persist=lambda _j: save(),
                    progress=progress,
                )
        except Exception as exc:  # noqa: BLE001 — a harness bug ends the attempt, never leaves it "attempting"
            if job.get("state") in (F.FIX_REQUESTED, F.FIX_ATTEMPTING):
                if job["state"] == F.FIX_REQUESTED:
                    F.transition(job, F.FIX_ATTEMPTING, now(), iteration=0)
                F.transition(
                    job,
                    F.FIX_FAILED,
                    now(),
                    reason=f"harness_exception:{type(exc).__name__}:{exc}"[:300],
                    updated_at=now().isoformat(),
                )
        C.settle(
            claims_db,
            claim_id,
            outcome=str(job.get("state")),
            spent_usd=job.get("cost_usd"),
            iterations_done=len(job.get("iterations") or []),
        )
        save()
        remember(
            F.memory_row(
                job,
                event="attempt_outcome",
                now=now(),
                backend=backend,
                reason=job.get("reason"),
                iterations=len(job.get("iterations") or []),
                cost_usd=job.get("cost_usd"),
                head_sha=job.get("head_sha"),
                pr_url=job.get("pr_url"),
                shadow_route=job.get("shadow_route"),
            )
        )
        out["attempted"].append(
            {
                "job_id": job["job_id"],
                "outcome": job["state"],
                "reason": job.get("reason"),
                "iterations": len(job.get("iterations") or []),
                "cost_usd": job.get("cost_usd"),
            }
        )
        if job["state"] == F.ESCALATED_NOT_CODE and not job.get("escalated_at"):
            esc = escalate_non_code(
                "agent_not_code", lane=job["lane"], signature=job.get("signature"), rc=src["receipt"], src=job
            )
            out["attempted"][-1]["finding"] = esc.get("path")
        if job["state"] in (F.FIX_FAILED, F.FIX_REFUSED, F.ESCALATED_NOT_CODE) and not job.get("escalated_at"):
            out["escalations"].append(escalation_for(job, now()))
            job["escalated_at"] = now().isoformat()
        if job["state"] == F.FIX_READY_LOCAL and not job.get("finding_path"):
            job["repo_root"] = str(repo)
            name, text = ready_local_finding(job, now())
            job["finding_path"] = write_finding(cfg, root, name, text)
            out["findings"].append({"kind": "fix_ready_local", "job_id": job["job_id"], "path": job["finding_path"]})
            save()
        arming = F.arming_verdict(grant, cfg=cfg, jobs_today=jobs_today())
    for job in work.get("jobs", {}).values():
        if lo is not None:
            # local-only: no gh call of any kind; the lead folds fix_ready_local branches by hand
            break
        if job.get("state") in (F.FIX_READY_LOCAL, F.FIX_PR_OPENED, F.FIX_DEPLOYED, F.OUTPUT_RECOVERED):
            moved = advance(job, cfg=cfg, now=t, diag_state=diag, root=root, gh=gh, repo=repo)
            if moved:
                out["advanced"].append({"job_id": job["job_id"], "to": moved})
            if moved or job.get("acceptance"):
                remember(
                    F.memory_row(
                        job,
                        event=f"lifecycle:{moved or job['state']}",
                        now=t,
                        backend=job.get("backend"),
                        acceptance=job.get("acceptance"),
                        merged_sha=job.get("merged_sha"),
                        release_sha=job.get("release_sha"),
                    )
                )
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
    print(
        json.dumps(
            {
                k: out.get(k)
                for k in (
                    "mode",
                    "admitted",
                    "skipped",
                    "attempted",
                    "advanced",
                    "reconciled",
                    "arming",
                    "policy",
                    "local_only",
                    "findings",
                    "backend",
                    "provider",
                    "refused",
                    "counts",
                )
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

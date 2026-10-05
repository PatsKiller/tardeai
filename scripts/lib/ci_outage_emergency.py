"""Governed emergency release path for CI-provider (GitHub Actions) outages.

Operator 2026-10-05, during a GitHub Actions incident in which hosted-runner assignment failed and
every required job was cancelled before running a step: "you need to build an emergency path for
situations like this. Because this is not in our control."

The normal promote gate (scripts/release_grant_preflight.py --ci-only) requires completed,
successful push/main CI on the exact SHA. This module decides when that evidence may be
substituted — never silently. ALL of the following must hold, and each is machine-verified:

  1. Outage proof: githubstatus.com reports an unresolved incident naming Actions, AND every
     required workflow that is not green has jobs that never started (no steps, no runner).
     A required job that actually ran and failed blocks the path: real red stays red.
  2. Substitute evidence: the required workflows' own `run:` steps, replayed locally from the
     workflow file at the candidate SHA, plus the configured extra suites, all exit 0; logs are
     sha256-hashed and bound to the commit's TREE hash, so they cannot vouch for other content.
  3. Operator authority: an unexpired `release-emergency` grant (separate from release-write)
     whose text names the SHA and the incident id.
  4. Commit rule: the SHA is on origin/main, or (merge blocked by required checks) every
     non-merge commit it adds is already on GitHub (pushed, reviewable); the release is then
     labelled PENDING_RECONCILIATION and must reconcile by tree hash with the eventual main.

Every decision is appended to a durable ledger. A reconciliation pass marks the release
RECONCILED when GitHub CI passes on the deployed commit (or the main commit with the identical
tree), pages the operator on real failure or time-box expiry, and only rolls back when
`auto_rollback` is explicitly configured.

Pure functions take their inputs as arguments (runs, jobs, incidents, grants, git runner) so the
whole decision is testable without network or GitHub.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

SCHEMA = "CiOutageEmergency@v1"
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "ci_outage_emergency.yaml"
STATE_DIR = Path(os.environ.get("TRADEAI_EMERGENCY_STATE_DIR",
                                str(Path.home() / ".local" / "state" / "cio-phase2-exact-main" / "emergency")))
LEDGER_NAME = "ledger.jsonl"

PENDING = "PENDING_RECONCILIATION"
RECONCILED = "RECONCILED"
RECONCILE_FAILED = "RECONCILE_FAILED"
OVERDUE = "RECONCILE_OVERDUE"

_SHA40 = re.compile(r"[0-9a-f]{40}")


def load_config(path: Path = CONFIG_PATH) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ── 1. outage proof ──────────────────────────────────────────────────────────

def actions_incidents(payload: Mapping[str, Any], match: Iterable[str] = ("actions",)) -> list[dict]:
    """Unresolved status-page incidents that name Actions (in the title or a component)."""
    keys = [m.lower() for m in match]
    out = []
    for inc in (payload or {}).get("incidents") or []:
        if str(inc.get("status") or "").lower() in ("resolved", "postmortem"):
            continue
        names = [str(inc.get("name") or "")] + [str(c.get("name") or "") for c in inc.get("components") or []]
        if any(k in n.lower() for k in keys for n in names):
            out.append({"id": inc.get("id"), "name": inc.get("name"), "status": inc.get("status"),
                        "created_at": inc.get("created_at"), "shortlink": inc.get("shortlink")})
    return out


def job_never_started(job: Mapping[str, Any]) -> bool:
    """A job the provider never ran: no executed step and no runner assigned."""
    steps = job.get("steps") or []
    ran_steps = [s for s in steps if str(s.get("status") or "") in ("completed", "in_progress")
                 and str(s.get("conclusion") or "") not in ("skipped",)]
    if ran_steps or job.get("runner_name"):
        return False
    return str(job.get("conclusion") or "") in ("", "None", "cancelled", "skipped") or \
        str(job.get("status") or "") in ("queued", "waiting", "pending", "requested")


def evaluate_outage(sha: str, runs: list[dict], jobs_by_run: Mapping[int, list[dict]],
                    incidents: list[dict], required: Iterable[str]) -> dict:
    """Outage-affected when an Actions incident is open and every non-green required workflow
    never started. A required job that ran and failed → real_failure (blocks the path)."""
    required = sorted(required)
    latest: dict[str, dict] = {}
    for run in runs:
        if run.get("head_sha") != sha or run.get("event") != "push" or run.get("head_branch") != "main":
            continue
        path = str(run.get("path") or "").split("@", 1)[0]
        order = (int(run.get("run_number") or 0), int(run.get("id") or 0), int(run.get("run_attempt") or 1))
        if path not in latest or order > latest[path]["_order"]:
            latest[path] = {**run, "_order": order}
    workflows, real_failures, not_started = [], [], []
    for path in required:
        run = latest.get(path)
        if run is None:
            not_started.append(path)                    # never created (provider did not schedule it)
            workflows.append({"path": path, "state": "NOT_SCHEDULED"})
            continue
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            workflows.append({"path": path, "run_id": run.get("id"), "state": "SUCCESS"})
            continue
        jobs = list(jobs_by_run.get(int(run.get("id") or 0)) or [])
        ran = [j for j in jobs if not job_never_started(j)]
        failed = [j for j in ran if str(j.get("conclusion") or "") not in ("success", "skipped", "")]
        state = "NEVER_STARTED" if (jobs and not ran) or (not jobs and run.get("status") in ("queued", "pending", "waiting")) \
            else ("REAL_FAILURE" if failed else ("RUNNING" if run.get("status") != "completed" else "UNKNOWN"))
        rec = {"path": path, "run_id": run.get("id"), "run_attempt": run.get("run_attempt"), "state": state,
               "jobs": [{"id": j.get("id"), "name": j.get("name"), "conclusion": j.get("conclusion"),
                         "steps": len(j.get("steps") or []), "runner": j.get("runner_name") or None} for j in jobs]}
        workflows.append(rec)
        if state == "NEVER_STARTED":
            not_started.append(path)
        elif state == "REAL_FAILURE":
            real_failures.append(path)
        else:
            real_failures.append(path)                  # running/unknown is not an outage — wait for it
    errors = []
    if not _SHA40.fullmatch(sha or ""):
        errors.append("candidate_sha_must_be_full")
    if not incidents:
        errors.append("no_unresolved_actions_incident")
    if real_failures:
        errors.append("required_workflow_ran_or_pending:" + ",".join(real_failures))
    if not not_started:
        errors.append("no_outage_affected_workflow (normal gate applies)")
    return {"ok": not errors, "sha": sha, "incidents": incidents, "workflows": workflows,
            "outage_affected": not_started, "errors": errors}


# ── 2. substitute evidence (replayed workflows + extra suites) ───────────────

_KNOWN_EXPR = {
    "github.event_name": "push",
    "github.base_ref": "",
    "github.ref_name": "main",
}


def _subst(text: str, sha: str) -> tuple[str, list[str]]:
    unknown: list[str] = []

    def rep(m: re.Match) -> str:
        expr = m.group(1).strip()
        if expr == "github.sha":
            return sha
        if expr in _KNOWN_EXPR:
            return _KNOWN_EXPR[expr]
        unknown.append(expr)
        return m.group(0)
    return re.sub(r"\$\{\{\s*([^}]+?)\s*\}\}", rep, text or ""), unknown


def _if_allows(cond: Any) -> Optional[bool]:
    """Evaluate the step `if:` forms we understand for a push/main run; None = unknown."""
    if cond is None:
        return True
    c = str(cond).replace("${{", "").replace("}}", "").strip()
    if c in ("always()", "success()", "true"):
        return True
    m = re.fullmatch(r"github\.event_name\s*(==|!=)\s*'([a-z_]+)'", c)
    if m:
        return ("push" == m.group(2)) == (m.group(1) == "==")
    return None


def workflow_job_steps(workflow_text: str, job: str, skip: Mapping[str, str], sha: str) -> dict:
    """The job's runnable steps for a push/main run, the skipped ones (with reasons) and the
    problems that make the replay incomplete (which block the emergency path)."""
    import yaml
    doc = yaml.safe_load(workflow_text) or {}
    j = (doc.get("jobs") or {}).get(job)
    if not j:
        return {"steps": [], "skipped": [], "problems": [f"job_missing:{job}"], "env": {}}
    env_raw = {**(doc.get("env") or {}), **(j.get("env") or {})}
    env, problems = {}, []
    for k, v in env_raw.items():
        val, unknown = _subst(str(v), sha)
        if unknown:
            problems.append(f"env:{k}:unknown_expression:{','.join(unknown)}")
        env[str(k)] = val
    steps, skipped = [], []
    for s in j.get("steps") or []:
        name = str(s.get("name") or s.get("uses") or "unnamed")
        if s.get("uses"):
            skipped.append({"name": name, "reason": "uses: action (checkout/setup/upload), not repository code"})
            continue
        allow = _if_allows(s.get("if"))
        if allow is False:
            skipped.append({"name": name, "reason": f"if: {s.get('if')} is false for push/main"})
            continue
        if name in skip:
            skipped.append({"name": name, "reason": str(skip[name])})
            continue
        if allow is None:
            problems.append(f"step:{name}:unknown_if:{s.get('if')}")
            continue
        script, unknown = _subst(str(s.get("run") or ""), sha)
        senv = {}
        for k, v in (s.get("env") or {}).items():
            val, u2 = _subst(str(v), sha)
            unknown += u2
            senv[str(k)] = val
        if unknown:
            problems.append(f"step:{name}:unknown_expression:{','.join(unknown)}")
            continue
        steps.append({"name": name, "run": script, "env": senv,
                      "shell": str(s.get("shell") or "bash"), "working-directory": s.get("working-directory")})
    return {"steps": steps, "skipped": skipped, "problems": problems, "env": env}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _base(base: Optional[Path]) -> Path:
    return Path(base) if base is not None else Path(STATE_DIR)


def evidence_dir(sha: str, base: Optional[Path] = None) -> Path:
    return _base(base) / sha


def write_manifest(sha: str, tree: str, results: list[dict], *, base: Optional[Path] = None,
                   problems: list[str] = (), skipped: list[dict] = (), now: Optional[float] = None) -> Path:
    d = evidence_dir(sha, base)
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": SCHEMA, "kind": "local_evidence", "sha": sha, "tree": tree,
                "created_at": now if now is not None else time.time(),
                "results": results, "problems": list(problems), "skipped": list(skipped)}
    p = d / "manifest.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def verify_evidence(sha: str, tree: str, *, required_suites: Iterable[str], max_age_h: float,
                    base: Optional[Path] = None, now: Optional[float] = None) -> dict:
    """Evidence is valid only for this exact tree, complete, all-green, untampered and fresh."""
    now = time.time() if now is None else now
    p = evidence_dir(sha, base) / "manifest.json"
    errors: list[str] = []
    if not p.is_file():
        return {"ok": False, "errors": ["local_evidence_missing"], "manifest": str(p)}
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("sha") != sha:
        errors.append("evidence_sha_mismatch")
    if not tree or m.get("tree") != tree:
        errors.append("evidence_tree_mismatch")
    if m.get("problems"):
        errors.append("replay_incomplete:" + ";".join(m["problems"])[:300])
    age_h = (now - float(m.get("created_at") or 0)) / 3600.0
    if age_h > float(max_age_h):
        errors.append(f"evidence_stale:{age_h:.1f}h>{max_age_h}h")
    by_suite = {r.get("suite"): r for r in m.get("results") or []}
    for suite in required_suites:
        r = by_suite.get(suite)
        if r is None:
            errors.append("suite_missing:" + suite)
            continue
        if int(r.get("exit_code", 1)) != 0:
            errors.append("suite_failed:" + suite)
        log = Path(r.get("log") or "")
        if not log.is_file() or sha256_file(log) != r.get("log_sha256"):
            errors.append("log_tampered_or_missing:" + suite)
    return {"ok": not errors, "errors": errors, "manifest": str(p), "age_h": round(age_h, 2),
            "suites": sorted(by_suite)}


def required_suite_names(cfg: Mapping[str, Any]) -> list[str]:
    names = [f"workflow:{w['job']}" for w in cfg.get("workflow_jobs") or []]
    names += [str(s["name"]) for s in cfg.get("extra_suites") or []]
    return names


# ── 3. operator authority ────────────────────────────────────────────────────

def find_emergency_grant(grants: Iterable[Mapping[str, Any]], sha: str, incident_ids: Iterable[str], *,
                         tier: str = "release-emergency", now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    ids = [str(i) for i in incident_ids if i]
    refused = []
    for g in grants:
        if str(g.get("tier") or "") != tier:
            continue
        gid = str(g.get("grant_id") or g.get("id") or "")
        try:
            if float(g.get("expires") or g.get("expires_at") or 0) <= now:
                refused.append({"grant_id": gid, "why": "expired"})
                continue
        except (TypeError, ValueError):
            refused.append({"grant_id": gid, "why": "expiry_unreadable"})
            continue
        if int(g.get("uses") or 0) <= 0:
            refused.append({"grant_id": gid, "why": "no_uses_left"})
            continue
        text = str(g.get("reason") or g.get("for") or "").lower()
        names_sha = bool(sha) and sha[:9].lower() in text
        names_inc = any(i.lower() in text for i in ids)
        if names_sha and names_inc:
            return {"ok": True, "grant_id": gid, "refused": refused}
        refused.append({"grant_id": gid, "why": "grant must name the SHA and the incident id",
                        "names_sha": names_sha, "names_incident": names_inc})
    return {"ok": False, "grant_id": None, "refused": refused,
            "errors": [f"no {tier} grant names this SHA and incident"]}


# ── 4. commit rule ───────────────────────────────────────────────────────────

Runner = Callable[[list[str]], str]


def git_runner(repo: Path) -> Runner:
    import subprocess

    def run(args: list[str]) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=60, check=True).stdout.strip()
    return run


def tree_of(git: Runner, sha: str) -> str:
    return git(["rev-parse", f"{sha}^{{tree}}"])


def sha_rule(git: Runner, sha: str, main_ref: str = "origin/main") -> dict:
    """ON_MAIN, or PENDING_RECONCILIATION when every non-merge commit it adds is already on GitHub."""
    import subprocess
    tree = tree_of(git, sha)
    try:
        git(["merge-base", "--is-ancestor", sha, main_ref])
        return {"ok": True, "label": "ON_MAIN", "tree": tree, "local_merges": []}
    except subprocess.CalledProcessError:
        pass
    errors = []
    try:
        git(["merge-base", "--is-ancestor", main_ref, sha])
    except subprocess.CalledProcessError:
        errors.append(f"{main_ref}_not_ancestor_of_candidate")
    added = [c for c in git(["rev-list", f"{main_ref}..{sha}"]).split() if c]
    merges = [c for c in git(["rev-list", "--merges", f"{main_ref}..{sha}"]).split() if c]
    unpushed = []
    for c in added:
        if c in merges:
            continue
        if not git(["branch", "-r", "--contains", c]).strip():
            unpushed.append(c)
    if unpushed:
        errors.append("commits_not_on_github:" + ",".join(x[:9] for x in unpushed[:10]))
    return {"ok": not errors, "label": PENDING, "tree": tree, "local_merges": merges,
            "added_commits": len(added), "errors": errors}


# ── decision ─────────────────────────────────────────────────────────────────

def decide(*, sha: str, outage: Mapping[str, Any], evidence: Mapping[str, Any], grant: Mapping[str, Any],
           commit: Mapping[str, Any]) -> dict:
    errors = []
    for part, res in (("outage", outage), ("evidence", evidence), ("grant", grant), ("commit", commit)):
        if not res.get("ok"):
            errors += [f"{part}:{e}" for e in (res.get("errors") or ["refused"])]
    return {"schema": SCHEMA, "allowed": not errors, "sha": sha, "label": commit.get("label"),
            "tree": commit.get("tree"), "incident_ids": [i.get("id") for i in outage.get("incidents") or []],
            "grant_id": grant.get("grant_id"), "errors": errors,
            "outage": outage, "evidence": {k: evidence.get(k) for k in ("manifest", "age_h", "suites", "errors")},
            "commit": commit}


# ── ledger ───────────────────────────────────────────────────────────────────

def ledger_path(base: Optional[Path] = None) -> Path:
    return _base(base) / LEDGER_NAME


def append_ledger(record: Mapping[str, Any], base: Optional[Path] = None) -> dict:
    p = ledger_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": SCHEMA, "ts": time.time(), **record}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return row


def load_ledger(base: Optional[Path] = None) -> list[dict]:
    p = ledger_path(base)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def open_emergencies(rows: list[dict]) -> list[dict]:
    """Latest state per emergency release that has not reconciled (or been rolled back)."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("event") in ("EMERGENCY_PROMOTED", "RECONCILE_CHECK", RECONCILED, RECONCILE_FAILED, OVERDUE,
                              "ROLLED_BACK", "ROLLBACK_DRY_RUN"):
            latest[r["sha"]] = r
    return [r for r in latest.values() if r.get("state") not in (RECONCILED, "ROLLED_BACK")]


# ── 5. reconciliation ────────────────────────────────────────────────────────

def reconcile_record(rec: Mapping[str, Any], *, main_commits: list[tuple[str, str]],
                     checks_for: Callable[[str], Mapping[str, Any]], jobs_ran_and_failed: Callable[[str], bool],
                     now: float, within_h: float, content_merged: Optional[bool] = None) -> dict:
    """One pass for one emergency release. main_commits: [(sha, tree)] newest first.
    content_merged: True when every commit the release added is now on main (its PRs merged) —
    if main then carries no commit with the deployed tree, the live content diverged from main."""
    sha, tree = rec["sha"], rec.get("tree")
    target = sha if any(s == sha for s, _ in main_commits) else next((s for s, t in main_commits if t == tree), None)
    promoted_at = float(rec.get("promoted_at") or rec.get("ts") or now)
    overdue = (now - promoted_at) / 3600.0 > float(within_h)
    out = {"sha": sha, "tree": tree, "main_sha": target, "promoted_at": promoted_at}
    if target is None:
        diverged = bool(content_merged) and rec.get("label") == PENDING
        state = RECONCILE_FAILED if diverged else (OVERDUE if overdue else PENDING)
        return {**out, "state": state,
                "why": "main moved on without this tree (content diverged)" if diverged
                else "no main commit with this tree yet"}
    ev = checks_for(target)
    if ev.get("ok"):
        return {**out, "state": RECONCILED, "why": "exact-SHA push/main CI green", "checks": ev.get("checks")}
    if jobs_ran_and_failed(target):
        return {**out, "state": RECONCILE_FAILED, "why": "required CI ran and failed on the deployed content",
                "errors": ev.get("errors")}
    return {**out, "state": OVERDUE if overdue else PENDING, "why": "CI not complete yet", "errors": ev.get("errors")}


def page_text(state: str, rec: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    return (f"🚨 EMERGENCY RELEASE {state} · {str(rec.get('sha'))[:9]}\n"
            f"{result.get('why')}\n"
            f"promoted {time.strftime('%Y-%m-%d %H:%M', time.localtime(float(rec.get('promoted_at') or rec.get('ts') or 0)))} "
            f"under incident {', '.join(str(i) for i in rec.get('incident_ids') or [])}\n"
            f"previous release: {rec.get('prev_release')}\n"
            "Runbook: docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md § CI provider outage — emergency release")


__all__ = [
    "SCHEMA", "PENDING", "RECONCILED", "RECONCILE_FAILED", "OVERDUE", "load_config", "actions_incidents",
    "job_never_started", "evaluate_outage", "workflow_job_steps", "write_manifest", "verify_evidence",
    "required_suite_names", "find_emergency_grant", "sha_rule", "tree_of", "git_runner", "decide",
    "append_ledger", "load_ledger", "open_emergencies", "reconcile_record", "page_text", "sha256_file",
]

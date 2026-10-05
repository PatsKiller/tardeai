#!/usr/bin/env python3
"""CI-provider outage — governed emergency release (operator 2026-10-05).

  evidence      --sha SHA            replay the required workflows + extra suites locally on SHA's tree
  check         --sha SHA [--record --prev DIR --release DIR]
                                     outage proof + evidence + release-emergency grant + commit rule
  request-grant --sha SHA            ask the operator (Telegram) for a release-emergency grant naming
                                     the SHA and the live incident id
  reconcile     [--apply]            after GitHub recovers: RECONCILED / page / (configured) rollback
  status                             the emergency ledger, open releases first

`check` exits 0 only when every condition holds; the deploy script calls it when the exact-SHA
gate fails AND TRADEAI_EMERGENCY_RELEASE_SHA names this SHA. The environment variable alone grants
nothing. No credential is read or printed; gh stderr is never copied into records.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import ci_outage_emergency as em  # noqa: E402
from scripts.lib.release_grant_binding import load_grants  # noqa: E402
from scripts.release_grant_preflight import REQUIRED_PUSH_WORKFLOWS, collect_push_checks  # noqa: E402

VENV_BIN = Path(os.environ.get("TRADEAI_VENV_BIN", str(ROOT / ".venv" / "bin")))


def _repository() -> str:
    remote = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True,
                            text=True, timeout=20, check=True).stdout.strip()
    m = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", remote)
    if not m:
        raise ValueError("unsupported_repository")
    return m.group(1)


def _gh_json(endpoint: str) -> dict:
    out = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def fetch_runs_and_jobs(sha: str) -> tuple[list[dict], dict[int, list[dict]]]:
    repo = _repository()
    runs = _gh_json(f"repos/{repo}/actions/runs?head_sha={sha}&event=push&branch=main&per_page=100").get("workflow_runs") or []
    jobs = {}
    for r in runs:
        rid = int(r.get("id") or 0)
        if rid:
            jobs[rid] = _gh_json(f"repos/{repo}/actions/runs/{rid}/jobs?per_page=100").get("jobs") or []
    return runs, jobs


def fetch_incidents(cfg: dict) -> list[dict]:
    with urllib.request.urlopen(cfg["status_url"], timeout=20) as r:  # public status page, no credential
        payload = json.loads(r.read().decode())
    return em.actions_incidents(payload, cfg.get("incident_match") or ["actions"])


# ── evidence ─────────────────────────────────────────────────────────────────

def _clone_at(sha: str) -> Path:
    """A throwaway local clone (own .git/config, so steps that set core.hooksPath touch nothing
    shared) at SHA, with refs/remotes/origin/main copied from the dev repo (no network)."""
    tmp = Path(tempfile.mkdtemp(prefix=f"emergency-{sha[:9]}-"))
    subprocess.run(["git", "clone", "--quiet", "--no-checkout", str(ROOT), str(tmp)], check=True, timeout=600)
    subprocess.run(["git", "-C", str(tmp), "fetch", "--quiet", str(ROOT),
                    "+refs/remotes/origin/main:refs/remotes/origin/main"], check=True, timeout=600)
    subprocess.run(["git", "-C", str(tmp), "checkout", "--quiet", "--detach", sha], check=True, timeout=600)
    subprocess.run(["git", "-C", str(tmp), "config", "--unset-all", "core.hooksPath"], check=False)
    return tmp


def _run_logged(cmd, *, cwd: Path, env: dict, log: Path, timeout: int, shell: bool = False) -> int:
    with log.open("w", encoding="utf-8") as fh:
        fh.write(f"$ {cmd if shell else ' '.join(cmd)}\n")
        fh.flush()
        try:
            p = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout, shell=shell, executable="/bin/bash" if shell else None)
            return p.returncode
        except subprocess.TimeoutExpired:
            fh.write("\nTIMEOUT\n")
            return 124


def cmd_evidence(sha: str, cfg: dict) -> int:
    git = em.git_runner(ROOT)
    tree = em.tree_of(git, sha)
    out_dir = em.evidence_dir(sha)
    out_dir.mkdir(parents=True, exist_ok=True)
    clone = _clone_at(sha)
    base_env = {**os.environ, "PATH": f"{VENV_BIN}:{os.environ.get('PATH', '')}", "CI": "true",
                "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": sha,
                "TRADEAI_REMOTE_PUSH_AUTHORIZED": "0"}
    results, problems, skipped = [], [], []
    try:
        for wj in cfg.get("workflow_jobs") or []:
            suite = f"workflow:{wj['job']}"
            text = (clone / wj["workflow"]).read_text(encoding="utf-8")
            plan = em.workflow_job_steps(text, wj["job"], wj.get("skip") or {}, sha)
            problems += [f"{suite}:{p}" for p in plan["problems"]]
            skipped += [{"suite": suite, **s} for s in plan["skipped"]]
            log = out_dir / f"{suite.replace(':', '_')}.log"
            rc = 0
            with log.open("w", encoding="utf-8") as fh:
                fh.write(f"# {wj['workflow']} job {wj['job']} at {sha} (replayed locally)\n")
            for step in plan["steps"]:
                env = {**base_env, **plan["env"], **step["env"]}
                cwd = clone / (step.get("working-directory") or ".")
                step_log = out_dir / f"{suite.replace(':', '_')}__{re.sub(r'[^A-Za-z0-9]+', '_', step['name'])[:60]}.log"
                rc_step = _run_logged(step["run"], cwd=cwd, env=env, log=step_log, timeout=3600, shell=True)
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(f"step {step['name']!r}: exit {rc_step}  log={step_log.name} sha256={em.sha256_file(step_log)}\n")
                if rc_step != 0 and rc == 0:
                    rc = rc_step
            results.append({"suite": suite, "exit_code": rc, "log": str(log), "log_sha256": em.sha256_file(log),
                            "steps": len(plan["steps"])})
        for s in cfg.get("extra_suites") or []:
            cwd = clone / (s.get("cwd") or ".")
            if s.get("needs_node_modules"):
                src_nm = ROOT / (s.get("cwd") or ".") / "node_modules"
                if src_nm.is_dir() and not (cwd / "node_modules").exists():
                    (cwd / "node_modules").symlink_to(src_nm)
            env = dict(base_env)
            preview = None
            if s.get("preview_port"):
                subprocess.run(["npm", "run", "build"], cwd=str(cwd), env=env, capture_output=True, timeout=900)
                preview = subprocess.Popen(["npx", "vite", "preview", "--port", str(s["preview_port"]), "--strictPort"],
                                           cwd=str(cwd), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                env["PLAYWRIGHT_BASE_URL"] = f"http://127.0.0.1:{s['preview_port']}"
                time.sleep(4)
            log = out_dir / f"{s['name']}.log"
            try:
                rc = _run_logged(list(s["cmd"]), cwd=cwd, env=env, log=log, timeout=int(s.get("timeout_s") or 1800))
            finally:
                if preview:
                    preview.terminate()
            results.append({"suite": s["name"], "exit_code": rc, "log": str(log), "log_sha256": em.sha256_file(log)})
    finally:
        shutil.rmtree(clone, ignore_errors=True)
    path = em.write_manifest(sha, tree, results, problems=problems, skipped=skipped)
    ok = not problems and all(r["exit_code"] == 0 for r in results)
    print(json.dumps({"ok": ok, "manifest": str(path), "tree": tree, "problems": problems,
                      "results": [{k: r[k] for k in ("suite", "exit_code")} for r in results]}, indent=2))
    return 0 if ok else 2


# ── check ────────────────────────────────────────────────────────────────────

def build_decision(sha: str, cfg: dict) -> dict:
    try:
        incidents = fetch_incidents(cfg)
    except Exception as exc:  # noqa: BLE001 — unreadable status page is not an outage proof
        incidents = []
        status_err = f"status_unavailable:{type(exc).__name__}"
    else:
        status_err = None
    try:
        runs, jobs = fetch_runs_and_jobs(sha)
    except Exception as exc:  # noqa: BLE001
        runs, jobs = [], {}
        status_err = (status_err or "") + f" runs_unavailable:{type(exc).__name__}"
    outage = em.evaluate_outage(sha, runs, jobs, incidents, REQUIRED_PUSH_WORKFLOWS)
    if status_err:
        outage["errors"].append(status_err.strip())
        outage["ok"] = False
    git = em.git_runner(ROOT)
    commit = em.sha_rule(git, sha)
    evidence = em.verify_evidence(sha, commit.get("tree") or "", required_suites=em.required_suite_names(cfg),
                                  max_age_h=float(cfg.get("evidence_max_age_h") or 12))
    grant = em.find_emergency_grant(load_grants(), sha, [i.get("id") for i in incidents],
                                    tier=str(cfg.get("grant_tier") or "release-emergency"))
    return em.decide(sha=sha, outage=outage, evidence=evidence, grant=grant, commit=commit)


def cmd_check(args, cfg: dict) -> int:
    d = build_decision(args.sha, cfg)
    if args.record:
        em.append_ledger({"event": "EMERGENCY_CHECK", "state": "ALLOWED" if d["allowed"] else "REFUSED", **d})
        if d["allowed"]:
            em.append_ledger({"event": "EMERGENCY_PROMOTED", "state": em.PENDING, "sha": args.sha, "tree": d["tree"],
                              "label": d["label"], "incident_ids": d["incident_ids"], "grant_id": d["grant_id"],
                              "prev_release": args.prev, "release": args.release, "promoted_at": time.time(),
                              "added_commits": (d.get("commit") or {}).get("added_commits")})
    print(json.dumps(d, sort_keys=True, default=str))
    return 0 if d["allowed"] else 2


def cmd_request_grant(args, cfg: dict) -> int:
    incidents = fetch_incidents(cfg)
    if not incidents:
        print(json.dumps({"ok": False, "error": "no unresolved Actions incident — use the normal gate"}))
        return 2
    inc = incidents[0]
    reason = (f"EMERGENCY release {args.sha} during GitHub incident {inc['id']} ({inc['name']}): required CI "
              f"never started; local replay evidence bound to tree; reconcile when GitHub recovers")
    py = VENV_BIN / "python"
    return subprocess.run([str(py if py.exists() else sys.executable), str(ROOT / "scripts" / "guard_request_approval.py"),
                           str(cfg.get("grant_tier") or "release-emergency"), "--for", "2h", "--uses", "2",
                           "--reason", reason]).returncode


# ── reconcile ────────────────────────────────────────────────────────────────

def _main_commits(n: int = 300) -> list[tuple[str, str]]:
    subprocess.run(["git", "-C", str(ROOT), "fetch", "--quiet", "origin", "main"], check=False, timeout=120)
    out = subprocess.run(["git", "-C", str(ROOT), "log", "origin/main", f"-n{n}", "--format=%H %T"],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return [tuple(line.split()) for line in out.splitlines() if line.strip()]


def _content_merged(sha: str) -> bool:
    """Every non-merge commit the emergency release added is now reachable from origin/main."""
    added = subprocess.run(["git", "-C", str(ROOT), "rev-list", "--no-merges", f"origin/main..{sha}"],
                           capture_output=True, text=True, timeout=60).stdout.split()
    return not added


def _ran_and_failed(sha: str) -> bool:
    runs, jobs = fetch_runs_and_jobs(sha)
    for r in runs:
        path = str(r.get("path") or "").split("@", 1)[0]
        if path not in REQUIRED_PUSH_WORKFLOWS or r.get("status") != "completed" or r.get("conclusion") == "success":
            continue
        if any(not em.job_never_started(j) and str(j.get("conclusion") or "") == "failure" for j in jobs.get(int(r["id"])) or []):
            return True
    return False


def _page(text: str) -> bool:
    """Deploy-safety page: an unreconciled emergency release must reach the operator, so it
    bypasses the noise router like the other urgent ops pages (stop-manager host lock, defense)."""
    from telegram_alert import send_telegram
    return bool(send_telegram(text, bypass_router=True, message_class="operator_alert"))


def cmd_reconcile(args, cfg: dict) -> int:
    rows = em.load_ledger()
    opened = em.open_emergencies(rows)
    if not opened:
        print(json.dumps({"open": 0}))
        return 0
    mains = _main_commits()
    out = []
    for rec in opened:
        res = em.reconcile_record(rec, main_commits=mains, checks_for=collect_push_checks,
                                  jobs_ran_and_failed=_ran_and_failed, now=time.time(),
                                  within_h=float(cfg.get("reconcile_within_h") or 24),
                                  content_merged=_content_merged(rec["sha"]))
        action = None
        if res["state"] in (em.RECONCILE_FAILED, em.OVERDUE):
            last_page = max((float(r.get("ts") or 0) for r in rows if r.get("sha") == rec["sha"] and r.get("paged")), default=0)
            if time.time() - last_page >= float(cfg.get("page_cooldown_min") or 120) * 60:
                action = "page"
            if res["state"] == em.RECONCILE_FAILED:
                action = (action or "") + ("+rollback" if cfg.get("auto_rollback") else "+rollback_dry_run")
        out.append({**res, "action": action})
        if not args.apply:
            continue
        paged = False
        if action and action.startswith("page"):
            paged = _page(em.page_text(res["state"], rec, res))
        em.append_ledger({"event": "RECONCILE_CHECK" if res["state"] not in (em.RECONCILED, em.RECONCILE_FAILED, em.OVERDUE)
                          else res["state"], **{k: rec.get(k) for k in ("label", "incident_ids", "prev_release", "release",
                                                                        "promoted_at", "grant_id")},
                          **res, "paged": paged})
        if res["state"] == em.RECONCILE_FAILED and rec.get("prev_release"):
            if cfg.get("auto_rollback"):
                rc = subprocess.run(["bash", str(ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"), "rollback",
                                     str(rec["prev_release"])]).returncode
                em.append_ledger({"event": "ROLLED_BACK" if rc == 0 else "ROLLBACK_FAILED", "sha": rec["sha"],
                                  "state": "ROLLED_BACK" if rc == 0 else em.RECONCILE_FAILED, "rc": rc,
                                  "prev_release": rec["prev_release"]})
            else:
                em.append_ledger({"event": "ROLLBACK_DRY_RUN", "sha": rec["sha"], "state": em.RECONCILE_FAILED,
                                  "would_run": f"scripts/cio_phase2_exact_main_deploy.sh rollback {rec['prev_release']}"})
    print(json.dumps({"open": len(opened), "apply": bool(args.apply), "results": out}, indent=2, default=str))
    return 0


def cmd_status() -> int:
    rows = em.load_ledger()
    print(json.dumps({"open": em.open_emergencies(rows), "events": len(rows),
                      "ledger": str(em.ledger_path())}, indent=2, default=str))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evidence"); e.add_argument("--sha", required=True)
    c = sub.add_parser("check"); c.add_argument("--sha", required=True); c.add_argument("--record", action="store_true")
    c.add_argument("--prev"); c.add_argument("--release")
    g = sub.add_parser("request-grant"); g.add_argument("--sha", required=True)
    r = sub.add_parser("reconcile"); r.add_argument("--apply", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    cfg = em.load_config()
    if getattr(a, "sha", None) and not re.fullmatch(r"[0-9a-f]{40}", a.sha):
        print(json.dumps({"ok": False, "error": "--sha must be the full 40-hex commit"}))
        return 2
    if a.cmd == "evidence":
        return cmd_evidence(a.sha, cfg)
    if a.cmd == "check":
        return cmd_check(a, cfg)
    if a.cmd == "request-grant":
        return cmd_request_grant(a, cfg)
    if a.cmd == "reconcile":
        return cmd_reconcile(a, cfg)
    return cmd_status()


if __name__ == "__main__":
    sys.exit(main())

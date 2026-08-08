#!/usr/bin/env python3
"""coder_dispatch.py — multi-coder auto-fix dispatcher for the Health Agent.

Takes a code-level problem (from the Health Agent / escalation queue) and routes it to ONE available
AI coder backend (Claude Code, Cursor, Grok, ChatGPT/Codex proxy, Codex CLI, Aider, …) to produce a
fix. The fix is made in an ISOLATED git worktree, verified (compile/tests), and then — depending on
mode — either saved as a review diff (advisory, default) or pushed to a branch + opened as a PR.

Design (locked with operator 2026-06-22):
  • Apply model      : worktree → verify → PR     (never edits the working tree or main directly)
  • Dispatch strategy: router picks ONE backend per problem (by kind + availability + priority)
  • Registry         : config/coder_backends.json — EVERY backend is wired even if not installed;
                       availability is detected at runtime, dormant backends are skipped.
  • Safety           : advisory by default (diff artifact, no push); CODER_DISPATCH_MODE=pr opens PRs.
                       Bounded (per-run + daily caps). Fully audited (DB + JSONL). Never raises.

Usage:
    .venv/bin/python scripts/coder_dispatch.py --list-backends
    .venv/bin/python scripts/coder_dispatch.py --problem "Fix X in scripts/y.py" --kind single_file
    .venv/bin/python scripts/coder_dispatch.py --problem "..." --apply          # run coder, verify, advisory diff
    CODER_DISPATCH_MODE=pr .venv/bin/python scripts/coder_dispatch.py --problem "..." --apply   # + open PR
    .venv/bin/python scripts/coder_dispatch.py --from-queue --apply             # drain escalation code-fix items
"""
from __future__ import annotations

import re
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# DEV_ROOT always points to the git-enabled dev directory for coder worktree operations
DEV_ROOT = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
sys.path.insert(0, str(DEV_ROOT / "scripts"))

try:
    from lib.live_project_root import get_live_project_root
    LIVE_ROOT = get_live_project_root()
except Exception:
    LIVE_ROOT = PROJECT_ROOT

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

REGISTRY_FILE = PROJECT_ROOT / "config" / "coder_backends.json"
LOG_DIR = PROJECT_ROOT / "logs"
ARTIFACT_DIR = PROJECT_ROOT / "logs" / "coder_dispatch_diffs"
AUDIT_JSONL = LOG_DIR / "coder_dispatch.jsonl"
QUEUE_FILE = LOG_DIR / "claude_escalation_queue.json"
WORKTREE_ROOT = Path("/tmp/tradeai_coder_worktrees")

# Bounds (overridable via env). A runaway-loop backstop, not a target.
MAX_PER_RUN = int(os.getenv("CODER_DISPATCH_MAX_PER_RUN", "2"))
DAILY_CAP = int(os.getenv("CODER_DISPATCH_DAILY_CAP", "6"))
MODE = os.getenv("CODER_DISPATCH_MODE", "advisory").lower()   # advisory | pr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [coder-dispatch] %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(LOG_DIR / "coder_dispatch.log")])
log = logging.getLogger("coder_dispatch")


# ── Registry ──────────────────────────────────────────────────────────────────────────────────────

def load_registry() -> dict:
    """DB-first (config_documents key 'coder_backends'), fallback to the JSON file. Never raises."""
    try:
        from config_db_loader import get_config
        cfg = get_config("coder_backends", fallback_path="config/coder_backends.json")
        if cfg:
            return cfg
    except Exception:
        pass
    try:
        return json.loads(REGISTRY_FILE.read_text())
    except Exception as e:
        log.error(f"registry load failed: {e}")
        return {"backends": [], "routing": {}, "defaults": {}}


def is_available(b: dict) -> bool:
    """Detect whether a backend can run right now. CLI agents → executable exists; http_diff → port answers."""
    if not b.get("enabled", True):
        return False
    kind = b.get("kind")
    if kind == "cli_agent":
        binp = b.get("bin", "")
        return bool(binp) and os.path.isfile(binp) and os.access(binp, os.X_OK)
    if kind == "http_diff":
        import urllib.request
        try:
            url = b.get("base_url", "").rstrip("/") + "/models"
            with urllib.request.urlopen(url, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False
    return False


def select_backend(reg: dict, kind: str) -> dict | None:
    """Router: walk the routing preference for this problem-kind and return the first available backend."""
    backends = {b["name"]: b for b in reg.get("backends", [])}
    routing = reg.get("routing", {})
    order = routing.get(kind) or routing.get("_default") or [
        b["name"] for b in sorted(reg.get("backends", []), key=lambda x: x.get("priority", 999))
    ]
    for name in order:
        b = backends.get(name)
        if b and is_available(b):
            return b
    return None


# ── git / worktree helpers ──────────────────────────────────────────────────────────────────────────

def _git(*args, cwd=None, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd or DEV_ROOT),
                          capture_output=True, text=True, timeout=timeout)


def _in_git_repo() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


def make_worktree(branch: str, base: str) -> Path | None:
    """Create an isolated worktree off `base` on a new `branch`. Returns the path or None."""
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    wt = WORKTREE_ROOT / branch.replace("/", "_")
    # base may not exist (fresh repo / no main) — fall back to HEAD.
    base_ref = base if _git("rev-parse", "--verify", base).returncode == 0 else "HEAD"
    r = _git("worktree", "add", "-b", branch, str(wt), base_ref)
    if r.returncode != 0:
        log.error(f"worktree add failed: {r.stderr.strip()}")
        return None
    return wt


def remove_worktree(wt: Path, branch: str, keep_branch: bool):
    try:
        _git("worktree", "remove", "--force", str(wt))
    except Exception:
        pass
    if not keep_branch:
        try:
            _git("branch", "-D", branch)
        except Exception:
            pass


def changed_files(wt: Path) -> list[str]:
    r = _git("status", "--porcelain", cwd=wt)
    return [ln[3:].strip() for ln in r.stdout.splitlines() if ln.strip()]


# ── Backend invocation ────────────────────────────────────────────────────────────────────────────

def _build_prompt(problem: dict) -> str:
    detail = problem.get("detail") or problem.get("problem") or problem.get("description") or ""
    comp = problem.get("component", "")
    files = problem.get("files") or problem.get("files_hint") or []
    diag = problem.get("llm_diagnosis", "")
    lines = [
        "You are fixing a defect in the Trade AI v12 codebase. Make the SMALLEST correct change.",
        "Only edit files needed to fix the described problem. Do not reformat unrelated code.",
        "Match surrounding code style. Do not add dependencies. Do not touch trading/broker order paths.",
        "",
        f"Component: {comp}" if comp else "",
        f"Problem: {detail}",
    ]
    if diag:
        lines.append(f"Prior diagnosis: {diag}")
    if files:
        lines.append("Likely files: " + ", ".join(files))
    return "\n".join(x for x in lines if x)


def run_cli_agent(b: dict, prompt: str, wt: Path) -> tuple[bool, str]:
    """Invoke a CLI coder agent inside the worktree. Returns (ran, output)."""
    args = []
    for a in b.get("args_template", []):
        args.append(a.replace("{prompt}", prompt) if "{prompt}" in a else a)
    cmd = [b["bin"], *args]
    cwd = wt if b.get("cwd_is_worktree", True) else PROJECT_ROOT
    timeout = b.get("timeout_sec", 900)
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(cwd), start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
                    proc.communicate(timeout=5)
            except Exception:
                pass
            log.warning(f"  ⏱️ coder backend {b.get('name')} timeout ({timeout}s) — process group killed")
            return True, f"timeout after {timeout}s"
        out = (stdout or "")[-2000:] + (
            ("\n[stderr] " + (stderr or "")[-500:])
            if proc.returncode != 0 and stderr else ""
        )
        return True, out
    except Exception as e:
        return False, f"invoke error: {e}"


def run_http_diff(b: dict, prompt: str, wt: Path) -> tuple[bool, str]:
    """Ask an OpenAI-compatible proxy for a unified diff, then git-apply it in the worktree."""
    import urllib.request
    body = json.dumps({
        "model": b.get("model", "gpt-4"),
        "messages": [
            {"role": "system", "content": "You are a code-fixing assistant. Reply with ONLY a unified "
             "git diff (diff --git format, relative paths) that applies cleanly with `git apply`. No prose."},
            {"role": "user", "content": prompt + "\n\nReturn only the unified diff."},
        ],
        "temperature": 0.1,
    }).encode()
    try:
        req = urllib.request.Request(b["base_url"].rstrip("/") + "/chat/completions",
                                     data=body, headers={"Content-Type": "application/json",
                                                         "Authorization": "Bearer local-proxy"})
        with urllib.request.urlopen(req, timeout=b.get("timeout_sec", 300)) as r:
            data = json.loads(r.read().decode())
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        return False, f"proxy error: {e}"
    # Extract the diff (strip ``` fences if present)
    diff = content
    if "```" in content:
        parts = content.split("```")
        for p in parts:
            p = p.lstrip()
            if p.startswith("diff") or p.startswith("--- ") or "diff --git" in p:
                diff = p[4:] if p.startswith("diff") else p
                break
    patch = wt / ".coder_dispatch.patch"
    patch.write_text(diff)
    ap = _git("apply", "--whitespace=nowarn", str(patch), cwd=wt)
    try:
        patch.unlink()
    except Exception:
        pass
    if ap.returncode != 0:
        return True, f"diff did not apply: {ap.stderr.strip()[:300]}"
    return True, "diff applied"


def verify(reg: dict, wt: Path, files: list[str]) -> tuple[bool, str]:
    """Verification gate before PR. Configurable test_cmd; always py_compile changed Python files."""
    # 1) syntax-compile every changed .py — a real 'does it parse' gate, zero project assumptions.
    pyf = [f for f in files if f.endswith(".py")]
    if pyf:
        r = subprocess.run([sys.executable, "-m", "py_compile", *pyf], cwd=str(wt),
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, f"py_compile failed: {r.stderr.strip()[:400]}"
    # 2) optional project test command from registry
    tc = (reg.get("defaults") or {}).get("test_cmd") or os.getenv("CODER_DISPATCH_TEST_CMD", "")
    if tc:
        r = subprocess.run(tc, shell=True, cwd=str(wt), capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return False, f"test_cmd failed: {(r.stderr or r.stdout).strip()[-400:]}"
    return True, "verified" + (f" ({len(pyf)} py files compiled)" if pyf else "")


# ── Audit ───────────────────────────────────────────────────────────────────────────────────────────

def _db():
    try:
        from db_adapter import _execute, USE_DB
        return (_execute, USE_DB)
    except Exception:
        return (None, False)


def ensure_audit_table():
    ex, use = _db()
    if not use:
        return
    ex("""CREATE TABLE IF NOT EXISTS coder_dispatch_audit (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT now(),
            component TEXT, problem TEXT, kind TEXT,
            backend TEXT, mode TEXT, branch TEXT,
            outcome TEXT, files_changed JSONB, pr_url TEXT,
            reasoning TEXT, detail TEXT)""")
    ex("""CREATE INDEX IF NOT EXISTS idx_coder_dispatch_audit_created_at
          ON coder_dispatch_audit (created_at)""")


def dispatched_today() -> int:
    ex, use = _db()
    if not use:
        # JSONL fallback count
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return sum(1 for ln in AUDIT_JSONL.read_text().splitlines()
                       if today in ln and ('"outcome": "pr_opened"' in ln or '"outcome": "advisory_diff"' in ln))
        except Exception:
            return 0
    r = ex("SELECT COUNT(*) AS c FROM coder_dispatch_audit WHERE created_at >= now()::date "
           "AND outcome IN ('pr_opened','advisory_diff')", fetch="one")
    return (r or {}).get("c", 0) if r else 0


def audit(rec: dict):
    rec = {"created_at": datetime.now(timezone.utc).isoformat(), **rec}
    try:
        AUDIT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_JSONL, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass
    ex, use = _db()
    if use:
        try:
            ex("""INSERT INTO coder_dispatch_audit
                  (component,problem,kind,backend,mode,branch,outcome,files_changed,pr_url,reasoning,detail)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
               (rec.get("component"), rec.get("problem"), rec.get("kind"), rec.get("backend"),
                rec.get("mode"), rec.get("branch"), rec.get("outcome"),
                json.dumps(rec.get("files_changed") or []), rec.get("pr_url"),
                rec.get("reasoning"), rec.get("detail")))
        except Exception:
            pass


# ── Dispatch ──────────────────────────────────────────────────────────────────────────────────────

def dispatch_one(problem: dict, reg: dict, apply: bool) -> dict:
    """Route + (optionally) fix one problem. Returns a result dict. Never raises."""
    kind = problem.get("kind", "_default")
    comp = problem.get("component", "health")
    detail = (problem.get("detail") or problem.get("problem") or "")[:300]

    b = select_backend(reg, kind)
    if not b:
        res = {"component": comp, "kind": kind, "outcome": "no_backend_available",
               "reasoning": "no enabled+installed backend matched this kind", "problem": detail}
        audit(res); return res

    reasoning = f"router picked '{b['name']}' for kind='{kind}' (available)"
    if not apply:
        res = {"component": comp, "kind": kind, "backend": b["name"], "mode": "plan",
               "outcome": "planned", "reasoning": reasoning, "problem": detail,
               "prompt_preview": _build_prompt(problem)[:400]}
        log.info(f"PLAN: {comp} → {b['display']} ({MODE} mode would apply). Run with --apply to execute.")
        return res

    if not _in_git_repo():
        res = {"component": comp, "backend": b["name"], "outcome": "not_a_git_repo",
               "reasoning": "coder dispatch needs a git repo for worktree+PR", "problem": detail}
        audit(res); return res

    base = (reg.get("defaults") or {}).get("base_branch", "main")
    sid = f"{int(time.time())}"
    # Sanitize the component into a valid git branch ref — components are 'health:cat:type' and the
    # colons (plus any other invalid char) made EVERY autofix branch invalid → 'worktree_failed' on
    # every queue item (the 8/8 failures the health audit surfaced).
    _safe = re.sub(r"[^A-Za-z0-9._-]+", "-", comp).strip("-/.") or "fix"
    branch = f"autofix/{_safe}-{sid}"[:60]
    wt = make_worktree(branch, base)
    if not wt:
        res = {"component": comp, "backend": b["name"], "branch": branch,
               "outcome": "worktree_failed", "reasoning": reasoning, "problem": detail}
        audit(res); return res

    prompt = _build_prompt(problem)
    try:
        if b["kind"] == "cli_agent":
            ran, out = run_cli_agent(b, prompt, wt)
        else:
            ran, out = run_http_diff(b, prompt, wt)

        files = changed_files(wt)
        if not ran or not files:
            remove_worktree(wt, branch, keep_branch=False)
            res = {"component": comp, "backend": b["name"], "branch": branch,
                   "outcome": "no_changes", "reasoning": reasoning,
                   "detail": out[:400], "problem": detail, "files_changed": []}
            audit(res); return res

        ok, vmsg = verify(reg, wt, files)
        if not ok:
            # keep the diff as an artifact for review, then discard the branch
            _save_diff_artifact(wt, branch)
            remove_worktree(wt, branch, keep_branch=False)
            res = {"component": comp, "backend": b["name"], "branch": branch,
                   "outcome": "verify_failed", "reasoning": reasoning, "detail": vmsg,
                   "files_changed": files, "problem": detail}
            audit(res); return res

        # Verified. Commit inside the worktree.
        _git("add", "-A", cwd=wt)
        _git("commit", "-m", f"autofix({comp}): {detail[:60]}\n\nBackend: {b['display']}\n"
             f"Auto-generated by coder_dispatch. Review before merge.\n\n"
             f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>", cwd=wt)

        if MODE == "pr":
            push = _git("push", "-u", "origin", branch, cwd=wt, timeout=180)
            pr_url = ""
            if push.returncode == 0:
                pr = subprocess.run(
                    ["gh", "pr", "create", "--head", branch, "--base", base,
                     "--title", f"autofix({comp}): {detail[:60]}",
                     "--body", f"Automated fix by **{b['display']}** via coder_dispatch.\n\n"
                               f"Problem: {detail}\n\nVerification: {vmsg}\n\n"
                               f"⚠️ Review before merge.\n\n🤖 Generated with coder_dispatch"],
                    cwd=str(wt), capture_output=True, text=True, timeout=120)
                pr_url = pr.stdout.strip() if pr.returncode == 0 else f"(pr create failed: {pr.stderr.strip()[:160]})"
            else:
                pr_url = f"(push failed: {push.stderr.strip()[:160]})"
            remove_worktree(wt, branch, keep_branch=True)
            res = {"component": comp, "backend": b["name"], "branch": branch, "mode": "pr",
                   "outcome": "pr_opened", "reasoning": reasoning, "detail": vmsg,
                   "files_changed": files, "pr_url": pr_url, "problem": detail}
            audit(res)
            log.info(f"PR: {comp} fixed by {b['display']} → {pr_url}")
            return res
        else:
            # advisory: save diff artifact, discard branch (no push)
            art = _save_diff_artifact(wt, branch)
            remove_worktree(wt, branch, keep_branch=False)
            res = {"component": comp, "backend": b["name"], "branch": branch, "mode": "advisory",
                   "outcome": "advisory_diff", "reasoning": reasoning, "detail": vmsg,
                   "files_changed": files, "pr_url": str(art), "problem": detail}
            audit(res)
            log.info(f"ADVISORY: {comp} fix by {b['display']} saved → {art} (set CODER_DISPATCH_MODE=pr to auto-PR)")
            return res
    except Exception as e:
        remove_worktree(wt, branch, keep_branch=False)
        res = {"component": comp, "backend": b["name"], "branch": branch,
               "outcome": "error", "reasoning": reasoning, "detail": str(e)[:400], "problem": detail}
        audit(res); return res


def _save_diff_artifact(wt: Path, branch: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    art = ARTIFACT_DIR / f"{branch.replace('/', '_')}.diff"
    try:
        # uncommitted changes (verify_failed path, before commit)
        out = _git("diff", "HEAD", cwd=wt).stdout
        if not out.strip():
            # advisory-success path already committed the fix → diff the autofix commit vs its parent,
            # else the artifact is empty and the change is lost when the branch is removed.
            out = _git("diff", "HEAD~1", "HEAD", cwd=wt).stdout
        art.write_text(out)
    except Exception:
        pass
    return art


def code_fix_items_from_queue() -> list[dict]:
    """Pull code-fix-flagged items from the escalation queue (component-level problems the safe-retry
    + LLM tiers could not resolve, explicitly tagged needs_code_fix).

    Filters out already-dispatched items unless the dispatch is older than 24h (allows retry
    after a transient backend-unavailable or verify-failed outcome)."""
    try:
        from lib.queue_file import read_items
        items = read_items(QUEUE_FILE)
    except Exception:
        try:
            items = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
        except Exception:
            return []
    now_ts = time.time()
    result = []
    for i in items:
        if not (i.get("needs_code_fix") or i.get("kind") in
                ("code", "single_file", "multi_file", "schema")):
            continue
        # Skip already-dispatched items unless >24h old (retry window)
        ds = i.get("_dispatch_status")
        if ds == "dispatched":
            dispatched_at = i.get("_dispatched_at", 0)
            if now_ts - float(dispatched_at) < 86400:
                continue  # still within retry window
        result.append(i)
    return result


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────

def list_backends(reg: dict):
    print(f"Coder backends (mode={MODE}, max/run={MAX_PER_RUN}, daily_cap={DAILY_CAP}):\n")
    for b in sorted(reg.get("backends", []), key=lambda x: x.get("priority", 999)):
        avail = "✅ available" if is_available(b) else ("⏸ dormant (not installed)"
                if b.get("kind") == "cli_agent" else "⏸ offline")
        print(f"  [{b.get('priority'):>3}] {b['display']:<32} {b['kind']:<10} {avail}")
        print(f"        {b.get('bin') or b.get('base_url')}")
    print(f"\n  Today: {dispatched_today()}/{DAILY_CAP} dispatches used.")


def main():
    ap = argparse.ArgumentParser(description="Multi-coder auto-fix dispatcher")
    ap.add_argument("--problem", help="problem description to fix")
    ap.add_argument("--kind", default="_default", help="problem kind: code|single_file|multi_file|schema|ui")
    ap.add_argument("--component", default="manual", help="component label for audit")
    ap.add_argument("--from-queue", action="store_true", help="drain code-fix items from escalation queue")
    ap.add_argument("--apply", action="store_true", help="actually run the coder (default: plan only)")
    ap.add_argument("--list-backends", action="store_true")
    ap.add_argument("--limit", type=int, default=MAX_PER_RUN)
    ap.add_argument("--reset-dispatched", action="store_true",
                    help="clear _dispatch_status on all queue items (operator override)")
    args = ap.parse_args()

    reg = load_registry()
    ensure_audit_table()

    if args.list_backends:
        list_backends(reg); return

    # --reset-dispatched: clear dispatch status on all queue items (operator override)
    if args.reset_dispatched:
        try:
            from lib.queue_file import atomic_update
            def _reset(items):
                for i in items:
                    for k in ("_dispatch_status", "_dispatch_outcome", "_dispatched_at"):
                        i.pop(k, None)
                return items
            atomic_update(QUEUE_FILE, _reset)
            print(json.dumps({"ok": True, "reset_dispatched": True}))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}))
        return

    problems = []
    if args.problem:
        problems.append({"component": args.component, "kind": args.kind, "detail": args.problem})
    if args.from_queue:
        problems.extend(code_fix_items_from_queue())

    if not problems:
        print("Nothing to do. Use --problem '…' or --from-queue, or --list-backends."); return

    if args.apply:
        used = dispatched_today()
        if used >= DAILY_CAP:
            log.warning(f"daily cap reached ({used}/{DAILY_CAP}) — refusing to dispatch. (raise CODER_DISPATCH_DAILY_CAP)")
            return
        problems = problems[: min(args.limit, DAILY_CAP - used)]

    results = [dispatch_one(p, reg, apply=args.apply) for p in problems[: args.limit]]

    # Mark dispatched items in the queue so they aren't re-dispatched every cron run.
    # In advisory mode the finding can never clear (diff is never merged), but at least
    # the dispatch loop stops after one attempt.  Re-eligible after 24h for retry.
    if args.apply and args.from_queue:
        try:
            from lib.queue_file import atomic_update
            dispatched_comps = {p.get("component") for p in problems[: args.limit]}
            now_ts = time.time()
            def _mark(items):
                for i in items:
                    if i.get("component") in dispatched_comps:
                        i["_dispatch_status"] = "dispatched"
                        i["_dispatch_outcome"] = "attempted"  # detailed outcome in audit table
                        i["_dispatched_at"] = now_ts
                return items
            atomic_update(QUEUE_FILE, _mark)
        except Exception as e:
            log.warning(f"Failed to mark dispatched items in queue: {e}")

    print(json.dumps({"ok": True, "mode": MODE, "applied": args.apply,
                      "count": len(results), "results": results}, indent=2, default=str))


if __name__ == "__main__":
    main()

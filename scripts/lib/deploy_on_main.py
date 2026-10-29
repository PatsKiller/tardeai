"""Deploy-on-main poller core (AGENTS.md §25.10 / 24.0.0).

Promote-only: if origin/main tip ≠ CURRENT pin, STOP is absent, GlobalReleaseLock is free,
and the standing deploy delegation is armed, run cio_phase2_exact_main_deploy.sh prepare+promote
for that SHA, then post_release_tester, and write DeployOnMainReceipt@v1 (path=poller).

Never merges PRs or pushes remotes; local source advances only by exact-main fast-forward. This is the
live promote path; the release train it replaced was retired 2026-10-27 (operator directive). From
scripts/lib/release_control.py it uses only the STOP latch reader and GlobalReleaseLock.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "DeployOnMainReceipt@v1"
PATH_POLLER = "poller"
PATH_MANUAL_EMERGENCY = "manual_emergency"

DEFAULT_RELEASES = Path.home() / "trade-ai-releases" / "portfolio-server"
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
RECEIPTS_REL = Path("data") / "runtime" / "deploy_on_main"


@dataclass(frozen=True)
class PollDecision:
    action: str  # noop | promote | refuse
    reason: str
    main_sha: str = ""
    current_sha: str = ""
    detail: dict[str, Any] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_dir() -> Path:
    env = os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR")
    if env:
        return Path(env)
    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    return root / "data" / "runtime" / "release_window"


def receipts_dir() -> Path:
    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    return root / RECEIPTS_REL


def releases_root() -> Path:
    return Path(os.environ.get("TRADEAI_PORTFOLIO_SERVER_ROOT") or DEFAULT_RELEASES)


def current_pin_sha(releases: Path | None = None) -> str:
    """SHA served by CURRENT (directory name prefix or BUILD_SHA / SOURCE_COMMIT)."""
    root = releases or releases_root()
    current = root / "CURRENT"
    try:
        resolved = current.resolve(strict=True)
    except OSError:
        return ""
    name = resolved.name
    # release dirs: <sha>-main-exact-phase2-<ts>
    if "-" in name:
        cand = name.split("-", 1)[0]
        if len(cand) >= 9 and all(c in "0123456789abcdef" for c in cand.lower()):
            return cand.lower()
    for rel in ("BUILD_SHA", "SOURCE_COMMIT", "expected_release_pin.txt"):
        p = resolved / rel
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8").strip().split()[0]
            except OSError:
                continue
            if len(text) >= 9 and all(c in "0123456789abcdef" for c in text.lower()):
                return text.lower()[:40]
    return ""


def origin_main_sha(repo: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "origin/main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip().lower()[:40]


def fetch_origin_main(repo: Path) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", "-C", str(repo), "fetch", "origin", "main", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "fetch failed")[:400]
    return True, ""


def stop_latched(sd: Path | None = None) -> tuple[bool, str]:
    from scripts.lib.release_control import LATCH_ABSENT, LATCH_NAME, read_latch

    latch = (sd or state_dir()) / LATCH_NAME
    kind, body = read_latch(latch)
    if kind == LATCH_ABSENT:
        return False, "ABSENT"
    if kind == "SET":
        return True, f"SET:{((body or {}).get('reason') or 'latched')[:80]}"
    return True, f"UNREADABLE:{(body or {}).get('error', 'corrupt')}"


def deploy_delegation_path() -> Path:
    return Path(
        os.environ.get("TRADEAI_DEPLOY_DELEGATION")
        or (Path.home() / ".config" / "tradeai" / "deploy_on_main" / "delegation.json")
    )


def deploy_delegation_armed() -> tuple[bool, str]:
    """Standing deploy (promote-only) delegation. Missing/PAUSED/REVOKED = not armed.

    Path: TRADEAI_DEPLOY_DELEGATION (host file outside the repo) or
    ~/.config/tradeai/deploy_on_main/delegation.json
    """
    path = deploy_delegation_path()
    if not path.is_file():
        # Soft-add / dry environments: allow when TRADEAI_DEPLOY_DELEGATION_SOFT=1
        if os.environ.get("TRADEAI_DEPLOY_DELEGATION_SOFT") == "1":
            return True, "soft_armed"
        return False, f"missing:{path}"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"unreadable:{type(exc).__name__}"
    status = str(body.get("status") or "").upper()
    if status != "ACTIVE":
        return False, f"status:{status or 'empty'}"
    return True, "ACTIVE"


def decide(
    *,
    repo: Path,
    releases: Path | None = None,
    fetch: bool = True,
) -> PollDecision:
    if fetch:
        ok, err = fetch_origin_main(repo)
        if not ok:
            return PollDecision("refuse", f"fetch_failed:{err}")
    main = origin_main_sha(repo)
    if not main or len(main) < 9:
        return PollDecision("refuse", "origin_main_unreadable")
    cur = current_pin_sha(releases)
    if cur and main.startswith(cur[: min(40, len(cur))]) or (cur and cur.startswith(main[: min(40, len(main))])):
        return PollDecision("noop", "already_served", main_sha=main, current_sha=cur)
    if cur and main == cur:
        return PollDecision("noop", "already_served", main_sha=main, current_sha=cur)
    # Normalize short pins: if CURRENT short sha is prefix of main, noop
    if cur and len(cur) >= 9 and main.startswith(cur):
        return PollDecision("noop", "already_served", main_sha=main, current_sha=cur)

    stopped, stop_detail = stop_latched()
    if stopped:
        return PollDecision("refuse", f"stop_latched:{stop_detail}", main_sha=main, current_sha=cur)

    armed, arm_detail = deploy_delegation_armed()
    if not armed:
        return PollDecision("refuse", f"delegation_not_armed:{arm_detail}", main_sha=main, current_sha=cur)

    return PollDecision("promote", "main_ahead_of_current", main_sha=main, current_sha=cur)


def write_receipt(
    *,
    path_kind: str,
    outcome: str,
    main_sha: str,
    current_sha_before: str,
    current_sha_after: str = "",
    reason: str = "",
    detail: Optional[dict[str, Any]] = None,
) -> Path:
    out_dir = receipts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": SCHEMA,
        "as_of": _utc_now(),
        "path": path_kind,
        "outcome": outcome,
        "main_sha": main_sha,
        "current_sha_before": current_sha_before,
        "current_sha_after": current_sha_after,
        "reason": reason,
        "detail": detail or {},
    }
    name = f"{_utc_now().replace(':', '').replace('-', '')}_{path_kind}_{outcome}.json"
    dest = out_dir / name
    dest.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def _align_checkout(repo: Path, sha: str) -> tuple[int, str]:
    """Clean fast-forward to the selected exact main commit; never reset or discard.

    This runs only inside the admitted poller's GlobalReleaseLock. Existing Git
    and native deployment grants remain binding; no authority flags are minted.
    """
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        return 2, "checkout_target_invalid"

    def git(*args: str):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)

    status = git("status", "--porcelain")
    if status.returncode != 0:
        return status.returncode, "checkout_unreadable"
    if status.stdout.strip():
        return 2, "checkout_dirty"
    main = git("rev-parse", "refs/remotes/origin/main")
    if main.returncode != 0 or main.stdout.strip() != sha:
        return 2, "checkout_target_not_current_main"
    head = git("rev-parse", "HEAD")
    if head.returncode != 0:
        return head.returncode, "checkout_head_unreadable"
    if head.stdout.strip() == sha:
        return 0, "checkout_already_at_target"
    ancestor = git("merge-base", "--is-ancestor", "HEAD", sha)
    if ancestor.returncode != 0:
        return ancestor.returncode, "checkout_not_fast_forward"
    moved = git("merge", "--ff-only", "--no-edit", sha)
    if moved.returncode != 0:
        return moved.returncode, "checkout_fast_forward_refused"
    actual = git("rev-parse", "HEAD")
    if actual.returncode != 0 or actual.stdout.strip() != sha:
        return 2, "checkout_head_mismatch"
    status = git("status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        return 2, "checkout_dirty_after_fast_forward"
    return 0, "checkout_fast_forwarded"


_BINDING_LINE = re.compile(r'"binding_source":\s*"([a-z_]+)"')


def _binding_of(stdout: str) -> str:
    """How the native preflight bound this action: deploy_delegation | capability_ledger | grant | none."""
    found = ""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{") or '"allowed"' not in line:
            continue
        try:
            body = json.loads(line)
        except ValueError:
            continue
        if not isinstance(body, dict) or "allowed" not in body:
            continue
        if body.get("allowed"):
            found = str(body.get("binding_source") or "grant")
        elif not found:
            found = "none"
    return found


def run_deploy_script(
    repo: Path,
    sha: str,
    *,
    dry_run: bool = False,
    extra_env: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    script = repo / "scripts" / "cio_phase2_exact_main_deploy.sh"
    if not script.is_file():
        return 127, f"missing:{script}"
    if dry_run:
        return 0, "dry_run:would_prepare_promote"
    # Native prepare refuses a stale checkout; it does not advance HEAD itself.
    # Align only by clean fast-forward to the exact selected origin/main SHA.
    rc, alignment = _align_checkout(repo, sha)
    if rc != 0:
        return rc, alignment
    # Native prepare/promote retain their own exact-main CI and binding checks. The poller never injects
    # emergency/train/grant-bypass authority; its only authority is the deploy-delegation ticket
    # (scripts/lib/deploy_delegation_binding.py), which the native preflight verifies independently.
    env = os.environ.copy()
    for foreign in ("TRADEAI_EMERGENCY_RELEASE_SHA", "TRADEAI_RELEASE_TRAIN_SHA", "TRADEAI_RELEASE_CAMPAIGN"):
        env.pop(foreign, None)
    env.update(extra_env or {})
    logs: list[str] = [alignment]
    for action in ("prepare", "promote"):
        r = subprocess.run(
            ["bash", str(script), action],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        logs.append(f"{action}:rc={r.returncode}")
        binding = _binding_of(r.stdout or "")
        if binding:
            logs.append(f"binding:{action}={binding}")
        if r.stdout:
            logs.append(r.stdout[-2000:])
        if r.stderr:
            logs.append(r.stderr[-2000:])
        if r.returncode != 0:
            return r.returncode, "\n".join(logs)
    return 0, "\n".join(logs)


def bindings_from_log(log: str) -> dict[str, str]:
    return dict(re.findall(r"^binding:(prepare|promote)=([a-z_]+)$", log or "", flags=re.M))


def failure_reason_line(log: str) -> str:
    """The one line an operator needs from a failed run's log."""
    lines = [ln.strip() for ln in (log or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith(("ERROR:", "RELEASE GRANT", "FATAL")):
            return ln[:300]
    if lines and lines[0].startswith("checkout_") and len(lines) == 1:
        return lines[0]
    return (lines[-1] if lines else "no output")[:300]


# ── checkout hygiene ─────────────────────────────────────────────────────────────────────────────


def preserve_dirty_enabled() -> bool:
    """Config flag (default ON): preserve a dirty canonical checkout (patch + tagged stash) and proceed."""
    return str(os.environ.get("TRADEAI_DEPLOY_PRESERVE_DIRTY", "1")).strip().lower() not in ("0", "false", "off", "no")


def _git(repo: Path, *args: str, **kw: Any) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False, **kw)


def dirty_paths(repo: Path) -> list[str]:
    st = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if st.returncode != 0:
        return []
    return [ln[3:] for ln in st.stdout.splitlines() if ln.strip()]


def preserve_dirty_checkout(repo: Path, sha: str) -> dict[str, Any]:
    """Save the dirty state as a timestamped patch in persistent-state and a uniquely tagged stash.

    Never discards: the patch file, the stash entry and a ``refs/deploy-on-main/autostash/<tag>`` ref all
    keep the work. Returns {ok, tag, patch, stash_sha, paths} (ok False = nothing was moved).
    """
    paths = dirty_paths(repo)
    stamp = _utc_now().replace(":", "").replace("-", "")
    tag = f"deploy_on_main-autostash-{stamp}-{sha[:12]}"
    out_dir = receipts_dir() / "dirty_checkout"
    out_dir.mkdir(parents=True, exist_ok=True)
    patch = out_dir / f"{tag}.patch"
    tracked = _git(repo, "diff", "--binary", "HEAD")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    body = [
        f"# {tag}",
        f"# repo: {repo}",
        f"# head: {_git(repo, 'rev-parse', 'HEAD').stdout.strip()}",
        "# paths:",
        *[f"#   {p}" for p in paths],
        "",
        tracked.stdout or "",
    ]
    for rel in [u for u in (untracked.stdout or "").splitlines() if u.strip()]:
        nd = _git(repo, "diff", "--binary", "--no-index", "/dev/null", rel)
        body.append(nd.stdout or f"# untracked (unreadable as diff): {rel}\n")
    patch.write_text("\n".join(body), encoding="utf-8")
    stash = _git(repo, "stash", "push", "--include-untracked", "-m", tag)
    if stash.returncode != 0:
        return {
            "ok": False,
            "tag": tag,
            "patch": str(patch),
            "paths": paths,
            "error": (stash.stderr or stash.stdout or "stash failed")[:300],
        }
    top = _git(repo, "rev-parse", "--verify", "-q", "refs/stash")
    stash_sha = top.stdout.strip()
    msg = _git(repo, "log", "-1", "--format=%s", stash_sha).stdout if stash_sha else ""
    if not stash_sha or tag not in msg:
        return {"ok": False, "tag": tag, "patch": str(patch), "paths": paths, "error": "stash_not_recorded"}
    _git(repo, "update-ref", f"refs/deploy-on-main/autostash/{tag}", stash_sha)
    if dirty_paths(repo):
        return {
            "ok": False,
            "tag": tag,
            "patch": str(patch),
            "paths": paths,
            "stash_sha": stash_sha,
            "error": "still_dirty_after_stash",
        }
    return {"ok": True, "tag": tag, "patch": str(patch), "paths": paths, "stash_sha": stash_sha}


def checkout_hygiene(repo: Path, sha: str) -> tuple[bool, dict[str, Any]]:
    """Clean → (True, {}). Dirty → P1 (deduped per SHA per hour) naming the paths; then preserve + proceed
    when the flag is on, else refuse. Never discards."""
    paths = dirty_paths(repo)
    if not paths:
        return True, {}
    info: dict[str, Any] = {"paths": paths[:50], "path_count": len(paths)}
    if preserve_dirty_enabled():
        saved = preserve_dirty_checkout(repo, sha)
        info.update(saved)
        ok = bool(saved.get("ok"))
    else:
        info["preserve"] = "disabled"
        ok = False
    shown = ", ".join(paths[:8]) + (f" (+{len(paths) - 8} more)" if len(paths) > 8 else "")
    if ok:
        msg = (
            f"deploy_on_main: canonical checkout {repo} was dirty before deploying main {sha[:12]} — "
            f"preserved and proceeding. Paths: {shown}. Patch: {info.get('patch')}; "
            f"stash '{info.get('tag')}' (ref refs/deploy-on-main/autostash/{info.get('tag')})."
        )
    else:
        msg = (
            f"deploy_on_main: canonical checkout {repo} is dirty — deploy of main {sha[:12]} BLOCKED "
            f"({info.get('error') or info.get('preserve')}). Paths: {shown}. Clean or stash it on the host."
        )
    if _dedupe_ok("dirty", sha, window_s=3600):
        _alert(msg, kind="deploy_on_main_dirty_checkout", detail=info)
    return ok, info


# ── main's required checks ───────────────────────────────────────────────────────────────────────


def main_checks_status(repo: Path, sha: str) -> tuple[str, list[str]]:
    """green | pending | red | unavailable — exact-SHA push/main evidence via the canonical preflight."""
    pre = repo / "scripts" / "release_grant_preflight.py"
    if not pre.is_file():
        return "unavailable", ["preflight_absent"]
    try:
        r = subprocess.run(
            [os.environ.get("TRADEAI_PY") or sys.executable, str(pre), "--ci-only", "--sha", sha],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "unavailable", [f"ci_read:{type(exc).__name__}"]
    try:
        ev = json.loads([ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith("{")][-1])
    except (IndexError, ValueError):
        return "unavailable", [f"rc={r.returncode}"]
    errors = [str(e) for e in (ev.get("errors") or [])]
    if ev.get("ok"):
        return "green", []
    if any(e.startswith("checks_unavailable") for e in errors):
        return "unavailable", errors[:10]
    red = [
        c
        for c in (ev.get("checks") or [])
        if c.get("status") == "completed" and c.get("conclusion") not in ("success", None)
    ]
    return ("red" if red else "pending"), errors[:10]


def run_post_release_tester(repo: Path, *, dry_run: bool = False) -> tuple[int, str]:
    tester = repo / "scripts" / "post_release_tester.py"
    if not tester.is_file():
        return 0, "post_release_tester_absent_skip"
    if dry_run:
        return 0, "dry_run:would_verify"
    r = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(tester)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-2000:]


def poll_once(
    *,
    repo: Path,
    dry_run: bool = False,
    fetch: bool = True,
    apply: bool = False,
) -> dict[str, Any]:
    """One poll cycle. apply=False never runs prepare/promote (default safe)."""
    from scripts.lib.release_control import GlobalReleaseLock, LockBusy

    decision = decide(repo=repo, fetch=fetch)
    result: dict[str, Any] = {
        "as_of": _utc_now(),
        "action": decision.action,
        "reason": decision.reason,
        "main_sha": decision.main_sha,
        "current_sha": decision.current_sha,
        "dry_run": dry_run,
        "apply": apply,
    }
    if decision.action != "promote":
        write_receipt(
            path_kind=PATH_POLLER,
            outcome=decision.action,
            main_sha=decision.main_sha,
            current_sha_before=decision.current_sha,
            reason=decision.reason,
        )
        if decision.action == "noop" and decision.reason == "already_served":
            track_outcome("served", decision.main_sha, repo=repo)
        return result

    if not apply:
        write_receipt(
            path_kind=PATH_POLLER,
            outcome="would_promote",
            main_sha=decision.main_sha,
            current_sha_before=decision.current_sha,
            reason=decision.reason,
            detail={"apply": False},
        )
        result["outcome"] = "would_promote"
        return result

    sd = state_dir()
    try:
        with GlobalReleaseLock(sd, timeout_s=0.0):
            # Re-check STOP under the lock
            stopped, stop_detail = stop_latched(sd)
            if stopped:
                write_receipt(
                    path_kind=PATH_POLLER,
                    outcome="refuse",
                    main_sha=decision.main_sha,
                    current_sha_before=decision.current_sha,
                    reason=f"stop_under_lock:{stop_detail}",
                )
                result["outcome"] = "refuse"
                result["reason"] = f"stop_under_lock:{stop_detail}"
                return result

            # A delegation revoked while waiting for the lock cannot authorize
            # either the local checkout advance or a native prepare/promote.
            armed, arm_detail = deploy_delegation_armed()
            if not armed:
                result["outcome"] = "refuse"
                result["reason"] = f"delegation_under_lock:{arm_detail}"
                write_receipt(
                    path_kind=PATH_POLLER,
                    outcome="refuse",
                    main_sha=decision.main_sha,
                    current_sha_before=decision.current_sha,
                    reason=result["reason"],
                )
                return result
            return _deploy_under_lock(repo, decision, result, sd, dry_run=dry_run)
    except LockBusy:
        write_receipt(
            path_kind=PATH_POLLER,
            outcome="refuse",
            main_sha=decision.main_sha,
            current_sha_before=decision.current_sha,
            reason="global_release_lock_busy",
        )
        result["outcome"] = "refuse"
        result["reason"] = "global_release_lock_busy"
        return result


def _deploy_under_lock(
    repo: Path, decision: PollDecision, result: dict[str, Any], sd: Path, *, dry_run: bool
) -> dict[str, Any]:
    """Called only while GlobalReleaseLock is held, STOP is absent and the delegation is armed."""
    from scripts.lib import deploy_delegation_binding as DDB

    sha = decision.main_sha
    t0 = time.monotonic()
    detail: dict[str, Any] = {}

    def failed(rc: int, reason: str, log: str, *, after: str = "") -> dict[str, Any]:
        line = failure_reason_line(log)
        write_receipt(
            path_kind=PATH_POLLER,
            outcome="deploy_failed",
            main_sha=sha,
            current_sha_before=decision.current_sha,
            current_sha_after=after,
            reason=reason,
            detail={
                **detail,
                "reason_line": line,
                "log_tail": log[-1500:],
                "elapsed_s": round(time.monotonic() - t0, 1),
            },
        )
        result.update(outcome="deploy_failed", rc=rc, failure=line)
        track_outcome("failed", sha, reason_line=line, repo=repo, current=decision.current_sha)
        return result

    extra_env: dict[str, str] = {}
    ticket: Optional[Path] = None
    if not dry_run:
        ci, errors = main_checks_status(repo, sha)
        detail["main_checks"] = ci
        if ci in ("pending", "unavailable"):
            # Not a failure: Mergify just merged and push/main CI is still running (or GitHub is unreachable).
            write_receipt(
                path_kind=PATH_POLLER,
                outcome="waiting_ci",
                main_sha=sha,
                current_sha_before=decision.current_sha,
                reason=f"main_checks_{ci}",
                detail={"errors": errors},
            )
            result.update(outcome="waiting_ci", reason=f"main_checks_{ci}")
            return result
        if ci == "red":
            return failed(
                3, "main_checks_red", "ERROR: main required checks are red for this SHA: " + "; ".join(errors[:5])
            )
        clean, hygiene = checkout_hygiene(repo, sha)
        if hygiene:
            detail["dirty_checkout"] = hygiene
        if not clean:
            return failed(2, "checkout_dirty", "checkout_dirty")
        ticket, nonce = DDB.issue_ticket(sd, sha)
        extra_env = {DDB.TICKET_ENV: str(ticket), DDB.NONCE_ENV: nonce}
    try:
        rc, log = run_deploy_script(repo, sha, dry_run=dry_run, extra_env=extra_env)
    finally:
        if ticket is not None:
            DDB.revoke_ticket(ticket)
    bindings = bindings_from_log(log)
    if bindings:
        detail["bindings"] = bindings
        vals = set(bindings.values())
        detail["matched_by"] = (
            vals.pop() if len(vals) == 1 else ",".join(f"{k}={v}" for k, v in sorted(bindings.items()))
        )
        result["matched_by"] = detail["matched_by"]
    after = current_pin_sha()
    if rc != 0:
        return failed(rc, f"deploy_rc={rc}", log, after=after)

    vrc, vlog = run_post_release_tester(repo, dry_run=dry_run)
    outcome = "verified" if vrc == 0 else "verify_failed"
    write_receipt(
        path_kind=PATH_POLLER,
        outcome=outcome,
        main_sha=sha,
        current_sha_before=decision.current_sha,
        current_sha_after=after,
        reason=decision.reason,
        detail={**detail, "verify_rc": vrc, "verify_tail": vlog[-800:], "elapsed_s": round(time.monotonic() - t0, 1)},
    )
    result["outcome"] = outcome
    result["current_sha_after"] = after
    if dry_run:
        return result
    if vrc != 0:
        _alert(
            f"deploy_on_main: promoted main {sha[:12]} ({commit_subject(repo, sha)}) but post-release "
            f"verify FAILED (rc={vrc}): {failure_reason_line(vlog)}",
            kind="deploy_on_main_verify",
        )
    track_outcome("served", sha, repo=repo)
    return result


# ── alerting: one P1 per failure streak, one OK on recovery ─────────────────────────────────────────

FAIL_STREAK_ALERT = 3


def _alert_state_path() -> Path:
    return receipts_dir() / "alert_state.json"


def _load_alert_state() -> dict[str, Any]:
    try:
        body = json.loads(_alert_state_path().read_text(encoding="utf-8"))
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_alert_state(state: dict[str, Any]) -> None:
    path = _alert_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _dedupe_ok(kind: str, sha: str, *, window_s: int, now: Optional[float] = None) -> bool:
    """True (and recorded) when no ``kind`` alert for this SHA was sent within window_s."""
    now = time.time() if now is None else now
    state = _load_alert_state()
    sent = state.setdefault("dedupe", {}).setdefault(kind, {})
    last = float(sent.get(sha) or 0)
    if now - last < window_s:
        return False
    sent[sha] = now
    # keep the ledger small: the last 50 SHAs per kind
    for old in sorted(sent, key=lambda k: float(sent[k]))[:-50]:
        sent.pop(old, None)
    _save_alert_state(state)
    return True


def commit_subject(repo: Path, sha: str) -> str:
    r = _git(repo, "log", "-1", "--format=%s", sha)
    return (r.stdout or "").strip()[:120] if r.returncode == 0 else ""


def track_outcome(
    kind: str, sha: str, *, reason_line: str = "", repo: Optional[Path] = None, current: str = ""
) -> Optional[str]:
    """kind: failed | served. Returns the alert kind sent ("p1" | "ok") or None.

    deploy_failed for the same SHA FAIL_STREAK_ALERT times in a row → one P1 naming the reason; a later
    promote/already-served after that P1 → one OK note. Other outcomes (waiting_ci, lock busy, STOP)
    neither extend nor clear a streak.
    """
    state = _load_alert_state()
    streak = state.get("fail_streak") or {}
    sent: Optional[str] = None
    if kind == "failed":
        if streak.get("sha") != sha:
            streak = {"sha": sha, "count": 0, "first_at": _utc_now(), "alerted": False}
        streak["count"] = int(streak.get("count") or 0) + 1
        streak["reason"] = reason_line
        streak["last_at"] = _utc_now()
        if streak["count"] >= FAIL_STREAK_ALERT and not streak.get("alerted"):
            subject = commit_subject(repo, sha) if repo else ""
            _alert(
                f"deploy_on_main: main {sha[:12]} ({subject or 'no subject'}) has failed to deploy "
                f"{streak['count']} times in a row since {streak['first_at']}. CURRENT is still "
                f"{current[:12] or 'unknown'}. Reason: {reason_line or 'see receipt'}. "
                f"Receipts: data/runtime/deploy_on_main/latest.json",
                kind="deploy_on_main",
                detail={"sha": sha, "count": streak["count"]},
            )
            streak["alerted"] = True
            sent = "p1"
        state["fail_streak"] = streak
    elif kind == "served":
        if streak.get("alerted"):
            subject = commit_subject(repo, sha) if repo else ""
            _alert(
                f"deploy_on_main OK: main {sha[:12]} ({subject or 'no subject'}) is now served; the deploy "
                f"failure streak for {str(streak.get('sha'))[:12]} ({streak.get('count')} failures) has cleared.",
                kind="deploy_on_main_recovered",
                priority="P2",
                resolving=True,
            )
            sent = "ok"
        if streak:
            state["fail_streak"] = {}
        else:
            return None
    _save_alert_state(state)
    return sent


def _alert(
    message: str, *, kind: str, detail: Optional[dict[str, Any]] = None, priority: str = "P1", resolving: bool = False
) -> None:
    try:
        from scripts.delivery_failure_alerts import page_p1  # type: ignore

        page_p1(kind=kind, message=message, detail=detail, priority=priority, resolving=resolving)
    except Exception:  # noqa: BLE001 — never fail the poller on alert path
        pass


def _alert_p1(message: str) -> None:  # back-compat shim
    _alert(message, kind="deploy_on_main")

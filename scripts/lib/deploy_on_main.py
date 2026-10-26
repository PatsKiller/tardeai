"""Deploy-on-main poller core (AGENTS.md §25.10 / 24.0.0).

Promote-only: if origin/main tip ≠ CURRENT pin, STOP is absent, GlobalReleaseLock is free,
and the standing deploy delegation is armed, run cio_phase2_exact_main_deploy.sh prepare+promote
for that SHA, then post_release_tester, and write DeployOnMainReceipt@v1 (path=poller).

Never merges PRs or pushes remotes; local source advances only by exact-main fast-forward. Soft-add: live until 24.0.0 is ACTIVE stays the release train;
this module is the target path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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


def deploy_delegation_armed() -> tuple[bool, str]:
    """Standing deploy (promote-only) delegation. Missing/PAUSED/REVOKED = not armed.

    Path: TRADEAI_DEPLOY_DELEGATION (host file outside the repo) or
    ~/.config/tradeai/deploy_on_main/delegation.json
    """
    path = Path(
        os.environ.get("TRADEAI_DEPLOY_DELEGATION")
        or (Path.home() / ".config" / "tradeai" / "deploy_on_main" / "delegation.json")
    )
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


def run_deploy_script(repo: Path, sha: str, *, dry_run: bool = False) -> tuple[int, str]:
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
    # Native prepare/promote retain their own exact-main CI and grant checks.
    # The poller never injects emergency/train/grant-bypass authority.
    env = os.environ.copy()
    env.pop("TRADEAI_EMERGENCY_RELEASE_SHA", None)
    env.pop("TRADEAI_RELEASE_TRAIN_SHA", None)
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
        if r.stdout:
            logs.append(r.stdout[-2000:])
        if r.stderr:
            logs.append(r.stderr[-2000:])
        if r.returncode != 0:
            return r.returncode, "\n".join(logs)
    return 0, "\n".join(logs)


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

            t0 = time.monotonic()
            rc, log = run_deploy_script(repo, decision.main_sha, dry_run=dry_run)
            after = current_pin_sha()
            if rc != 0:
                write_receipt(
                    path_kind=PATH_POLLER,
                    outcome="deploy_failed",
                    main_sha=decision.main_sha,
                    current_sha_before=decision.current_sha,
                    current_sha_after=after,
                    reason=f"deploy_rc={rc}",
                    detail={"log_tail": log[-1500:], "elapsed_s": round(time.monotonic() - t0, 1)},
                )
                result["outcome"] = "deploy_failed"
                result["rc"] = rc
                _alert_p1(f"deploy_on_main failed rc={rc} sha={decision.main_sha[:12]}")
                return result

            vrc, vlog = run_post_release_tester(repo, dry_run=dry_run)
            outcome = "verified" if vrc == 0 else "verify_failed"
            write_receipt(
                path_kind=PATH_POLLER,
                outcome=outcome,
                main_sha=decision.main_sha,
                current_sha_before=decision.current_sha,
                current_sha_after=after,
                reason=decision.reason,
                detail={"verify_rc": vrc, "verify_tail": vlog[-800:], "elapsed_s": round(time.monotonic() - t0, 1)},
            )
            result["outcome"] = outcome
            result["current_sha_after"] = after
            if vrc != 0:
                _alert_p1(f"deploy_on_main verify failed sha={decision.main_sha[:12]}")
            return result
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


def _alert_p1(message: str) -> None:
    try:
        from scripts.delivery_failure_alerts import page_p1  # type: ignore

        page_p1(kind="deploy_on_main", message=message)
    except Exception:  # noqa: BLE001 — never fail the poller on alert path
        pass

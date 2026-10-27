"""Mergify queue / Dequeued monitor (AGENTS.md §25.10 / §28.12).

Dequeued must not be a dead end. Classify each blocked PR, auto-requeue when the
block is the known draft-skip false failure (or hotfix already on main), wake the
claim owner with an exact next step otherwise, and page P1 once per incident.

Never merges. Never adds ``operator-merge`` by itself — requeue is ``@mergifyio queue``
on a PR that already carries the label from Telegram Approve.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_CHECKS = ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")
MERGIFY_PAYLOAD_RE = re.compile(
    r"-\*- Mergify Payload -\*-\s*(\{.*?\})\s*-\*- Mergify Payload End -\*-",
    re.DOTALL,
)
DRAFT_SKIP_HINT = re.compile(
    r"on draft #\d+|Checks failed.*draft|check-skipped\s*=\s*(cio-hardening|ci-gate|release-readiness)",
    re.IGNORECASE,
)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_root() -> Path:
    return Path(
        os.environ.get("TRADEAI_STATE_ROOT")
        or (Path.home() / "trade-ai-releases" / "persistent-state")
    )


def receipts_dir(root: Path | None = None) -> Path:
    return (root or state_root()) / "data" / "runtime" / "mergify_queue_monitor"


@dataclass
class DequeueEvent:
    pr: int
    reason_code: str  # CHECKS_FAILED | CONFLICTS | MANUAL | RULE | BISECTION | UNKNOWN
    label: str
    speculative_draft: int | None = None
    body_excerpt: str = ""
    left_at: str = ""


@dataclass
class ActionPlan:
    pr: int
    classification: str
    # auto_requeue | wait_hotfix | conflict_rebase | real_ci_fail | hold | noop
    action: str
    message: str
    requeue: bool = False
    page_p1: bool = False
    wake_claim: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def parse_mergify_payload(body: str) -> dict[str, Any] | None:
    m = MERGIFY_PAYLOAD_RE.search(body or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def classify_dequeue(
    *,
    reason_code: str,
    body: str,
    mergeable: str | None,
    checks: dict[str, str] | None,
    hotfix_on_main: bool,
) -> ActionPlan:
    """Pure classifier — no I/O.

    ``checks`` maps check name → conclusion on the *real* PR head (not the draft).
    """
    reason = (reason_code or "UNKNOWN").upper()
    body = body or ""
    checks = checks or {}

    if reason in {"CONFLICTS", "CONFLICT"} or (mergeable or "").upper() == "CONFLICTING":
        return ActionPlan(
            pr=0,
            classification="CONFLICTS",
            action="conflict_rebase",
            message=(
                "Base conflict — rebase onto origin/main, push, wait for the four "
                "checks green, then `@mergifyio queue` (or refresh). Do not stop until merged."
            ),
            requeue=False,
            page_p1=True,
            wake_claim=True,
            detail={"reason": reason, "mergeable": mergeable},
        )

    draft_skip = bool(DRAFT_SKIP_HINT.search(body)) or (
        reason == "CHECKS_FAILED"
        and any(checks.get(c) == "SUCCESS" for c in REQUIRED_CHECKS)
        and "draft #" in body.lower()
    )

    if draft_skip or reason == "CHECKS_FAILED":
        real_red = [
            c
            for c in REQUIRED_CHECKS
            if checks.get(c) in {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"}
        ]
        if real_red:
            return ActionPlan(
                pr=0,
                classification="REAL_CI_FAIL",
                action="real_ci_fail",
                message=(
                    f"Real CI red on head: {', '.join(real_red)}. Fix tests, push, "
                    "wait for green, then `@mergifyio queue`. Do not stop until merged."
                ),
                requeue=False,
                page_p1=True,
                wake_claim=True,
                detail={"red": real_red},
            )
        if hotfix_on_main:
            return ActionPlan(
                pr=0,
                classification="DRAFT_SKIP_FALSE_FAIL",
                action="auto_requeue",
                message=(
                    "Dequeued on speculative draft skip (false fail). Hotfix on main — "
                    "auto-requeueing with `@mergifyio queue`."
                ),
                requeue=True,
                page_p1=False,
                wake_claim=False,
                detail={"draft_skip": True, "hotfix_on_main": True},
            )
        return ActionPlan(
            pr=0,
            classification="DRAFT_SKIP_FALSE_FAIL",
            action="wait_hotfix",
            message=(
                "Dequeued because Mergify speculative drafts skipped required checks. "
                "Root fix: `.mergify.yml` merge_conditions tolerate skip + CI runs on "
                "`mergify/*` heads. Once that hotfix is on main, this monitor requeues "
                "automatically. Do not treat Dequeued as done."
            ),
            requeue=False,
            page_p1=True,
            wake_claim=True,
            detail={"draft_skip": True, "hotfix_on_main": False},
        )

    return ActionPlan(
        pr=0,
        classification=reason or "UNKNOWN",
        action="hold",
        message=f"Dequeued ({reason}). Inspect Mergify status comment; fix; `@mergifyio queue`.",
        requeue=False,
        page_p1=True,
        wake_claim=True,
        detail={"reason": reason},
    )


def hotfix_landed(main_mergify_yml: str) -> bool:
    """True when main's .mergify.yml has the skip-tolerant merge_conditions."""
    if "check-skipped=cio-hardening" in main_mergify_yml:
        return True
    if "batch_size: 1" in main_mergify_yml and "check-skipped=" in main_mergify_yml:
        return True
    return False


def _gh(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def fetch_open_operator_merge_prs(repo: str = "PatsKiller/tardeai") -> list[dict[str, Any]]:
    proc = _gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--label",
            "operator-merge",
            "--json",
            "number,title,mergeable,isDraft,labels,headRefName,baseRefName,url",
            "--limit",
            "50",
        ]
    )
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []


def fetch_latest_dequeue_comment(pr: int, repo: str = "PatsKiller/tardeai") -> tuple[str, dict[str, Any] | None]:
    proc = _gh(["api", f"repos/{repo}/issues/{pr}/comments", "--paginate"])
    if proc.returncode != 0:
        return "", None
    try:
        comments = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return "", None
    latest_body = ""
    latest_payload: dict[str, Any] | None = None
    for c in comments:
        body = c.get("body") or ""
        payload = parse_mergify_payload(body)
        if payload and payload.get("state") == "dequeued":
            latest_body = body
            latest_payload = payload
        elif "Left the queue" in body or "dequeue_reason" in body:
            latest_body = body
    return latest_body, latest_payload


def fetch_head_check_conclusions(pr: int, repo: str = "PatsKiller/tardeai") -> dict[str, str]:
    proc = _gh(
        [
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "statusCheckRollup",
        ]
    )
    out: dict[str, str] = {}
    if proc.returncode != 0:
        return out
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return out
    for row in data.get("statusCheckRollup") or []:
        name = row.get("name") or ""
        conclusion = (row.get("conclusion") or row.get("state") or "").upper()
        if name in REQUIRED_CHECKS:
            out[name] = conclusion
    return out


def fetch_main_mergify_yml(repo: str = "PatsKiller/tardeai") -> str:
    proc = _gh(["api", f"repos/{repo}/contents/.mergify.yml?ref=main", "--jq", ".content"])
    if proc.returncode != 0:
        return ""
    import base64

    raw = (proc.stdout or "").strip().replace("\n", "")
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def post_pr_comment(pr: int, body: str, repo: str = "PatsKiller/tardeai") -> bool:
    proc = _gh(
        [
            "pr",
            "comment",
            str(pr),
            "--repo",
            repo,
            "--body",
            body,
        ]
    )
    return proc.returncode == 0


def requeue_pr(pr: int, repo: str = "PatsKiller/tardeai") -> bool:
    """Ask Mergify to queue again. PR must still have operator-merge."""
    return post_pr_comment(pr, "@mergifyio queue", repo=repo)


def wake_claim_for_pr(pr: int, message: str) -> dict[str, Any]:
    """Best-effort: find a claim mentioning this PR and write blocker + handoff."""
    claims_dir = state_root() / "data" / "coordination" / "claims"
    if not claims_dir.is_dir():
        return {"woke": False, "reason": "no_claims_dir"}
    needle = f"#{pr}"
    hit: Path | None = None
    for path in sorted(claims_dir.glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if needle in raw or f"PR {pr}" in raw or f"pr {pr}" in raw:
            hit = path
            break
    if hit is None:
        return {"woke": False, "reason": "no_claim_for_pr"}
    claim_id = hit.stem
    py = ROOT / ".venv" / "bin" / "python"
    if not py.is_file():
        py = Path(
            os.environ.get("TRADEAI_PYTHON")
            or (Path.home() / "trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python")
        )
    script = ROOT / "scripts" / "agent_claim.py"
    if not script.is_file():
        return {"woke": False, "reason": "no_agent_claim_script", "claim_id": claim_id}
    blocker = subprocess.run(
        [
            str(py),
            str(script),
            "blocker",
            "--claim",
            claim_id,
            "--force",
            f"Mergify dequeued #{pr}: {message[:400]}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    handoff = subprocess.run(
        [
            str(py),
            str(script),
            "handoff",
            "--claim",
            claim_id,
            "--force",
            "--next",
            f"Fix Mergify block on #{pr}, then `@mergifyio queue`; do not stop until merged. {message[:240]}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return {
        "woke": blocker.returncode == 0 or handoff.returncode == 0,
        "claim_id": claim_id,
        "blocker_rc": blocker.returncode,
        "handoff_rc": handoff.returncode,
    }


def already_acted(pr: int, classification: str, root: Path | None = None) -> bool:
    """Dedupe: one auto action per (pr, classification) per 6h window file."""
    d = receipts_dir(root)
    stamp = _utc()[:13]  # YYYY-MM-DDTHH
    marker = d / "dedupe" / f"{pr}_{classification}_{stamp}.flag"
    return marker.is_file()


def mark_acted(pr: int, classification: str, root: Path | None = None) -> None:
    d = receipts_dir(root) / "dedupe"
    d.mkdir(parents=True, exist_ok=True)
    stamp = _utc()[:13]
    (d / f"{pr}_{classification}_{stamp}.flag").write_text(_utc() + "\n", encoding="utf-8")


def run_once(
    *,
    dry_run: bool = True,
    repo: str = "PatsKiller/tardeai",
    root: Path | None = None,
) -> dict[str, Any]:
    """Scan operator-merge PRs; act on dequeued ones. Default dry-run."""
    main_yml = fetch_main_mergify_yml(repo=repo)
    hot = hotfix_landed(main_yml)
    prs = fetch_open_operator_merge_prs(repo=repo)
    plans: list[dict[str, Any]] = []
    actions_taken: list[dict[str, Any]] = []

    for pr_row in prs:
        pr = int(pr_row["number"])
        labels = {((x.get("name") if isinstance(x, dict) else x) or "") for x in (pr_row.get("labels") or [])}
        body, payload = fetch_latest_dequeue_comment(pr, repo=repo)
        is_dequeued = "dequeued" in labels or (payload and payload.get("state") == "dequeued")
        if not is_dequeued and not body:
            continue
        reason = "UNKNOWN"
        if payload:
            dr = payload.get("dequeue_reason") or {}
            reason = str(dr.get("code") or reason)
        checks = fetch_head_check_conclusions(pr, repo=repo)
        plan = classify_dequeue(
            reason_code=reason,
            body=body,
            mergeable=pr_row.get("mergeable"),
            checks=checks,
            hotfix_on_main=hot,
        )
        plan.pr = pr
        plans.append(asdict(plan))

        if already_acted(pr, plan.classification, root=root) and plan.action == "auto_requeue":
            actions_taken.append({"pr": pr, "skipped": "dedupe"})
            continue

        comment = (
            f"### Mergify queue monitor\n\n"
            f"**Classification:** `{plan.classification}`\n\n"
            f"{plan.message}\n\n"
            f"_as_of {_utc()} · dry_run={dry_run}_"
        )

        if dry_run:
            actions_taken.append({"pr": pr, "would": asdict(plan), "comment": comment[:200]})
            continue

        if plan.action == "auto_requeue" and plan.requeue:
            post_pr_comment(pr, comment, repo=repo)
            ok = requeue_pr(pr, repo=repo)
            mark_acted(pr, plan.classification, root=root)
            actions_taken.append({"pr": pr, "requeued": ok})
            continue

        post_pr_comment(pr, comment, repo=repo)
        woke = None
        if plan.wake_claim:
            woke = wake_claim_for_pr(pr, plan.message)
        if plan.page_p1:
            try:
                from scripts.delivery_failure_alerts import page_p1

                page_p1(
                    kind="mergify_dequeued",
                    message=f"#{pr} {plan.classification}: {plan.message[:180]}",
                    detail={"pr": pr, "plan": asdict(plan)},
                )
            except Exception as exc:  # noqa: BLE001
                actions_taken.append({"pr": pr, "page_error": f"{type(exc).__name__}:{exc}"[:120]})
        mark_acted(pr, plan.classification, root=root)
        actions_taken.append({"pr": pr, "commented": True, "woke": woke, "action": plan.action})

    receipt = {
        "schema": "MergifyQueueMonitorReceipt@v1",
        "as_of": _utc(),
        "dry_run": dry_run,
        "hotfix_on_main": hot,
        "scanned": len(prs),
        "plans": plans,
        "actions": actions_taken,
    }
    out = receipts_dir(root)
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "latest.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        stamp = _utc().replace(":", "").replace("-", "")
        (out / f"{stamp}.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    return receipt

#!/usr/bin/env python3
"""main_ci_watch.py — exact-SHA CI of main HEAD, cached as a receipt for the Releases page (read-only).

Why (operator 2026-10-22, System -> Releases & schedules): "Releasing next <sha> · main CI UNAVAILABLE". The page
reads only ``post_merge_ci.json``, which the deploy writes for the SHA it promotes, and never calls GitHub from the
request path. Nothing cached the CI of main HEAD between deploys. This script is that cache.

One run:
  1. main HEAD from GitHub (``gh api repos/<slug>/commits/main``, GET), or ``--sha``;
  2. the push/main workflow runs for exactly that SHA (``gh api --paginate
     repos/<slug>/actions/runs?head_sha=<sha>&event=push&branch=main``, GET), latest run/attempt per workflow path —
     the same selection rule as scripts/release_grant_preflight.py ``evaluate_push_checks``;
  3. per required workflow (``REQUIRED_WORKFLOWS`` == release_grant_preflight.REQUIRED_PUSH_WORKFLOWS, pinned by
     test) SUCCESS | FAILURE | PENDING | MISSING, and one overall state:
       FAILURE      any required workflow completed with a conclusion other than success
       SUCCESS      every required workflow completed with success
       PENDING      otherwise (queued / in progress, or not started yet: MISSING counts as pending)
       UNAVAILABLE  GitHub could not be read (exit 1; the failed receipt keeps the previous ok_at).

    python3 scripts/main_ci_watch.py --dry-run     # print only; writes nothing
    python3 scripts/main_ci_watch.py               # real run: writes the receipt

A real run writes exactly one file: the LaneRunReceipt@v2 ``<state root>/data/runtime/main-ci-watch_last.json``
(summary schema ``MainCiWatch@v1``), read by GET /api/v2/ops/releases-schedules (next_release.ci). Every gh call goes
through pr_hygiene_audit's read-only guard (GET-only ``gh api``). No git write, no DB, no model, no send, no broker.

Scheduling: none in this change. The proposed n8n shadow lane (registry row, allowlist entry and a DRAFT health
contract) is docs/ops/proposals/main-ci-watch-lane-20261022/ — registering it is the owner's step (AGENTS.md
§23.19: an agent never marks a contract REVIEWED). Exit 0 = the state was read (PENDING / FAILURE are output, not
failures); 1 = GitHub unreadable; 2 = usage / no slug.

MBI_BEHAVIOR = 0. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pr_hygiene_audit as PHA  # noqa: E402  (read-only Gh / Git, slug + canonical-clone resolution)

LANE_ID = "main-ci-watch"
SCHEMA = "MainCiWatch@v1"
MAIN_BRANCH = "main"
#: Must equal scripts/release_grant_preflight.py REQUIRED_PUSH_WORKFLOWS (the promote gate); a test pins it.
REQUIRED_WORKFLOWS = (
    ".github/workflows/agent-governance.yml",
    ".github/workflows/cio-production-hardening-ci.yml",
    ".github/workflows/release-readiness.yml",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
STATES = ("SUCCESS", "FAILURE", "PENDING", "UNAVAILABLE")


def select_latest(runs: Iterable[Mapping[str, Any]], sha: str) -> dict[str, Mapping[str, Any]]:
    """Latest push/main run per workflow path for exactly ``sha``; a later run or attempt supersedes, never chosen by
    conclusion (release_grant_preflight.evaluate_push_checks rule)."""
    latest: dict[str, tuple[tuple[int, int, int], Mapping[str, Any]]] = {}
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        if run.get("head_sha") != sha or run.get("event") != "push" or run.get("head_branch") != MAIN_BRANCH:
            continue
        path = str(run.get("path") or "").split("@", 1)[0]
        if not path or not run.get("id"):
            continue
        order = (int(run.get("run_number") or 0), int(run["id"]), int(run.get("run_attempt") or 1))
        if path not in latest or order > latest[path][0]:
            latest[path] = (order, run)
    return {p: r for p, (_, r) in latest.items()}


def workflow_state(run: Optional[Mapping[str, Any]]) -> str:
    if run is None:
        return "MISSING"
    if run.get("status") != "completed":
        return "PENDING"
    return "SUCCESS" if run.get("conclusion") == "success" else "FAILURE"


def evaluate(
    sha: str, runs: Iterable[Mapping[str, Any]], *, checked_at: Optional[str] = None, head_source: str = "github"
) -> dict[str, Any]:
    """Pure: the MainCiWatch@v1 summary for ``sha`` from GitHub workflow-run JSON."""
    latest = select_latest(runs, sha)
    rows = []
    for path in REQUIRED_WORKFLOWS:
        run = latest.get(path)
        rows.append(
            {
                "path": path,
                "name": (run or {}).get("name") or Path(path).stem,
                "state": workflow_state(run),
                "status": (run or {}).get("status"),
                "conclusion": (run or {}).get("conclusion"),
                "run_id": (run or {}).get("id"),
                "run_attempt": (run or {}).get("run_attempt"),
                "url": (run or {}).get("html_url"),
                "updated_at": (run or {}).get("updated_at"),
            }
        )
    states = [r["state"] for r in rows]
    overall = "FAILURE" if "FAILURE" in states else "SUCCESS" if all(s == "SUCCESS" for s in states) else "PENDING"
    return {
        "schema": SCHEMA,
        "head_sha": sha,
        "head_source": head_source,
        "branch": MAIN_BRANCH,
        "state": overall,
        "required_workflows": list(REQUIRED_WORKFLOWS),
        "workflows": rows,
        "counts": {s: states.count(s) for s in ("SUCCESS", "FAILURE", "PENDING", "MISSING")},
        "latest_update_at": max((str(r["updated_at"]) for r in rows if r["updated_at"]), default=None),
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
    }


def main_head(gh: "PHA.Gh") -> str:
    doc = gh.json("api", f"repos/{gh.slug}/commits/{MAIN_BRANCH}")
    sha = str((doc or {}).get("sha") or "") if isinstance(doc, Mapping) else ""
    if not SHA_RE.match(sha):
        raise PHA.AuditError("main HEAD sha missing from the commits API response")
    return sha


def workflow_runs(gh: "PHA.Gh", sha: str) -> list[Mapping[str, Any]]:
    doc = gh.json(
        "api", "--paginate", f"repos/{gh.slug}/actions/runs?head_sha={sha}&event=push&branch={MAIN_BRANCH}&per_page=100"
    )
    pages = doc if isinstance(doc, list) else [doc]
    runs: list[Mapping[str, Any]] = []
    for page in pages:
        if not isinstance(page, Mapping) or not isinstance(page.get("workflow_runs"), list):
            raise PHA.AuditError("invalid workflow-runs response")
        runs.extend(r for r in page["workflow_runs"] if isinstance(r, Mapping))
    return runs


def watch(gh: "PHA.Gh", sha: Optional[str] = None) -> dict[str, Any]:
    head_source = "argument" if sha else "github"
    sha = sha or main_head(gh)
    return evaluate(sha, workflow_runs(gh, sha), head_source=head_source)


def summary_line(s: Mapping[str, Any]) -> str:
    c = s.get("counts") or {}
    return (
        f"main {str(s.get('head_sha'))[:9]} CI {s.get('state')} "
        f"(success={c.get('SUCCESS', 0)} failure={c.get('FAILURE', 0)} pending={c.get('PENDING', 0)} "
        f"missing={c.get('MISSING', 0)})"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="print only; write nothing")
    ap.add_argument("--json", action="store_true", help="print the summary JSON")
    ap.add_argument("--sha", help="check this full SHA instead of GitHub's main HEAD")
    ap.add_argument("--slug", help="owner/name (default: TRADEAI_PR_HYGIENE_SLUG, else the clone's origin URL)")
    a = ap.parse_args(argv)
    if a.sha and not SHA_RE.match(a.sha):
        print("[main-ci-watch] --sha must be a full 40-hex SHA", file=sys.stderr)
        return 2
    from lib.lane_last_receipt import dry_run_report, now_iso, write_lane_receipt

    started = now_iso()
    slug = PHA.resolve_slug(a.slug, PHA.Git(PHA.resolve_repo(None)))
    if not slug:
        print("[main-ci-watch] no GitHub slug (pass --slug or run with a clone)", file=sys.stderr)
        if not a.dry_run:
            write_lane_receipt(
                LANE_ID,
                ok=False,
                exit_code=2,
                started_at=started,
                script="main_ci_watch.py",
                error="no_github_slug",
                output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"config_missing": 1}},
            )
        return 2
    try:
        summary = watch(PHA.Gh(slug), a.sha)
    except PHA.AuditError as exc:
        print(f"[main-ci-watch] GitHub unreadable: {exc}", file=sys.stderr)
        if not a.dry_run:
            write_lane_receipt(
                LANE_ID,
                ok=False,
                exit_code=1,
                started_at=started,
                script="main_ci_watch.py",
                error=f"AuditError: {exc}",
                summary={"schema": SCHEMA, "state": "UNAVAILABLE", "head_sha": a.sha},
                output={"produced_count": 0, "attempted_count": 1, "skipped_reasons": {"dependency_unavailable": 1}},
            )
        return 1
    summary["slug"] = slug
    print(json.dumps(summary, indent=1) if a.json else f"[main-ci-watch] {summary_line(summary)}")
    if a.dry_run:
        dry_run_report(
            LANE_ID,
            {"summary": summary_line(summary), "state": summary["state"], "head_sha": summary["head_sha"]},
            would_write=[f"data/runtime/{LANE_ID}_last.json"],
        )
        return 0
    write_lane_receipt(
        LANE_ID,
        ok=True,
        exit_code=0,
        started_at=started,
        script="main_ci_watch.py",
        summary=summary,
        output={
            "produced_count": len(summary["workflows"]),
            "attempted_count": len(summary["workflows"]),
            "skipped_reasons": {},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

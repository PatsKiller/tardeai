#!/usr/bin/env python3
"""Scan open PRs and Telegram-notify ones that are merge-ready.

A PR is notified when:
  - base=main, state=open
  - not draft
  - no held/broker labels
  - no operator-merge label yet (already approved)
  - required checks are green (cio-hardening, agent-governance,
    release-readiness, ci-gate)
  - no PENDING Telegram request for this head already delivered

Schedule (host cron / n8n after cutover): every 10–15 minutes. Operators get
one interrupt per head SHA; they never open github.com to Approve.

  .venv/bin/python scripts/notify_pr_merge_ready.py --dry-run
  .venv/bin/python scripts/notify_pr_merge_ready.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _list_prs(repo: str) -> list[dict]:
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--base",
            "main",
            "--state",
            "open",
            "--limit",
            "50",
            "--json",
            "number,title,url,headRefOid,isDraft,labels",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"gh pr list failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "[]")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true", help="Send Telegram (default is dry-run)")
    p.add_argument("--force-pr", type=int, default=0, help="Notify this PR even if checks are not green")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument(
        "--native",
        action="store_true",
        help="Use prmapprove (needs CURRENT promote); default is guard bridge",
    )
    args = p.parse_args(argv)
    apply = bool(args.apply) and not args.dry_run

    from scripts.lib import pr_merge_telegram as pmt

    env_via = os.environ.get("PR_MERGE_TELEGRAM_VIA_GUARD", "1").strip() not in ("0", "false", "no")
    via_guard = (not args.native) and env_via

    prs = _list_prs(args.repo)
    results: list[dict] = []
    for pr in prs:
        number = int(pr["number"])
        labels = {str(x.get("name") if isinstance(x, dict) else x) for x in (pr.get("labels") or [])}
        if pr.get("isDraft"):
            results.append({"pr": number, "action": "skip", "reason": "draft"})
            continue
        if labels & pmt.HOLD_LABELS:
            results.append({"pr": number, "action": "skip", "reason": "held_or_broker"})
            continue
        if pmt.LABEL in labels:
            results.append({"pr": number, "action": "skip", "reason": "already_labeled"})
            continue
        head = str(pr.get("headRefOid") or "")
        pending = pmt.find_pending(number, head)
        if pending and pending.get("delivery", {}).get("accepted"):
            results.append({"pr": number, "action": "skip", "reason": "already_notified", "request_id": pending["request_id"]})
            continue
        green, statuses = pmt.pr_check_rollup_green(number, repo=args.repo)
        if not green and number != args.force_pr:
            results.append({"pr": number, "action": "skip", "reason": "checks_not_green", "checks": statuses})
            continue
        if not apply:
            results.append(
                {
                    "pr": number,
                    "action": "would_notify",
                    "title": pr.get("title"),
                    "head": head[:9],
                    "checks": statuses,
                }
            )
            continue
        notify_fn = pmt.mint_and_notify_via_guard if via_guard else pmt.mint_and_notify
        out = notify_fn(
            pr_number=number,
            title=str(pr.get("title") or ""),
            head_sha=head,
            url=str(pr.get("url") or ""),
            reason="CI green — tap Approve to queue Mergify (no GitHub needed)",
            repo=args.repo,
        )
        results.append({"pr": number, "action": "notified" if out.get("ok") else "notify_failed", **out})

    summary = {
        "ok": True,
        "apply": apply,
        "via_guard": via_guard,
        "scanned": len(prs),
        "would_notify": sum(1 for r in results if r.get("action") == "would_notify"),
        "notified": sum(1 for r in results if r.get("action") == "notified"),
        "results": results,
    }
    try:
        pmt.write_notify_receipt(summary)
    except OSError as exc:
        summary["receipt_error"] = str(exc)
    if args.as_json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(
            f"scanned={summary['scanned']} would_notify={summary['would_notify']} "
            f"notified={summary['notified']} apply={apply} via_guard={via_guard}"
        )
        for r in results:
            if r.get("action") in ("would_notify", "notified", "notify_failed"):
                print(f"  #{r['pr']} {r['action']} {r.get('title', '')[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

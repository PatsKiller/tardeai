#!/usr/bin/env python3
"""Request a Telegram Approve for a PR (Mergify go-signal).

DEFAULT (2026-10-27): add the PR to the NEXT DIGEST and print when it goes. The operator
approves once per digest (scripts/pr_merge_digest.py); no per-PR Telegram prompt is sent.
Agents: open the PR and stop — you do not need to run this at all; the digest finds every
ready PR. ``--single`` keeps the coordinator's ad-hoc one-PR prompt (the old behaviour).

Usage
-----
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208            # next digest
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --single   # ad-hoc prompt
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --wait
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --native
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --dry-run

``--single`` default (PR #2185, Telegram guard grants retired): the dedicated
``prmapprove`` buttons (native). The old ``--via-guard`` chicken-egg bridge asked
for a short ``telegram`` guard grant through the ``gapprove`` buttons; that is a
Telegram-issued guard grant, so it now refuses (``GUARD_BRIDGE_RETIRED``) before
minting anything.
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


def _pr_view(pr: int, repo: str) -> dict:
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "number,title,url,headRefOid,state,labels,files",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"gh pr view failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pr", type=int, required=True, help="Pull request number")
    p.add_argument("--repo", default=os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai"))
    p.add_argument("--reason", default="", help="Shown on the Telegram card")
    p.add_argument("--ttl", type=int, default=0, help="Seconds until the request expires (default 24h)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument(
        "--via-guard",
        action="store_true",
        default=None,
        help="Use the gapprove guard bridge (retired with Telegram guard grants, PR #2185: refuses)",
    )
    p.add_argument(
        "--native",
        action="store_true",
        help="Use prmapprove buttons (the default while Telegram guard grants are retired)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="After send, wait for Telegram Approve and apply operator-merge",
    )
    p.add_argument("--timeout", type=int, default=900, help="--wait timeout seconds (default 900)")
    p.add_argument(
        "--single",
        action="store_true",
        help="Coordinator ad-hoc: send a per-PR Approve prompt now instead of adding to the next digest",
    )
    args = p.parse_args(argv)

    from scripts.lib import pr_merge_telegram as pmt

    # The guard bridge needs a Telegram guard grant; while those are retired (PR #2185) the
    # default is the native prmapprove path. An explicit --via-guard / env=1 still asks, and refuses.
    via_default = "0" if pmt.guard_bridge_retired() else "1"
    env_via = os.environ.get("PR_MERGE_TELEGRAM_VIA_GUARD", via_default).strip() not in ("0", "false", "no")
    via_guard = (not args.native) and (args.via_guard if args.via_guard is not None else env_via)

    view = _pr_view(args.pr, args.repo)
    if str(view.get("state") or "").upper() != "OPEN":
        print(f"PR #{args.pr} is not OPEN (state={view.get('state')})", file=sys.stderr)
        return 2
    labels = {str(x.get("name") if isinstance(x, dict) else x) for x in (view.get("labels") or [])}
    if pmt.LABEL in labels and not args.dry_run:
        out = {
            "ok": True,
            "skipped": "already_has_operator_merge",
            "pr_number": args.pr,
            "label": pmt.LABEL,
        }
        print(json.dumps(out, indent=2) if args.as_json else f"skip: #{args.pr} already has {pmt.LABEL}")
        return 0

    if not args.single:
        from scripts.lib import pr_merge_digest as pmd

        when = pmd.next_digest_at()
        out = {
            "ok": True,
            "pr_number": int(view["number"]),
            "action": "would_add_to_next_digest" if args.dry_run else "added_to_next_digest",
            "next_digest_at": when,
            "note": "The digest lists the PR only when READY (not draft, four checks green on the head, "
            "not held). Coordinator can send now: scripts/pr_merge_digest.py --apply --now",
        }
        if not args.dry_run:
            pmd.nominate(
                int(view["number"]),
                head_sha=str(view.get("headRefOid") or ""),
                title=str(view.get("title") or ""),
                reason=args.reason,
            )
        if args.as_json:
            print(json.dumps(out, indent=2))
        else:
            print(f"pr=#{out['pr_number']} {out['action']} — next digest {when}")
        return 0

    from scripts.lib import merge_hold_paths as mhp

    held = sorted(labels & mhp.hold_labels()) + sorted(
        mhp.held_classes([str(f.get("path") if isinstance(f, dict) else f) for f in (view.get("files") or [])])
    )
    if held:
        print(
            f"refused: #{args.pr} is held ({', '.join(held)}) — needs operator merge; "
            f"no Telegram Approve is offered (config/merge_hold_paths.json)",
            file=sys.stderr,
        )
        return 3

    kw = dict(
        pr_number=int(view["number"]),
        title=str(view.get("title") or ""),
        head_sha=str(view.get("headRefOid") or ""),
        url=str(view.get("url") or ""),
        reason=args.reason or "Ready for Mergify — tap Approve (no GitHub needed)",
        repo=args.repo,
        dry_run=bool(args.dry_run),
    )
    if args.ttl > 0:
        kw["ttl"] = args.ttl

    if via_guard:
        result = pmt.mint_and_notify_via_guard(**kw)
    else:
        result = pmt.mint_and_notify(**kw)

    if args.wait and result.get("ok") and not args.dry_run and via_guard:
        wait_out = pmt.wait_guard_and_apply(
            pr_number=int(view["number"]),
            request_id=str(result.get("request_id") or ""),
            timeout_s=int(args.timeout),
        )
        result["wait"] = wait_out
        if not wait_out.get("ok"):
            result["ok"] = False

    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(
            f"pr=#{result.get('pr_number')} request_id={result.get('request_id')} "
            f"via={result.get('via', 'native')} ok={result.get('ok')} "
            f"telegram={result.get('telegram')}"
        )
        if result.get("wait"):
            print(f"wait={result['wait']}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

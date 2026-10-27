#!/usr/bin/env python3
"""Request a Telegram Approve for a PR (Mergify go-signal).

Usage
-----
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --wait
  .venv/bin/python scripts/request_pr_merge_approve.py --prs 2216,2212,2211 --wait
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --native
  .venv/bin/python scripts/request_pr_merge_approve.py --pr 2208 --dry-run

Default path (``--via-guard``, the chicken-egg bridge): Telegram Approve uses
the live ``gapprove`` buttons already on CURRENT. After you tap Approve this
script (with ``--wait``) adds the ``operator-merge`` label. No GitHub UI.

When two or more PRs need Approve at once, use ``--prs`` (a digest). One Telegram
card and one ``telegram`` grant cover the batch. Parallel ``--pr --wait`` floods
collide on the one-use bridge grant (ACTIVE_GRANT_EXISTS / SUPERSEDED) — do not.

After this code is promoted to CURRENT, pass ``--native`` (or set
``PR_MERGE_TELEGRAM_VIA_GUARD=0``) so the dedicated ``prmapprove`` buttons are
used instead.
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
            "number,title,url,headRefOid,state,labels",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"gh pr view failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return json.loads(proc.stdout)


def _parse_prs(raw: str) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for part in str(raw or "").replace(" ", ",").split(","):
        part = part.strip().lstrip("#")
        if not part:
            continue
        if not part.isdigit():
            raise SystemExit(f"bad --prs token: {part!r}")
        n = int(part)
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pr", type=int, default=0, help="Single pull request number")
    p.add_argument(
        "--prs",
        default="",
        help="Comma-separated PR numbers for a digest (preferred when ≥2 Approves)",
    )
    p.add_argument("--repo", default=os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai"))
    p.add_argument("--reason", default="", help="Shown on the Telegram card")
    p.add_argument("--ttl", type=int, default=0, help="Seconds until the request expires (default 24h)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument(
        "--via-guard",
        action="store_true",
        default=None,
        help="Use live gapprove bridge (default until CURRENT has prmapprove)",
    )
    p.add_argument(
        "--native",
        action="store_true",
        help="Use prmapprove buttons (needs CURRENT promote of this PR)",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="After send, wait for Telegram Approve and apply operator-merge",
    )
    p.add_argument("--timeout", type=int, default=900, help="--wait timeout seconds (default 900)")
    args = p.parse_args(argv)

    from scripts.lib import pr_merge_telegram as pmt

    env_via = os.environ.get("PR_MERGE_TELEGRAM_VIA_GUARD", "1").strip() not in ("0", "false", "no")
    via_guard = (not args.native) and (args.via_guard if args.via_guard is not None else env_via)

    digest_prs = _parse_prs(args.prs)
    if digest_prs and args.pr:
        raise SystemExit("use --pr OR --prs, not both")
    if not digest_prs and not args.pr:
        raise SystemExit("pass --pr N or --prs N,M,...")

    # ---- digest path (≥2 PRs, one Telegram Approve) ----
    if digest_prs:
        if len(digest_prs) == 1:
            # Convenience: one number in --prs behaves like --pr
            args.pr = digest_prs[0]
            digest_prs = []
        else:
            items: list[dict] = []
            skipped: list[dict] = []
            for n in digest_prs:
                view = _pr_view(n, args.repo)
                if str(view.get("state") or "").upper() != "OPEN":
                    skipped.append({"pr_number": n, "reason": f"not_open:{view.get('state')}"})
                    continue
                labels = {
                    str(x.get("name") if isinstance(x, dict) else x)
                    for x in (view.get("labels") or [])
                }
                if pmt.LABEL in labels and not args.dry_run:
                    skipped.append({"pr_number": n, "reason": "already_has_operator_merge"})
                    continue
                items.append(
                    {
                        "pr_number": int(view["number"]),
                        "title": str(view.get("title") or ""),
                        "head_sha": str(view.get("headRefOid") or ""),
                        "url": str(view.get("url") or ""),
                    }
                )
            if len(items) < 2:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "reason": "digest_needs_2_open_unlabeled",
                            "items": items,
                            "skipped": skipped,
                        },
                        indent=2,
                    )
                    if args.as_json
                    else f"digest needs ≥2 open unlabeled PRs; got {len(items)} "
                    f"(skipped={skipped})",
                    file=sys.stderr if not args.as_json else sys.stdout,
                )
                return 2
            reason = args.reason or (
                f"Digest of {len(items)} PRs — one tap queues all for Mergify"
            )
            kw = dict(
                items=items,
                reason=reason,
                repo=args.repo,
                dry_run=bool(args.dry_run),
            )
            if args.ttl > 0:
                kw["ttl"] = args.ttl
            if via_guard:
                result = pmt.mint_and_notify_via_guard_digest(**kw)
            else:
                # Native digest: mint row + native interrupt (prmapprove).
                if args.dry_run:
                    result = {
                        "ok": True,
                        "dry_run": True,
                        "kind": "digest",
                        "pr_numbers": [i["pr_number"] for i in items],
                        "via": "native",
                        "would_send": True,
                        "label": pmt.LABEL,
                    }
                else:
                    rec = pmt.mint_digest_request(
                        items=items,
                        reason=reason,
                        repo=args.repo,
                        ttl=args.ttl if args.ttl > 0 else pmt.DEFAULT_TTL_SECONDS,
                    )
                    ok, detail, ids = pmt.send_interrupt(
                        pmt.format_message(rec), pmt.keyboard(rec["request_id"])
                    )
                    pmt.record_delivery(rec["request_id"], accepted=ok, message_ids=ids)
                    result = {
                        "ok": ok,
                        "kind": "digest",
                        "pr_numbers": list(rec["pr_numbers"]),
                        "request_id": rec["request_id"],
                        "via": "native",
                        "telegram": detail,
                        "message_ids": ids,
                        "label": pmt.LABEL,
                    }
            if skipped:
                result["skipped"] = skipped
            if args.wait and result.get("ok") and not args.dry_run and via_guard:
                wait_out = pmt.wait_guard_and_apply_digest(
                    request_id=str(result.get("request_id") or ""),
                    pr_numbers=list(result.get("pr_numbers") or []),
                    timeout_s=int(args.timeout),
                    repo=args.repo,
                )
                result["wait"] = wait_out
                if not wait_out.get("ok"):
                    result["ok"] = False
            if args.as_json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(
                    f"digest prs={result.get('pr_numbers')} "
                    f"request_id={result.get('request_id')} "
                    f"via={result.get('via', 'native')} ok={result.get('ok')} "
                    f"telegram={result.get('telegram')}"
                )
                if result.get("wait"):
                    print(f"wait={result['wait']}")
            return 0 if result.get("ok") else 1

    # ---- single-PR path ----
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

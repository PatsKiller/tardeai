#!/usr/bin/env python3
"""Host entrypoint for tradeai-deploy-on-main.timer (AGENTS.md §25.10).

Default is dry (decide + receipt, no prepare/promote). Live promote needs --apply
and an armed deploy delegation (or TRADEAI_DEPLOY_DELEGATION_SOFT=1 for lab).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _policy_broadcast(result: dict, *, repo: Path, apply: bool) -> dict:
    """AGENTS.md version-change broadcast (scripts/lib/policy_version_broadcast.py), after the poll.

    The poll just fetched origin/main, so a new Policy-Version on main is seen within one tick. Dry run unless this is
    the host timer's ``--apply`` (and not ``--dry-run``). Skipped when the fetch failed (origin/main may be old).
    Never changes the poll's outcome or exit code: a failure is reported in the receipt.
    """
    if "fetch_failed" in str(result.get("reason") or ""):
        return {"action": "skipped", "reason": "fetch_failed"}
    try:
        from scripts.lib.policy_version_broadcast import run

        return run(repo, apply=apply)
    except Exception as exc:  # noqa: BLE001 - the deploy poller must not fail on the broadcast
        return {"action": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Poll origin/main vs CURRENT; promote when ahead")
    ap.add_argument("--repo", type=Path, default=ROOT, help="git checkout with origin/main")
    ap.add_argument("--apply", action="store_true", help="run prepare+promote (default: decide only)")
    ap.add_argument("--dry-run", action="store_true", help="never invoke deploy script even with --apply")
    ap.add_argument("--no-fetch", action="store_true", help="skip git fetch origin main")
    ap.add_argument("--json", action="store_true", help="print result JSON")
    args = ap.parse_args(argv)

    from scripts.lib.deploy_on_main import poll_once

    result = poll_once(
        repo=args.repo.resolve(),
        dry_run=bool(args.dry_run),
        fetch=not args.no_fetch,
        apply=bool(args.apply),
    )
    result["policy_broadcast"] = _policy_broadcast(
        result, repo=args.repo.resolve(), apply=args.apply and not args.dry_run
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"deploy_on_main action={result.get('action')} "
            f"outcome={result.get('outcome', result.get('reason'))} "
            f"main={result.get('main_sha', '')[:12]} "
            f"current={result.get('current_sha', '')[:12]}"
        )
        pb = result["policy_broadcast"]
        print(f"policy_broadcast mode={pb.get('mode', '-')} action={pb.get('action')} version={pb.get('version', '-')}")
    outcome = str(result.get("outcome") or result.get("action") or "")
    if outcome in ("deploy_failed", "verify_failed"):
        return 1
    if result.get("action") == "refuse" and "fetch_failed" in str(result.get("reason")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

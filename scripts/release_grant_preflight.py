#!/usr/bin/env python3
"""Release-grant preflight for cio_phase2_exact_main_deploy.sh (prepare/promote).

Exit 0 when a release-write grant is bound to THIS release (PR/SHA/campaign);
exit 2 when refused. ``TRADEAI_RELEASE_GRANT_BINDING=warn`` prints the refusal
and exits 0 (visible degradation, transition only). Prints one JSON line.
No credential is read or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.release_grant_binding import ReleaseAction, decide_from_disk  # noqa: E402


GUARD_LEDGER = ROOT / ".cursor" / "hooks" / "guard_ledger.py"


def consume_release_grant(*, tier: str = "release-write", runner=None) -> dict:
    """Decrement one use of the active grant through the guard's own ledger CLI.

    Fail-soft: a missing ledger CLI or a consume error is REPORTED in the
    preflight JSON, never allowed to block a release the binding already
    approved (the binding is the control; consumption is the accounting).
    Disable with TRADEAI_GUARD_CONSUME=0.
    """
    if os.environ.get("TRADEAI_GUARD_CONSUME", "1") == "0":
        return {"ok": False, "skipped": "disabled"}
    if not GUARD_LEDGER.is_file():
        return {"ok": False, "skipped": "guard_ledger.py absent"}
    import subprocess
    run = runner or subprocess.run
    try:
        proc = run([sys.executable, str(GUARD_LEDGER), "consume", "--tier", tier],
                   capture_output=True, text=True, timeout=20)
        last = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
        body = json.loads(last[-1]) if last else {}
        return {"ok": proc.returncode == 0, "rc": proc.returncode, "tier": tier, **({"ledger": body} if body else {})}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--action", required=True, choices=("prepare", "promote", "rollback", "verify"))
    ap.add_argument("--sha", required=True)
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--campaign", default=os.environ.get("TRADEAI_RELEASE_CAMPAIGN") or None)
    args = ap.parse_args()
    mode = (os.environ.get("TRADEAI_RELEASE_GRANT_BINDING") or "enforce").lower()
    v = decide_from_disk(ReleaseAction(action=args.action, target_sha=args.sha, pr_number=args.pr, campaign=args.campaign))
    out = {**v.to_dict(), "mode": mode, "action": args.action, "sha": args.sha, "pr": args.pr}
    if v.allowed and args.action in ("prepare", "promote", "rollback"):
        # C-10 (2026-09-26): the deploy path never consumed a grant use, so the
        # ledger under-counted every Claude Code promote (both P1 grants showed
        # unconsumed uses after being exercised). One use per release action.
        out["consumed"] = consume_release_grant()
    print(json.dumps(out, sort_keys=True))
    if v.allowed:
        return 0
    if mode == "warn":
        print("RELEASE GRANT BINDING: REFUSED (warn mode — continuing): " + v.reason, file=sys.stderr)
        return 0
    print("RELEASE GRANT BINDING: REFUSED — " + v.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

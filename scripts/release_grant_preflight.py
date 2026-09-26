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

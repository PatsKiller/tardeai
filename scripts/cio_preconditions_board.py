#!/usr/bin/env python3
"""Print the four CIO persistent-spine preconditions as GREEN / RED, from live state.

    python3 scripts/cio_preconditions_board.py --root CURRENT
    python3 scripts/cio_preconditions_board.py --root CURRENT --json
    python3 scripts/cio_preconditions_board.py --no-http        # records only

Read-only and dry by default — there is no --apply, because there is nothing this
board could legitimately apply. It reads the record store, one HTTP payload, the
policy file and the running server's environment, and writes nothing.

The four:
    1. S0 attach + rehydrate
    2. CC shows a non-SCHD held narrative + the cash letter WITHOUT a ping
    3. Grok critique attach OR reject persisted on a record
    4. dust / CASH-as-a-ticker cannot fire

`--root` matters more than it looks. CIOPlanStore and friends use RELATIVE paths,
so they follow the CWD; run this from a worktree with no data/ and every record
check would report zero. That failure mode is why a wrong root yields
CANNOT_VERIFY with the resolved path, never RED.

Exit code is 0 whenever the board was produced. A RED is a finding to read, not a
crash — use --fail-on-red in a gate that wants it to be one.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. Sends no Telegram, makes no
vendor/LLM call, changes no flag.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "operator-run CLI entry point: CIOPreconditionsBoard@v1 is the shape this "
    "script prints and its consumer is a person deciding whether the persistent "
    "spine is load-bearing enough to build on. Wiring it into the product would "
    "make the spine grade its own homework, which is the exact failure the board "
    "exists to catch."
)

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib.cio_preconditions_board import (  # noqa: E402
    CANNOT_VERIFY, GREEN, RED, build_board, render,
)

LIVE_ROOT = "/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"
HOME_URL = "http://127.0.0.1:7777/api/v3/cio/home"


def fetch_home(url: str, timeout: float) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """GET the live payload. A failure is reported, never swallowed into a RED."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace")), None
    except Exception as exc:                                     # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=LIVE_ROOT,
                    help=f"tree holding data/cio (default: {LIVE_ROOT})")
    ap.add_argument("--home-url", default=HOME_URL)
    ap.add_argument("--no-http", action="store_true",
                    help="skip the CC payload; check 2 becomes CANNOT_VERIFY")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, help="write the JSON board to a file")
    ap.add_argument("--fail-on-red", action="store_true",
                    help="exit 1 if any check is RED (CANNOT_VERIFY never fails)")
    args = ap.parse_args(argv)

    home: Optional[dict[str, Any]] = None
    home_error: Optional[str] = None
    if args.no_http:
        home_error = "--no-http"
    else:
        home, home_error = fetch_home(args.home_url, args.timeout)

    board = build_board(args.root, home=home, home_error=home_error, repo=REPO)
    board["home_url"] = None if args.no_http else args.home_url
    board["home_error"] = home_error

    text = json.dumps(board, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text if args.json else render(board))

    if args.fail_on_red and board["counts"].get(RED):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

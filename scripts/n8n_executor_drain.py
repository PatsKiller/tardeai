#!/usr/bin/env python3
"""Ask the n8n run executor to hand over to a newly promoted release without killing its in-flight runs.

Called by ``restart_root_frozen_units`` in scripts/cio_phase2_exact_main_deploy.sh before it would restart
``tradeai-n8n-run-executor.service`` (LQ-20261107-137). It writes ``ExecutorDrainRequest@v1`` and waits up to
``--wait-s`` for the executor to be running from ``--target``. The last stdout line is the result token the deploy
reads:

  DRAIN_RESULT=re_resolved        the executor finished its runs, exited, and systemd started it on the target
  DRAIN_RESULT=deferred_draining  it is draining a long run; it restarts itself when idle (or at the deadline)
  DRAIN_RESULT=not_acknowledged   it never reported draining (an executor older than this code): restart it

Any other outcome (a crash, no token) means the deploy restarts the unit the old way.

LQ-20261107-1685 (D + E):

* ``--deadline-s`` is raised to the longest in-flight lane timeout plus the lost grace (floor 2400 s), so the
  backstop never meets a live child. ``--no-deadline-from-status`` keeps the fixed value (tests).
* In regular market hours on a trading day, a request that would stop every start while a run older than
  300 s is in flight is refused with exit 3 and ``DRAIN_RESULT=refused_market_busy``; it writes no request.
  ``--wait-max S`` waits up to S seconds (re-checking every 30 s) for that run to end, then refuses.

``--dry-run`` prints what it would write and touches nothing. ``--no-systemd`` skips the live cwd read-back
(tests). AUTHORITY: READ_ONLY_ADVISORY. Writes one request file; never signals, restarts or kills a process.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_executor_drain as D  # noqa: E402


def _state_root(arg: str | None) -> Path:
    return Path(arg or os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def _on_target(unit: str, target: Path, use_systemd: bool):
    if not use_systemd:
        return lambda: False
    from scripts.lib import current_bound_units as cbu

    def check() -> bool:
        try:
            return bool(cbu.verify(str(target), [unit]).get(unit, {}).get("ok"))
        except Exception:  # noqa: BLE001 - an unreadable cwd is "not yet"
            return False

    return check


def _allowlist_doc(path: str | None, root: Path) -> dict | None:
    """The new release's N8nRunAllowlist@v1 (for lane timeouts), or None when unreadable."""
    candidates = [Path(path)] if path else [root / "config" / "n8n_run_allowlist.json"]
    for candidate in candidates:
        try:
            doc = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("lanes"), list):
            return doc
    return None


def cmd_request(args: argparse.Namespace) -> int:
    target = Path(args.target)
    if not target.is_dir():
        print(json.dumps({"error": "target_not_a_directory", "target": str(target)}))
        print(f"DRAIN_RESULT={D.RESULT_NOT_ACKED}")
        return 0
    state = _state_root(args.state_root)
    now = args.now
    allow = _allowlist_doc(args.allowlist, ROOT)
    # LQ-20261107-1685 (E): in market hours a drain stops every start while a long run is in flight.
    deadline_s = args.deadline_s
    if args.deadline_from_status:
        deadline_s = max(
            deadline_s, D.deadline_for((D.read_status(state) or {}).get("busy"), allow, default=deadline_s)
        )
    guard = D.market_guard(D.read_status(state), now=now, allowlist=allow)
    waited = 0.0
    while guard is not None and args.wait_max and waited < args.wait_max:
        time.sleep(min(30.0, args.wait_max - waited))
        waited += 30.0
        now = time.time()
        guard = D.market_guard(D.read_status(state), now=now, allowlist=allow)
    if guard is not None:
        print(
            json.dumps(
                {
                    "refused": guard,
                    "target": str(target.resolve()),
                    "would_write": str(D.request_path(state)),
                    "waited_s": waited,
                }
            )
        )
        print(f"DRAIN_RESULT={D.RESULT_REFUSED_MARKET_BUSY}")
        return 3
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "would_write": str(D.request_path(state)),
                    "target": str(target.resolve()),
                    "deadline_s": deadline_s,
                }
            )
        )
        return 0
    path = D.write_request(
        state, target, now=args.now, deadline_s=deadline_s, requested_by=args.requested_by
    )
    result = D.wait_for_drain(
        state,
        target,
        on_target=_on_target(args.unit, target, not args.no_systemd),
        wait_s=args.wait_s,
        ack_s=args.ack_s,
        poll_s=args.poll_s,
    )
    print(json.dumps({"request": str(path), "target": str(target.resolve()), "unit": args.unit, "result": result}))
    print(f"DRAIN_RESULT={result}")
    return 0


def cmd_retarget(args: argparse.Namespace) -> int:
    """Point a leftover drain request at ``--target`` (never creates one) and read it back (LQ-20261107-2246)."""
    out = D.retarget(_state_root(args.state_root), Path(args.target), now=args.now)
    print(json.dumps(out))
    print(f"RETARGET_RESULT={out['result']}")
    return 0 if out["result"] in ("ok", "absent") else 5


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("request", help="write the drain request and wait for the hand-over")
    r.add_argument("--target", required=True, help="the release directory just promoted")
    r.add_argument("--unit", default=D.EXECUTOR_UNIT)
    r.add_argument("--state-root")
    r.add_argument("--allowlist", default=None, help="N8nRunAllowlist@v1 for lane timeouts (default: this tree's)")
    r.add_argument("--wait-s", type=float, default=90.0)
    r.add_argument("--ack-s", type=float, default=20.0)
    r.add_argument("--poll-s", type=float, default=2.0)
    r.add_argument("--deadline-s", type=float, default=D.DEFAULT_DEADLINE_S)
    r.add_argument(
        "--no-deadline-from-status",
        dest="deadline_from_status",
        action="store_false",
        help="do not raise --deadline-s to the longest in-flight lane timeout; the fixed default is used (tests)",
    )
    r.add_argument(
        "--wait-max",
        type=float,
        default=0.0,
        help="when the market guard refuses, wait up to this many seconds (re-checking every 30 s), then refuse",
    )
    r.add_argument(
        "--now",
        type=float,
        default=None,
        help="evaluate the market guard and stamp the request at this epoch seconds (tests and dry runs only)",
    )
    r.add_argument("--requested-by", default="deploy")
    r.add_argument("--no-systemd", action="store_true", help="skip the live cwd read-back (tests)")
    r.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("retarget", help="point a leftover request at --target and read it back; exit 5 on mismatch")
    t.add_argument("--target", required=True)
    t.add_argument("--state-root")
    t.add_argument("--now", type=float, default=None)
    args = ap.parse_args(argv)
    return {"request": cmd_request, "retarget": cmd_retarget}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

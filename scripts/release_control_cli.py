#!/usr/bin/env python3
"""Host CLI for the release-train control state (Release Train v2, decision D3). Wired into nothing.

This is the ONLY entrypoint that builds a ``HostCliProof``: stdin must be a TTY, and for every operator command
(arm, resume, change-scope, revoke) the operator re-types the phrase the library prints, which names the epoch
the command will create. The Command Center may only request STOP or pause (through its own typed endpoint,
not this file); n8n never calls this. It works when CC and n8n are down: it reads and writes local files only.

  status                                   control mode, epoch, latch (ABSENT/SET/UNREADABLE), stop phase
  stop   --reason TEXT                     latch STOP + new epoch (safe direction; no confirmation)
  pause  --reason TEXT                     pause after the current train
  arm    --delegation PATH --reason TEXT   accept the delegation's digest; RUNNING with a new epoch
  resume --reason TEXT                     archive the latch (rename), new epoch, RUNNING (shows state first)
  change-scope --delegation PATH --reason  accept a changed delegation digest; new epoch
  revoke --reason TEXT                     stop automation; new epoch

Every mutating command supports --dry-run, which prints the transition and the phrase and writes nothing
(AGENTS §0 rule 7). Exit: 0 ok, 2 refused, 3 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import release_control as RC  # noqa: E402
from scripts.lib import release_delegation as RD  # noqa: E402

HOME = Path.home()
STATE_ROOT = Path(os.environ.get("TRADEAI_STATE_ROOT", str(HOME / "trade-ai-releases" / "persistent-state")))
#: Same directory as scripts/release_window.py STATE_DIR, so STOP.json is one latch.
STATE_DIR = Path(os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR",
                                str(STATE_ROOT / "data" / "runtime" / "release_window")))
OPERATOR_COMMANDS = ("arm", "resume", "change-scope", "revoke")


def _print(obj: dict) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def _proof(ctl: RC.ReleaseControl, command: str, *, stdin=None) -> RC.HostCliProof:
    stdin = stdin or sys.stdin
    if not stdin.isatty():
        raise RC.ControlRefused("NOT_A_TTY", f"{command} is typed by the operator at the host, never piped")
    phrase = ctl.expected_phrase(command.replace("-", "_"))
    print(f"Type exactly: {phrase}", file=sys.stderr)
    typed = stdin.readline().strip()
    return RC.HostCliProof(tty=os.ttyname(stdin.fileno()), uid=os.getuid(), confirmation=typed)


def _status(ctl: RC.ReleaseControl) -> dict:
    v = ctl.view()
    return {"mode": v.mode, "epoch": v.epoch, "version": v.version, "latch_state": v.latch_state,
            "latch": v.latch, "stop_phase": v.stop_phase, "stop": v.stop, "pause": v.pause,
            "current_train_id": v.current_train_id, "accepted_policy_digest": v.accepted_policy_digest,
            "mutation_refusal": v.mutation_refusal(v.current_train_id), "error": v.error, "state_dir": str(ctl.root)}


def main(argv: list[str] | None = None, *, stdin=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--state-dir", type=Path, default=STATE_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("stop", "pause", "resume", "revoke"):
        p = sub.add_parser(name)
        p.add_argument("--reason", required=True)
        p.add_argument("--dry-run", action="store_true")
    for name in ("arm", "change-scope"):
        p = sub.add_parser(name)
        p.add_argument("--delegation", type=Path, default=RD.DEFAULT_PATH)
        p.add_argument("--reason", required=True)
        p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    ctl = RC.ReleaseControl(args.state_dir)
    try:
        if args.cmd == "status":
            _print(_status(ctl))
            return 0
        actor = RC.Actor("host_cli", f"uid:{os.getuid()}")
        digest = None
        if args.cmd in ("arm", "change-scope"):
            dv = RD.load(args.delegation)
            if not dv.authorized:
                _print({"outcome": "REFUSED", "code": f"DELEGATION_{dv.code}", "detail": dv.detail})
                return 2
            digest = dv.digest
        if getattr(args, "dry_run", False):
            _print({"outcome": "DRY_RUN", "command": args.cmd, "current": _status(ctl), "policy_digest": digest,
                    "phrase": ctl.expected_phrase(args.cmd.replace("-", "_"))
                    if args.cmd in OPERATOR_COMMANDS else None, "writes": "nothing"})
            return 0
        if args.cmd == "stop":
            _print(ctl.request_stop(actor, args.reason))
        elif args.cmd == "pause":
            _print(ctl.request_pause(actor, args.reason))
        else:
            print(json.dumps({"current": _status(ctl)}, indent=2, default=str), file=sys.stderr)
            proof = _proof(ctl, args.cmd, stdin=stdin)
            if args.cmd == "arm":
                _print(ctl.arm(actor, proof, policy_digest=digest, reason=args.reason))
            elif args.cmd == "change-scope":
                _print(ctl.change_scope(actor, proof, policy_digest=digest, reason=args.reason))
            elif args.cmd == "revoke":
                _print(ctl.revoke(actor, proof, reason=args.reason))
            else:
                readiness = {"checked_at": RC.utc_iso(ctl.clock()), "shown": _status(ctl)}
                _print(ctl.resume(actor, proof, reason=args.reason, readiness=readiness))
        return 0
    except RC.ControlRefused as exc:
        _print({"outcome": "REFUSED", "code": exc.code, "detail": exc.detail})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

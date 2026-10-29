#!/usr/bin/env python3
"""policy_version_broadcast.py — when a new AGENTS.md Policy-Version reaches origin/main, tell every open claim and
the operator, once.

Operator, 2026-10-28: "How about if we go to [version] 27? How do the agents automatically know to check in to see if
there's a new one?" The gates (scripts/lib/policy_freshness.py) stop an agent at its next claim, commit or push; this
reaches the agents already mid-task.

What one run does (``run(repo, apply=...)``), keyed on origin/main's Policy-Version (no version is hard-coded):

* **No state yet** -> records a baseline (the version now on main); marks nothing and sends nothing, so installing this
  never announces a version that went live before it existed.
* **Same version as the state** -> nothing, except retrying a Telegram line that was not delivered (at most
  ``MAX_TELEGRAM_ATTEMPTS`` sends per version; the claim marks are never re-written).
* **New version** -> every open claim on the board (status ``active``, not released/abandoned) whose recorded
  ``policy_version`` differs is marked ``policy_changed`` (sidecar ``<claims_dir>/policy_changed/<claim_id>.json``;
  ``agent_claim.py status`` shows it until the claim heartbeats from a fresh worktree), then ONE Telegram line goes to
  the operator through the system send path (``autonomy_watchdog.telegram_system.send_system``), deduplicated per
  version by its identity ``policy-version-live:<version>``:
  ``AGENTS.md 27.0.0 is live; 3 open claims were on 26.0.0 and have been told``.

Dry run first (§0 rule 7): ``apply=False`` computes and returns everything above and writes and sends nothing. The live
path is the host timer only: ``scripts/deploy_on_main_poll.py --apply`` (tradeai-deploy-on-main.service) calls it
after each poll whose fetch succeeded. Never raises into the poller.

State: ``<claims_dir>/policy_broadcast_state.json`` (PolicyBroadcastState@v1).
AUTHORITY: coordination files + one operator Telegram line per Policy-Version; no broker, DB, scheduler or git write.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import policy_freshness as PF  # noqa: E402

STATE_SCHEMA = "PolicyBroadcastState@v1"
RESULT_SCHEMA = "PolicyBroadcastRun@v1"
STATE_NAME = "policy_broadcast_state.json"
IDENTITY_PREFIX = "policy-version-live:"
KIND = "policy_version_live"
FINISHED_STAGES = ("released", "abandoned")
MAX_TELEGRAM_ATTEMPTS = 6  # an undelivered line is retried on later polls, at most this many sends per version

Sender = Callable[..., dict]  # send_system(text, *, identity, kind) -> record


def state_path(claims_dir: Path | str) -> Path:
    return Path(claims_dir) / STATE_NAME


def read_state(path: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("schema") == STATE_SCHEMA else None


def _write_state(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    B._replace_own(path, {**doc, "schema": STATE_SCHEMA})


def open_claims(board: B.ClaimBoard) -> list[B.ClaimView]:
    views, _bad = board.views()
    return [v for v in views if v.doc.get("status") == "active" and v.stage not in FINISHED_STAGES]


def telegram_line(version: str, n: int, were_on: list[str]) -> str:
    on = "/".join(were_on) if were_on else "an older version"
    noun = "open claim was" if n == 1 else "open claims were"
    return f"AGENTS.md {version} is live; {n} {noun} on {on} and have been told"


def _default_sender() -> Sender:
    from scripts.lib.autonomy_watchdog.telegram_system import send_system

    return send_system


def _delivered(rec: dict | None) -> bool:
    return bool(rec and rec.get("ok") and not rec.get("suppressed"))


def run(
    repo: Path | str,
    *,
    apply: bool,
    claims_dir: Path | str | None = None,
    sender: Sender | None = None,
    board: B.ClaimBoard | None = None,
) -> dict[str, Any]:
    """One broadcast pass against the already-fetched origin/main. Returns a PolicyBroadcastRun@v1 receipt."""
    board = board or B.ClaimBoard(claims_dir)
    out: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "mode": "apply" if apply else "dry_run",
        "at": B.iso(board.now()),
        "claims_dir": str(board.dir),
        "action": "none",
        "marked": [],
        "telegram": None,
    }
    remote = PF.remote_policy(repo)
    version, blob = remote["version"], remote["blob"]
    out.update(version=version, blob=blob)
    if not version or not blob:
        out.update(action="unknown", reason="origin/main has no readable AGENTS.md Policy-Version (not fetched?)")
        return out
    sp = state_path(board.dir)
    state = read_state(sp)
    out["previous_version"] = (state or {}).get("version")
    if state is None:
        out["action"] = "baseline"
        if apply:
            _write_state(sp, {"version": version, "blob": blob, "at": out["at"], "told": 0, "baseline": True})
        return out
    if state.get("version") == version:
        attempts = int(state.get("telegram_attempts") or 1)
        if state.get("telegram_delivered") is False and state.get("text") and attempts < MAX_TELEGRAM_ATTEMPTS:
            out["action"] = "retry_telegram"
            out["telegram"] = {"text": state["text"], "would_send": not apply}
            if apply:
                rec = (sender or _default_sender())(state["text"], identity=IDENTITY_PREFIX + version, kind=KIND)
                out["telegram"] = {"text": state["text"], "record": rec}
                _write_state(
                    sp,
                    {
                        **state,
                        "telegram_delivered": _delivered(rec),
                        "telegram_at": out["at"],
                        "telegram_attempts": attempts + 1,
                    },
                )
        return out

    previous = state.get("version")
    claims = [v for v in open_claims(board) if v.doc.get("policy_version") != version]
    were_on = sorted({str(v.doc.get("policy_version") or previous or "unrecorded") for v in claims})
    text = telegram_line(version, len(claims), were_on or ([previous] if previous else []))
    out.update(action="broadcast", were_on=were_on)
    message = (
        f"AGENTS.md {version} is now on origin/main (this claim recorded"
        " {cv}); re-read AGENTS.md §0, rebase onto fresh origin/main, then heartbeat from that worktree"
    )
    for v in claims:
        mark = {
            "claim_id": v.claim_id,
            "claim_policy_version": v.doc.get("policy_version"),
            "from_version": previous,
            "to_version": version,
            "to_blob": blob,
            "marked_at": out["at"],
            "message": message.format(cv=v.doc.get("policy_version") or "no version"),
        }
        out["marked"].append({k: mark[k] for k in ("claim_id", "claim_policy_version", "to_version")})
        if apply:
            B.write_policy_mark(board.dir, v.claim_id, mark)
    out["telegram"] = {"text": text, "would_send": not apply}
    if apply:
        rec = (sender or _default_sender())(text, identity=IDENTITY_PREFIX + version, kind=KIND)
        out["telegram"] = {"text": text, "record": rec}
        _write_state(
            sp,
            {
                "version": version,
                "blob": blob,
                "previous_version": previous,
                "at": out["at"],
                "told": len(claims),
                "text": text,
                "telegram_delivered": _delivered(rec),
                "telegram_attempts": 1,
            },
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=ROOT)
    ap.add_argument("--claims-dir", default=None)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true", help="host timer path only (deploy_on_main_poll.py --apply)")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.repo, apply=a.apply, claims_dir=a.claims_dir), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
